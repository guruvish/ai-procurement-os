"""LangGraph orchestration.

    START -> extract_rfq --(ok)------> extract_quotations --(>=1 quote)--> evaluate -> END
                         |--(review)-> needs_review -> END        |
                         |--(failed)-> failed -> END  <-(0 quotes)-

Design choices:
- AI (Gemini) only inside extract_* nodes; evaluation is deterministic Python.
- One bad supplier document never stops the batch: it is recorded and the rest continue.
- Completed stages are reused on re-run (no repeated AI cost, human corrections preserved)
  unless force=True.
- Human approval is NOT a graph node that an AI can pass: it is an explicit app action
  (db.record_decision) allowed only in READY_FOR_APPROVAL.
"""
import threading
import time
from datetime import date
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app import db
from app.agents import extractors
from app.agents.llm import ExtractionError, QuotaExhaustedError
from app.log import get_logger
from app.schemas import RFQRequirements, WorkflowStatus
from app.services.document_parser import DocumentError, parse_document
from app.services.evaluation_engine import evaluate_all, recommend

log = get_logger("workflow")
S = WorkflowStatus
STARTABLE = {S.DOCUMENTS_UPLOADED, S.EXTRACTION_REVIEW_REQUIRED, S.READY_FOR_APPROVAL, S.REJECTED, S.FAILED}
REEVALUABLE = {S.EXTRACTION_REVIEW_REQUIRED, S.READY_FOR_APPROVAL, S.REJECTED}
PROCESSING = {S.EXTRACTING, S.EVALUATING}
_progress = None      # optional global callback(str) (used by scripts/tests)
_lock = threading.Lock()
_active: set = set()  # request ids currently being processed in THIS app process
_jobs: dict = {}      # request id -> background job info (messages, result, error, thread)


def set_progress(fn) -> None:
    global _progress
    _progress = fn


def _say(msg: str, rid: str = "") -> None:
    job = _jobs.get(rid)
    if job is not None:
        job["messages"].append(msg)
    if _progress:
        try:
            _progress(msg)
        except Exception:  # the UI must never break processing
            pass


def is_running(rid: str) -> bool:
    return rid in _active


def is_stale(rid: str) -> bool:
    """Status says 'processing' but nothing is running (app restarted or run interrupted)."""
    return db.get_status(rid) in PROCESSING and not is_running(rid)


# ---------- background jobs: processing must survive page reruns / user clicks ----------
def start_processing(rid: str, force: bool = False, actor: str = "user") -> None:
    """Validate now (errors reach the user immediately), then process in a background thread."""
    _check_startable(rid)
    job = {"messages": [], "result": None, "error": None, "done": False, "started": time.time()}
    _jobs[rid] = job

    def _target():
        try:
            job["result"] = run_processing(rid, force, actor)
        except Exception as e:  # recorded for the UI; details are in the log
            job["error"] = str(e) if isinstance(e, db.WorkflowStateError) else f"Unexpected error ({type(e).__name__})"
        finally:
            job["done"] = True

    job["thread"] = threading.Thread(target=_target, name=f"process-{rid}", daemon=True)
    job["thread"].start()


def job(rid: str):
    return _jobs.get(rid)


def pop_finished_job(rid: str):
    j = _jobs.get(rid)
    if j and j["done"]:
        return _jobs.pop(rid)
    return None


def _check_startable(rid: str) -> None:
    status = db.get_status(rid)
    if is_running(rid):
        raise db.WorkflowStateError("This evaluation is already being processed.")
    if status not in STARTABLE and status not in PROCESSING:
        raise db.WorkflowStateError(f"Processing cannot start while the request is {status.value}.")
    if not any(d["doc_role"] == "RFQ" for d in db.list_documents(rid)):
        raise db.WorkflowStateError("Upload the RFQ document first.")


class ProcurementState(TypedDict, total=False):
    request_id: str
    force: bool
    rfq: Optional[dict]
    quotations: list       # [{"document_id", "quotation": dict}]
    doc_errors: list       # [{"filename", "error"}]
    review_reasons: list
    llm_calls: list        # one metrics dict per AI call
    reused: int            # stages reused from a previous run
    evaluations: list
    recommendation: dict
    outcome: str           # ok | review | failed
    error: str


