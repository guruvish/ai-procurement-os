"""Workflow + database tests. The AI extractors are replaced by fakes, so these run
offline, cost nothing and are deterministic. They test routing, failure isolation,
re-use of completed stages, human corrections and approval rules."""
from datetime import date, timedelta

import pytest

from app import db
from app.agents import extractors, workflow
from app.agents.llm import CallMeta, ExtractionError, QuotaExhaustedError
from app.schemas import OfferedSpec, RFQRequirements, SupplierQuotation, TechRequirement, WorkflowStatus

S = WorkflowStatus
CALLS = {"rfq": 0, "quote": 0}


def fake_rfq(parsed, rfq_id=""):
    CALLS["rfq"] += 1
    if "incomplete" in parsed.filename:
        return RFQRequirements(rfq_id=rfq_id, product_name="Paracetamol API"), CallMeta("rfq_analyst", attempts=1)
    return RFQRequirements(
        rfq_id=rfq_id, product_name="Paracetamol API", required_quantity=10000, unit="kg", currency="INR",
        technical_requirements=[TechRequirement(name="purity", operator=">=", value=99.5, unit="%")],
        required_certificates=["Certificate of Analysis"], max_delivery_days=30,
        payment_terms="30 days after delivery"), CallMeta("rfq_analyst", attempts=1)


def fake_quote(parsed, rfq):
    CALLS["quote"] += 1
    name = parsed.filename.split(".")[0]
    if name.startswith("broken"):
        raise ExtractionError("supplier_analyst: AI output failed validation after 2 attempts")
    if name.startswith("quota"):
        raise QuotaExhaustedError("The daily free AI quota is used up")
    base = dict(supplier_name=name, unit_price=185, price_per="kg", currency="INR", tax_status="exclusive",
                delivery_days=21, valid_until=date.today() + timedelta(days=20), payment_terms="30 days",
                certificates=["CoA"], specifications=[OfferedSpec(name="purity", value=99.8, unit="%")])
    if name.startswith("cheap_fail"):
        base.update(unit_price=150, specifications=[OfferedSpec(name="purity", value=99.0, unit="%")])
    if name.startswith("noprice"):
        base.update(unit_price=None)
    return SupplierQuotation(**base), CallMeta("supplier_analyst", attempts=2 if "retry" in name else 1)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(extractors, "extract_rfq", fake_rfq)
    monkeypatch.setattr(extractors, "extract_quotation", fake_quote)
    CALLS.update(rfq=0, quote=0)
    db.init_db()


def _csv(text: str) -> bytes:
    return f"field,value\nnote,{text}\n".encode()


def make_request(rfq_file="rfq.csv", quotes=("good.csv",)):
    rid = db.create_request("RFQ-TEST-" + rfq_file + "-" + "-".join(quotes))
    import hashlib
    for fname, role in [(rfq_file, "RFQ")] + [(q, "QUOTATION") for q in quotes]:
        data = _csv(fname) if not fname.endswith(".pdf") else b"this is not a pdf"
        db.save_document(rid, fname, data, hashlib.sha256(data).hexdigest(), fname.rsplit(".", 1)[1], role)
    return rid


def test_happy_path_reaches_ready_for_approval_with_recommendation():
    rid = make_request(quotes=("good.csv", "cheap_fail.csv"))
    result = workflow.run_processing(rid)
    assert result["outcome"] == "ok"
    assert db.get_status(rid) == S.READY_FOR_APPROVAL
    assert result["recommendation"]["recommended_supplier"] == "good"
    assert result["metrics"]["ai_calls"] == 3
    assert len(db.get_evaluations(rid)) == 2


def test_one_bad_supplier_does_not_stop_the_batch():
    rid = make_request(quotes=("good.csv", "broken.csv", "fake.pdf"))
    result = workflow.run_processing(rid)
    assert result["outcome"] == "ok"
    assert {e["filename"] for e in result["doc_errors"]} == {"broken.csv", "fake.pdf"}
    failed = [d for d in db.list_documents(rid) if d["extraction_status"] == "failed"]
    assert len(failed) == 2 and all(d["error"] for d in failed)
    assert "not a real PDF" in next(d["error"] for d in failed if d["filename"] == "fake.pdf")


def test_all_suppliers_failing_marks_request_failed():
    rid = make_request(quotes=("broken.csv",))
    assert workflow.run_processing(rid)["outcome"] == "failed"
    assert db.get_status(rid) == S.FAILED


def test_incomplete_rfq_routes_to_human_review():
    rid = make_request(rfq_file="incomplete.csv")
    result = workflow.run_processing(rid)
    assert result["outcome"] == "review"
    assert db.get_status(rid) == S.EXTRACTION_REVIEW_REQUIRED
    assert CALLS["quote"] == 0   # stops before spending AI calls on suppliers


def test_rerun_reuses_completed_stages_without_new_ai_calls():
    rid = make_request(quotes=("good.csv",))
    workflow.run_processing(rid)
    before = dict(CALLS)
    result = workflow.run_processing(rid)
    assert CALLS == before
    assert result["metrics"]["stages_reused"] == 2
    workflow.run_processing(rid, force=True)
    assert CALLS["quote"] == before["quote"] + 1


