"""SQLite persistence: requests, documents, extracted data, evaluations, approvals, audit trail.
Extracted/evaluated objects are stored as validated JSON (Pydantic) - the schema is the contract."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from app import config
from app.schemas import RFQRequirements, SupplierEvaluation, SupplierQuotation, WorkflowStatus

DB_PATH: Path = config.DB_PATH
UPLOAD_DIR: Path = config.UPLOAD_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS procurement_requests (
    id TEXT PRIMARY KEY,
    rfq_number TEXT UNIQUE NOT NULL,
    title TEXT, department TEXT, buyer TEXT,
    status TEXT NOT NULL,
    rfq_json TEXT,
    recommendation_json TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES procurement_requests(id) ON DELETE CASCADE,
    filename TEXT NOT NULL, stored_path TEXT NOT NULL, file_type TEXT, sha256 TEXT NOT NULL,
    doc_role TEXT NOT NULL CHECK (doc_role IN ('RFQ', 'QUOTATION')),
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    error TEXT, warnings_json TEXT,
    uploaded_at TEXT NOT NULL,
    UNIQUE (request_id, sha256)
);
CREATE TABLE IF NOT EXISTS quotations (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES procurement_requests(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    supplier_name TEXT NOT NULL,
    data_json TEXT NOT NULL,
    edited_by_human INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE (document_id)
);
CREATE TABLE IF NOT EXISTS evaluations (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES procurement_requests(id) ON DELETE CASCADE,
    supplier_name TEXT NOT NULL,
    overall_status TEXT, total_cost REAL, risk_level TEXT,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES procurement_requests(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL, decision TEXT NOT NULL CHECK (decision IN ('APPROVED', 'REJECTED')),
    selected_supplier TEXT, comments TEXT,
    reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES procurement_requests(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT, metrics_json TEXT
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    event_type TEXT NOT NULL, description TEXT, actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_request ON documents(request_id);
CREATE INDEX IF NOT EXISTS idx_quotes_request ON quotations(request_id);
CREATE INDEX IF NOT EXISTS idx_evals_request ON evaluations(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_logs(request_id);
"""

# Allowed workflow transitions (anything else is rejected with a clear message)
S = WorkflowStatus
ALLOWED = {
    S.CREATED: {S.DOCUMENTS_UPLOADED},
    S.DOCUMENTS_UPLOADED: {S.DOCUMENTS_UPLOADED, S.EXTRACTING},
    S.EXTRACTING: {S.EVALUATING, S.EXTRACTION_REVIEW_REQUIRED, S.FAILED},
    S.EXTRACTION_REVIEW_REQUIRED: {S.EVALUATING, S.EXTRACTING, S.DOCUMENTS_UPLOADED},
    S.EVALUATING: {S.READY_FOR_APPROVAL, S.FAILED},
    S.READY_FOR_APPROVAL: {S.APPROVED, S.REJECTED, S.EVALUATING, S.EXTRACTING, S.DOCUMENTS_UPLOADED},
    S.REJECTED: {S.EVALUATING, S.EXTRACTING, S.DOCUMENTS_UPLOADED},
    S.APPROVED: {S.REPORT_GENERATED},
    S.REPORT_GENERATED: {S.REPORT_GENERATED},
    S.FAILED: {S.EXTRACTING, S.DOCUMENTS_UPLOADED},
}