def _parse(doc: dict):
    try:
        data = Path(doc["stored_path"]).read_bytes()
    except OSError:
        raise DocumentError(f"'{doc['filename']}' is missing from storage - please upload it again.")
    return parse_document(doc["filename"], data)


def _call(meta, filename: str, status: str = "ok") -> dict:
    d = meta.to_dict()
    d["document"] = filename
    d["status"] = status
    return d


# ---------- nodes ----------
def node_extract_rfq(state: ProcurementState) -> dict:
    rid = state["request_id"]
    rfq_docs = [d for d in db.list_documents(rid) if d["doc_role"] == "RFQ"]
    if not rfq_docs:
        return {"outcome": "failed", "error": "No RFQ document uploaded."}
    doc = rfq_docs[0]
    calls, reused = list(state.get("llm_calls", [])), state.get("reused", 0)

    existing = db.get_rfq(rid)
    if existing and not state.get("force") and doc["extraction_status"] in ("extracted", "validated"):
        rfq = existing
        reused += 1
        log.info(f"request={rid} node=extract_rfq reused previous extraction")
    else:
        _say(f"📄 Reading the RFQ ({doc['filename']})...", rid)
        try:
            parsed = _parse(doc)
            rfq, meta = extractors.extract_rfq(parsed, rfq_id=db.get_request(rid)["rfq_number"])
        except (DocumentError, ExtractionError) as e:
            db.update_document(doc["id"], "failed", str(e))
            log.warning(f"request={rid} node=extract_rfq failed: {type(e).__name__}")
            if getattr(e, "meta", None):
                calls.append(_call(e.meta, doc["filename"], "failed"))
            return {"outcome": "failed", "error": f"RFQ could not be processed: {e}", "llm_calls": calls}
        db.save_rfq(rid, rfq)
        db.update_document(doc["id"], "extracted", warnings=parsed.warnings)
        calls.append(_call(meta, doc["filename"]))

    reasons = list(state.get("review_reasons", []))
    missing = rfq.missing_core_fields()
    if missing:
        reasons.append(f"RFQ is missing: {', '.join(missing)} - please complete it before evaluation")
    if not rfq.technical_requirements:
        reasons.append("No technical requirements were found in the RFQ - please check the document")
    return {"rfq": rfq.model_dump(mode="json"), "review_reasons": reasons, "llm_calls": calls, "reused": reused}


def route_after_rfq(state: ProcurementState) -> str:
    if state.get("outcome") == "failed":
        return "failed"
    if any(r.startswith("RFQ is missing") for r in state.get("review_reasons", [])):
        return "review"
    return "quotes"