def test_human_correction_then_reevaluate_changes_verdict_and_is_audited():
    rid = make_request(quotes=("noprice.csv",))
    workflow.run_processing(rid)
    assert db.get_evaluations(rid)[0].overall_status == "NEEDS_CLARIFICATION"
    doc_id = db.list_quotations(rid)[0]["document_id"]
    db.human_edit_quotation(rid, doc_id, {"unit_price": 180.0}, actor="priya")
    result = workflow.reevaluate(rid, actor="priya")
    assert result["evaluations"][0].overall_status == "COMPLIANT"
    assert any(a["event_type"] == "HUMAN_CORRECTION" and a["actor"] == "priya" for a in db.list_audit(rid))
    assert db.list_quotations(rid)[0]["edited_by_human"] is True


def test_approval_rules_are_enforced():
    rid = make_request()
    with pytest.raises(db.WorkflowStateError):
        db.record_decision(rid, "APPROVED", "priya")          # not processed yet
    workflow.run_processing(rid)
    with pytest.raises(db.WorkflowStateError):
        db.record_decision(rid, "REJECTED", "priya", "")      # reject needs a reason
    with pytest.raises(db.WorkflowStateError):
        db.record_decision(rid, "APPROVED", "  ")             # reviewer required
    db.record_decision(rid, "APPROVED", "priya", "OK", selected_supplier="good")
    assert db.get_status(rid) == S.APPROVED
    assert db.list_approvals(rid)[0]["reviewer"] == "priya"
    with pytest.raises(db.WorkflowStateError):
        workflow.run_processing(rid)                          # approved = locked


def test_duplicate_upload_is_detected():
    rid = make_request()
    import hashlib
    data = _csv("good.csv")
    _, dup = db.save_document(rid, "good_copy.csv", data, hashlib.sha256(data).hexdigest(), "csv", "QUOTATION")
    assert dup is True
    assert len([d for d in db.list_documents(rid) if d["doc_role"] == "QUOTATION"]) == 1


def test_duplicate_rfq_number_rejected():
    db.create_request("RFQ-DUP")
    with pytest.raises(ValueError, match="already exists"):
        db.create_request("RFQ-DUP")


def test_daily_quota_stops_calls_and_marks_comparison_incomplete():
    rid = make_request(quotes=("good.csv", "quota.csv", "later.csv"))
    result = workflow.run_processing(rid)
    assert CALLS["quote"] == 2                                   # 'later' was NOT sent to the AI
    docs = {d["filename"]: d for d in db.list_documents(rid)}
    assert docs["later.csv"]["extraction_status"] == "pending"
    rec = result["recommendation"]
    assert rec["explanation"].startswith("INCOMPLETE - 2 quotation(s)")
    assert set(rec["unprocessed_documents"]) == {"quota.csv", "later.csv"}


def test_rerun_after_quota_reset_only_reads_missing_documents(monkeypatch):
    rid = make_request(quotes=("good.csv", "quota.csv"))
    workflow.run_processing(rid)
    db.delete_document(next(d["id"] for d in db.list_documents(rid) if d["filename"] == "quota.csv"))
    before = CALLS["quote"]
    result = workflow.run_processing(rid)
    assert CALLS["quote"] == before                              # good.csv reused, nothing re-read
    assert not result["recommendation"]["unprocessed_documents"]


def test_progress_messages_are_reported():
    msgs = []
    workflow.set_progress(msgs.append)
    try:
        workflow.run_processing(make_request(quotes=("good.csv",)))
    finally:
        workflow.set_progress(None)
    assert any("Reading the RFQ" in m for m in msgs) and any("good" in m for m in msgs)


# ---------- F10: processing interrupted by a page rerun ----------
def test_background_job_finishes_and_keeps_its_progress_log():
    rid = make_request(quotes=("good.csv", "cheap_fail.csv"))
    workflow.start_processing(rid, actor="priya")
    workflow.job(rid)["thread"].join(timeout=10)
    done = workflow.pop_finished_job(rid)
    assert done["result"]["outcome"] == "ok" and done["error"] is None
    assert any("Reading" in m for m in done["messages"])
    assert db.get_status(rid) == S.READY_FOR_APPROVAL


def test_interrupted_run_is_detected_and_can_be_resumed():
    """FAILURE F10: user typed in the sidebar during processing -> Streamlit rerun killed the run
    after extraction; status stayed EXTRACTING and the run button was disabled."""
    rid = make_request(quotes=("good.csv",))
    db.set_status(rid, S.EXTRACTING)          # what an interrupted run leaves behind
    assert workflow.is_stale(rid)
    result = workflow.run_processing(rid, actor="priya")
    assert result["outcome"] == "ok" and db.get_status(rid) == S.READY_FOR_APPROVAL
    assert any("interrupted" in a["description"] for a in db.list_audit(rid))


def test_same_request_cannot_be_processed_twice_at_once():
    rid = make_request()
    workflow._active.add(rid)
    try:
        with pytest.raises(db.WorkflowStateError, match="already being processed"):
            workflow.start_processing(rid)
    finally:
        workflow._active.discard(rid)