class WorkflowStateError(Exception):
    """Action not allowed in the current workflow state; message is user-facing."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


def audit(request_id: Optional[str], event_type: str, description: str, actor: str = "system") -> None:
    with connect() as c:
        c.execute("INSERT INTO audit_logs (request_id, event_type, description, actor, created_at) "
                  "VALUES (?, ?, ?, ?, ?)", (request_id, event_type, description, actor, _now()))


# ---------- requests ----------
def create_request(rfq_number: str, title: str = "", department: str = "", buyer: str = "",
                   actor: str = "user") -> str:
    rfq_number = rfq_number.strip()
    if not rfq_number:
        raise ValueError("RFQ number is required.")
    rid = uuid.uuid4().hex[:12]
    try:
        with connect() as c:
            c.execute("INSERT INTO procurement_requests (id, rfq_number, title, department, buyer, status, "
                      "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (rid, rfq_number, title, department, buyer, S.CREATED.value, _now(), _now()))
    except sqlite3.IntegrityError:
        raise ValueError(f"An evaluation for RFQ number '{rfq_number}' already exists.")
    audit(rid, "REQUEST_CREATED", f"RFQ {rfq_number} created", actor)
    return rid


def get_request(request_id: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT * FROM procurement_requests WHERE id = ?", (request_id,)).fetchone()
    return dict(row) if row else None


def list_requests() -> list:
    with connect() as c:
        rows = c.execute("SELECT * FROM procurement_requests ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_status(request_id: str) -> WorkflowStatus:
    req = get_request(request_id)
    if not req:
        raise WorkflowStateError("Procurement request not found.")
    return WorkflowStatus(req["status"])


def set_status(request_id: str, new: WorkflowStatus, actor: str = "system", note: str = "") -> None:
    old = get_status(request_id)
    if new not in ALLOWED[old]:
        raise WorkflowStateError(f"Cannot move from {old.value} to {new.value}.")
    with connect() as c:
        c.execute("UPDATE procurement_requests SET status = ?, updated_at = ? WHERE id = ?",
                  (new.value, _now(), request_id))
    audit(request_id, "STATUS_CHANGED", f"{old.value} -> {new.value}" + (f" ({note})" if note else ""), actor)


def delete_request(request_id: str, actor: str = "user") -> None:
    for d in list_documents(request_id):
        Path(d["stored_path"]).unlink(missing_ok=True)
    with connect() as c:
        c.execute("DELETE FROM procurement_requests WHERE id = ?", (request_id,))
    audit(request_id, "REQUEST_DELETED", "Request and its documents deleted", actor)


# ---------- documents ----------
def save_document(request_id: str, filename: str, data: bytes, sha256: str, file_type: str,
                  doc_role: str, actor: str = "user") -> tuple:
    """Returns (document_id, is_duplicate). Files get random internal names."""
    with connect() as c:
        dup = c.execute("SELECT id, filename FROM documents WHERE request_id = ? AND sha256 = ?",
                        (request_id, sha256)).fetchone()
    if dup:
        audit(request_id, "DUPLICATE_SKIPPED", f"{filename} is identical to {dup['filename']}", actor)
        return dup["id"], True
    if doc_role == "RFQ":
        for old in [d for d in list_documents(request_id) if d["doc_role"] == "RFQ"]:
            delete_document(old["id"], actor, reason="replaced by new RFQ upload")
    did = uuid.uuid4().hex[:12]
    folder = UPLOAD_DIR / request_id
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{did}.{file_type}"
    stored.write_bytes(data)
    with connect() as c:
        c.execute("INSERT INTO documents (id, request_id, filename, stored_path, file_type, sha256, doc_role, "
                  "uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (did, request_id, filename, str(stored), file_type, sha256, doc_role, _now()))
    audit(request_id, "DOCUMENT_UPLOADED", f"{doc_role}: {filename}", actor)
    status = get_status(request_id)
    if status != S.DOCUMENTS_UPLOADED and S.DOCUMENTS_UPLOADED in ALLOWED[status]:
        set_status(request_id, S.DOCUMENTS_UPLOADED, actor, "new document")
    return did, False


def list_documents(request_id: str) -> list:
    with connect() as c:
        rows = c.execute("SELECT * FROM documents WHERE request_id = ? ORDER BY doc_role DESC, uploaded_at, rowid",
                         (request_id,)).fetchall()
    return [dict(r) for r in rows]


def update_document(document_id: str, extraction_status: str, error: Optional[str] = None,
                    warnings: Optional[list] = None) -> None:
    with connect() as c:
        c.execute("UPDATE documents SET extraction_status = ?, error = ?, warnings_json = ? WHERE id = ?",
                  (extraction_status, error, json.dumps(warnings or []), document_id))


def delete_document(document_id: str, actor: str = "user", reason: str = "") -> None:
    with connect() as c:
        row = c.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            return
        c.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    Path(row["stored_path"]).unlink(missing_ok=True)
    audit(row["request_id"], "DOCUMENT_DELETED", f"{row['filename']}" + (f" ({reason})" if reason else ""), actor)


# ---------- extracted data ----------
def save_rfq(request_id: str, rfq: RFQRequirements) -> None:
    with connect() as c:
        c.execute("UPDATE procurement_requests SET rfq_json = ?, updated_at = ? WHERE id = ?",
                  (rfq.model_dump_json(), _now(), request_id))


def get_rfq(request_id: str) -> Optional[RFQRequirements]:
    req = get_request(request_id)
    return RFQRequirements.model_validate_json(req["rfq_json"]) if req and req["rfq_json"] else None


def human_edit_rfq(request_id: str, changes: dict, actor: str) -> RFQRequirements:
    current = get_rfq(request_id)
    if current is None:
        raise ValueError("RFQ has not been extracted yet.")
    data = current.model_dump()
    diffs = [f"{k}: {data.get(k)!r} -> {v!r}" for k, v in changes.items() if data.get(k) != v]
    if not diffs:
        return current
    data.update(changes)
    updated = RFQRequirements.model_validate(data)
    save_rfq(request_id, updated)
    audit(request_id, "HUMAN_CORRECTION", "RFQ: " + "; ".join(diffs), actor)
    return updated


def save_quotation(request_id: str, document_id: str, q: SupplierQuotation, edited_by_human: bool = False) -> None:
    with connect() as c:
        c.execute("INSERT INTO quotations (id, request_id, document_id, supplier_name, data_json, edited_by_human, "
                  "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(document_id) DO UPDATE SET "
                  "supplier_name = excluded.supplier_name, data_json = excluded.data_json, "
                  "edited_by_human = excluded.edited_by_human, updated_at = excluded.updated_at",
                  (uuid.uuid4().hex[:12], request_id, document_id, q.supplier_name, q.model_dump_json(),
                   int(edited_by_human), _now()))


def list_quotations(request_id: str) -> list:
    """Returns list of dicts: {document_id, edited_by_human, quotation: SupplierQuotation}."""
    with connect() as c:
        rows = c.execute("SELECT q.* FROM quotations q JOIN documents d ON d.id = q.document_id "
                         "WHERE q.request_id = ? ORDER BY d.uploaded_at", (request_id,)).fetchall()
    return [{"document_id": r["document_id"], "edited_by_human": bool(r["edited_by_human"]),
             "quotation": SupplierQuotation.model_validate_json(r["data_json"])} for r in rows]


def get_quotation(document_id: str) -> Optional[SupplierQuotation]:
    with connect() as c:
        row = c.execute("SELECT data_json FROM quotations WHERE document_id = ?", (document_id,)).fetchone()
    return SupplierQuotation.model_validate_json(row["data_json"]) if row else None


def human_edit_quotation(request_id: str, document_id: str, changes: dict, actor: str) -> SupplierQuotation:
    """Apply reviewer corrections; validated against the schema; each change is audited."""
    current = get_quotation(document_id)
    if current is None:
        raise ValueError("Quotation not found.")
    data = current.model_dump()
    diffs = []
    for k, v in changes.items():
        if data.get(k) != v:
            diffs.append(f"{k}: {data.get(k)!r} -> {v!r}")
            data[k] = v
    if not diffs:
        return current
    data["extraction_status"] = "validated"
    data["verification_warnings"] = []      # a human has now checked the values
    updated = SupplierQuotation.model_validate(data)
    save_quotation(request_id, document_id, updated, edited_by_human=True)
    audit(request_id, "HUMAN_CORRECTION", f"{updated.supplier_name}: " + "; ".join(diffs), actor)
    return updated


# ---------- evaluations ----------
def save_evaluations(request_id: str, evals: list, recommendation: dict) -> None:
    with connect() as c:
        c.execute("DELETE FROM evaluations WHERE request_id = ?", (request_id,))
        for e in evals:
            c.execute("INSERT INTO evaluations (id, request_id, supplier_name, overall_status, total_cost, "
                      "risk_level, data_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (uuid.uuid4().hex[:12], request_id, e.supplier_name, e.overall_status, e.total_cost,
                       e.risk_level, e.model_dump_json(), _now()))
        c.execute("UPDATE procurement_requests SET recommendation_json = ?, updated_at = ? WHERE id = ?",
                  (json.dumps(recommendation), _now(), request_id))


def get_evaluations(request_id: str) -> list:
    with connect() as c:
        rows = c.execute("SELECT data_json FROM evaluations WHERE request_id = ? ORDER BY rowid",
                         (request_id,)).fetchall()
    return [SupplierEvaluation.model_validate_json(r["data_json"]) for r in rows]


def get_recommendation(request_id: str) -> Optional[dict]:
    req = get_request(request_id)
    return json.loads(req["recommendation_json"]) if req and req["recommendation_json"] else None


# ---------- approvals ----------
def record_decision(request_id: str, decision: str, reviewer: str, comments: str = "",
                    selected_supplier: Optional[str] = None) -> None:
    """Explicit human action. The AI never calls this."""
    if not reviewer.strip():
        raise WorkflowStateError("Reviewer name is required.")
    if decision not in ("APPROVED", "REJECTED"):
        raise WorkflowStateError("Decision must be APPROVED or REJECTED.")
    if decision == "REJECTED" and not comments.strip():
        raise WorkflowStateError("Please give a reason when rejecting.")
    if get_status(request_id) != S.READY_FOR_APPROVAL:
        raise WorkflowStateError("This evaluation is not ready for approval yet.")
    with connect() as c:
        c.execute("INSERT INTO approvals (id, request_id, reviewer, decision, selected_supplier, comments, "
                  "reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (uuid.uuid4().hex[:12], request_id, reviewer.strip(), decision, selected_supplier,
                   comments, _now()))
    set_status(request_id, S(decision), actor=reviewer.strip(), note=comments[:200])


def list_approvals(request_id: str) -> list:
    with connect() as c:
        rows = c.execute("SELECT * FROM approvals WHERE request_id = ? ORDER BY reviewed_at",
                         (request_id,)).fetchall()
    return [dict(r) for r in rows]


# ---------- runs & audit ----------
def start_run(request_id: str) -> str:
    run_id = uuid.uuid4().hex[:12]
    with connect() as c:
        c.execute("INSERT INTO runs (id, request_id, started_at, status) VALUES (?, ?, ?, 'RUNNING')",
                  (run_id, request_id, _now()))
    return run_id


def finish_run(run_id: str, status: str, metrics: dict) -> None:
    with connect() as c:
        c.execute("UPDATE runs SET finished_at = ?, status = ?, metrics_json = ? WHERE id = ?",
                  (_now(), status, json.dumps(metrics), run_id))


def list_runs(request_id: Optional[str] = None) -> list:
    with connect() as c:
        if request_id:
            rows = c.execute("SELECT * FROM runs WHERE request_id = ? ORDER BY started_at DESC",
                             (request_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()
    return [dict(r) for r in rows]


def list_audit(request_id: str) -> list:
    with connect() as c:
        rows = c.execute("SELECT * FROM audit_logs WHERE request_id = ? ORDER BY id", (request_id,)).fetchall()
    return [dict(r) for r in rows]