def node_extract_quotations(state: ProcurementState) -> dict:
    rid = state["request_id"]
    rfq = RFQRequirements.model_validate(state["rfq"])
    quotes, errors = [], []
    calls, reused = list(state.get("llm_calls", [])), state.get("reused", 0)
    reasons = list(state.get("review_reasons", []))

    docs = [d for d in db.list_documents(rid) if d["doc_role"] == "QUOTATION"]
    quota_hit = None
    for i, doc in enumerate(docs, 1):
        existing = db.get_quotation(doc["id"])
        if existing and not state.get("force"):
            quotes.append({"document_id": doc["id"], "quotation": existing.model_dump(mode="json")})
            reused += 1
            _say(f"♻️ {doc['filename']} - already read earlier, reused ({i}/{len(docs)})", rid)
            continue
        if quota_hit:  # daily quota gone: don't hammer the API, leave the rest for the next run
            msg = "Not read yet - daily AI quota reached. Run again after the reset."
            db.update_document(doc["id"], "pending", msg)
            errors.append({"filename": doc["filename"], "error": msg})
            continue
        _say(f"🤖 Reading {doc['filename']} ({i}/{len(docs)})...", rid)
        try:
            parsed = _parse(doc)
            q, meta = extractors.extract_quotation(parsed, rfq)
        except QuotaExhaustedError as e:
            quota_hit = e
            db.update_document(doc["id"], "pending", str(e))
            errors.append({"filename": doc["filename"], "error": str(e)})
            if getattr(e, "meta", None):
                calls.append(_call(e.meta, doc["filename"], "failed"))
            _say("⛔ Daily AI quota reached - remaining documents will be read on the next run.", rid)
            continue
        except (DocumentError, ExtractionError) as e:
            db.update_document(doc["id"], "failed", str(e))
            errors.append({"filename": doc["filename"], "error": str(e)})
            if getattr(e, "meta", None):
                calls.append(_call(e.meta, doc["filename"], "failed"))
            log.warning(f"request={rid} node=extract_quotations doc={doc['id']} failed: {type(e).__name__}")
            continue
        db.save_quotation(rid, doc["id"], q)
        db.update_document(doc["id"], q.extraction_status, warnings=parsed.warnings)
        _say(f"✅ {q.supplier_name} - extracted in {meta.latency_s:.0f}s ({meta.model})", rid)
        calls.append(_call(meta, doc["filename"]))
        quotes.append({"document_id": doc["id"], "quotation": q.model_dump(mode="json")})

    if errors:
        reasons.append(f"{len(errors)} supplier document(s) could not be processed - see document list")
    review_docs = [x["quotation"]["supplier_name"] for x in quotes
                   if x["quotation"]["extraction_status"] == "review_required"]
    if review_docs:
        reasons.append("Please verify extracted values for: " + ", ".join(review_docs))
    out = {"quotations": quotes, "doc_errors": errors, "review_reasons": reasons,
           "llm_calls": calls, "reused": reused}
    if not quotes:
        out.update(outcome="failed", error="No supplier quotation could be processed.")
    return out


def route_after_quotations(state: ProcurementState) -> str:
    return "failed" if state.get("outcome") == "failed" else "evaluate"


def node_evaluate(state: ProcurementState) -> dict:
    rid = state["request_id"]
    _say("⚖️ Applying evaluation rules (no AI)...", rid)
    db.set_status(rid, S.EVALUATING)
    evals, rec = _evaluate_and_save(rid)
    db.set_status(rid, S.READY_FOR_APPROVAL)
    return {"evaluations": [e.model_dump(mode="json") for e in evals], "recommendation": rec, "outcome": "ok"}


def node_needs_review(state: ProcurementState) -> dict:
    db.set_status(state["request_id"], S.EXTRACTION_REVIEW_REQUIRED, note="; ".join(state.get("review_reasons", [])))
    return {"outcome": "review"}


def node_failed(state: ProcurementState) -> dict:
    db.set_status(state["request_id"], S.FAILED, note=state.get("error", "")[:200])
    return {"outcome": "failed"}


def _evaluate_and_save(rid: str):
    rfq = db.get_rfq(rid)
    quotes = [x["quotation"] for x in db.list_quotations(rid)]
    evals = evaluate_all(rfq, quotes, today=date.today())
    rec = recommend(evals)
    # A comparison that silently leaves suppliers out is dangerous: say so loudly.
    read_ids = {x["document_id"] for x in db.list_quotations(rid)}
    missing = [d["filename"] for d in db.list_documents(rid)
               if d["doc_role"] == "QUOTATION" and d["id"] not in read_ids]
    rec["unprocessed_documents"] = missing
    if missing:
        rec["explanation"] = (f"INCOMPLETE - {len(missing)} quotation(s) could not be read and are NOT included: "
                              f"{', '.join(missing)}. " + rec["explanation"])
    db.save_evaluations(rid, evals, rec)
    return evals, rec


def build_graph():
    g = StateGraph(ProcurementState)
    g.add_node("extract_rfq", node_extract_rfq)
    g.add_node("extract_quotations", node_extract_quotations)
    g.add_node("evaluate", node_evaluate)
    g.add_node("needs_review", node_needs_review)
    g.add_node("failed", node_failed)
    g.add_edge(START, "extract_rfq")
    g.add_conditional_edges("extract_rfq", route_after_rfq,
                            {"quotes": "extract_quotations", "review": "needs_review", "failed": "failed"})
    g.add_conditional_edges("extract_quotations", route_after_quotations,
                            {"evaluate": "evaluate", "failed": "failed"})
    for n in ("evaluate", "needs_review", "failed"):
        g.add_edge(n, END)
    return g.compile()


GRAPH = build_graph()


# ---------- public entry points (used by the UI and scripts) ----------
def _metrics(state: dict, seconds: float) -> dict:
    calls = state.get("llm_calls", [])
    return {
        "total_seconds": round(seconds, 2),
        "ai_calls": len(calls),
        "ai_calls_failed": sum(c.get("status") == "failed" for c in calls),
        "rate_limit_waits": sum(c.get("rate_limit_waits", 0) for c in calls),
        "models_used": sorted({c["model"] for c in calls if c.get("model")}),
        "ai_attempts": sum(c["attempts"] for c in calls),
        "ai_repair_retries": sum(c["attempts"] - 1 for c in calls),
        "invalid_fields": sorted({f for c in calls for f in c.get("invalid_fields", [])}),
        "input_tokens": sum(c["input_tokens"] for c in calls),
        "output_tokens": sum(c["output_tokens"] for c in calls),
        "vision_calls": sum(bool(c["used_vision"]) for c in calls),
        "stages_reused": state.get("reused", 0),
        "documents_failed": len(state.get("doc_errors", [])),
        "review_reasons": len(state.get("review_reasons", [])),
    }


def run_processing(request_id: str, force: bool = False, actor: str = "user") -> dict:
    with _lock:
        _check_startable(request_id)
        _active.add(request_id)
    try:
        return _run_processing(request_id, force, actor)
    finally:
        _active.discard(request_id)


def _run_processing(request_id: str, force: bool, actor: str) -> dict:
    if db.get_status(request_id) in PROCESSING:  # previous run was interrupted: recover, then resume
        db.set_status(request_id, S.FAILED, actor, "previous run was interrupted - resuming")
    db.set_status(request_id, S.EXTRACTING, actor, "force re-extraction" if force else "")
    run_id, t0 = db.start_run(request_id), time.time()
    try:
        final = GRAPH.invoke({"request_id": request_id, "force": force, "llm_calls": [],
                              "review_reasons": [], "doc_errors": [], "reused": 0})
    except Exception as e:
        log.exception(f"request={request_id} workflow crashed")
        try:
            db.set_status(request_id, S.FAILED, note=f"Unexpected error: {type(e).__name__}")
        except db.WorkflowStateError:
            pass
        db.finish_run(run_id, "crashed", {"error": type(e).__name__, "total_seconds": round(time.time() - t0, 2)})
        raise
    metrics = _metrics(final, time.time() - t0)
    db.finish_run(run_id, final.get("outcome", "unknown"), metrics)
    db.audit(request_id, "PROCESSING_FINISHED",
             f"outcome={final.get('outcome')} seconds={metrics['total_seconds']} ai_calls={metrics['ai_calls']} "
             f"failed_docs={metrics['documents_failed']}", actor)
    log.info(f"request={request_id} outcome={final.get('outcome')} metrics={metrics}")
    return {"outcome": final.get("outcome"), "error": final.get("error"),
            "review_reasons": final.get("review_reasons", []), "doc_errors": final.get("doc_errors", []),
            "recommendation": final.get("recommendation"), "metrics": metrics}


def reevaluate(request_id: str, actor: str = "user") -> dict:
    """Re-run the deterministic evaluation after human corrections. No AI call."""
    status = db.get_status(request_id)
    if status not in REEVALUABLE:
        raise db.WorkflowStateError(f"Re-evaluation is not possible while the request is {status.value}.")
    rfq = db.get_rfq(request_id)
    if rfq is None or rfq.missing_core_fields():
        raise db.WorkflowStateError("Complete the RFQ (product, quantity, unit) first.")
    if not db.list_quotations(request_id):
        raise db.WorkflowStateError("No supplier quotations extracted yet - run processing first.")
    db.set_status(request_id, S.EVALUATING, actor, "re-evaluation after review")
    evals, rec = _evaluate_and_save(request_id)
    db.set_status(request_id, S.READY_FOR_APPROVAL, actor)
    return {"evaluations": evals, "recommendation": rec}
