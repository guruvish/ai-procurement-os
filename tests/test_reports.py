"""Reports (PDF + Excel) and the Google Sheets export. AI and Google are faked: offline, free, deterministic."""
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app import config, db
from app.agents import extractors, workflow
from app.services import report_service as R
from tests.test_workflow import fake_quote, fake_rfq, make_request


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "rep.db")
    monkeypatch.setattr(db, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "REPORT_DIR", tmp_path / "reports")
    (tmp_path / "reports").mkdir()
    monkeypatch.setattr(extractors, "extract_rfq", fake_rfq)
    monkeypatch.setattr(extractors, "extract_quotation", fake_quote)
    db.init_db()


def _evaluated():
    rid = make_request(quotes=("good.csv", "cheap_fail.csv", "noprice.csv"))
    workflow.run_processing(rid)
    return rid


def test_draft_excel_has_all_tables_and_draft_warning():
    rid = _evaluated()
    wb = load_workbook(BytesIO(R.excel_report(rid)))
    assert wb.sheetnames == ["Summary", "Decision analysis", "Comparison", "Scorecard", "Compliance matrix",
                             "Checks", "Findings", "Evidence", "Approvals", "Audit trail"]
    assert "DRAFT" in wb["Summary"]["A1"].value
    comparison = [[c.value for c in r] for r in wb["Comparison"].iter_rows()]
    assert comparison[1][1] == "good" and comparison[1][2] == "Compliant"      # ranked first
    assert comparison[-1][1] == "cheap_fail" and comparison[-1][2] == "Not compliant"


def test_pdf_is_valid_and_marked_draft_before_approval():
    rid = _evaluated()
    pdf = R.pdf_report(rid)
    assert pdf.startswith(b"%PDF") and len(pdf) > 3000
    fitz = pytest.importorskip("pymupdf")
    text = "".join(p.get_text() for p in fitz.open(stream=pdf, filetype="pdf"))
    assert "DRAFT - NOT APPROVED" in text and "Compliance matrix" in text


def test_final_reports_require_approval_then_are_saved_and_audited():
    rid = _evaluated()
    with pytest.raises(db.WorkflowStateError, match="after approval"):
        R.save_final_reports(rid, "priya")
    db.record_decision(rid, "APPROVED", "priya", "ok", "good")
    paths = R.save_final_reports(rid, "priya")
    assert {p.suffix for p in paths} == {".pdf", ".xlsx"} and all(p.exists() for p in paths)
    assert db.get_status(rid) == db.S.REPORT_GENERATED
    assert any(a["event_type"] == "REPORT_GENERATED" for a in db.list_audit(rid))
    wb = load_workbook(BytesIO(R.excel_report(rid)))
    summary = {r[0].value: r[1].value for r in wb["Summary"].iter_rows(min_row=2)}
    assert summary["Selected supplier (human)"] == "good" and summary["Report status"].startswith("APPROVED by priya")


def test_google_sheets_export_writes_one_tab_per_table(monkeypatch):
    gspread = pytest.importorskip("gspread")
    from app.integrations import google_sheets as G
    rid = _evaluated()

    class FakeWS:
        def __init__(self, title):
            self.title, self.values, self.cleared = title, None, False

        def clear(self):
            self.cleared = True

        def update(self, range_name, values):
            self.values = values

        def format(self, *a, **k):
            pass

        def freeze(self, **k):
            pass

    class FakeSheet:
        url = "https://docs.google.com/spreadsheets/d/fake"

        def __init__(self):
            self.tabs = {}

        def worksheet(self, title):
            if title not in self.tabs:
                raise gspread.exceptions.WorksheetNotFound(title)
            return self.tabs[title]

        def add_worksheet(self, title, rows, cols):
            self.tabs[title] = FakeWS(title)
            return self.tabs[title]

    sheet = FakeSheet()
    monkeypatch.setattr(G, "is_configured", lambda: True)
    monkeypatch.setattr(G, "_client", lambda: type("C", (), {"open_by_key": lambda self, key: sheet})())
    assert G.export(rid, "priya") == FakeSheet.url
    rfq_no = db.get_request(rid)["rfq_number"]
    assert set(sheet.tabs) == {f"{rfq_no} - {t}"[:100] for t in G.TABS}
    assert sheet.tabs[f"{rfq_no} - Comparison"[:100]].values[1][1] == "good"
    G.export(rid, "priya")                                            # re-export overwrites, no duplicates
    assert all(ws.cleared for ws in sheet.tabs.values())
    assert any(a["event_type"] == "EXPORTED_TO_GOOGLE_SHEETS" for a in db.list_audit(rid))


def test_sheets_not_configured_gives_clear_message(monkeypatch):
    from app.integrations import google_sheets as G
    monkeypatch.setattr(config, "GOOGLE_SHEET_ID", "")
    with pytest.raises(ValueError, match="not set up"):
        G.export(_evaluated(), "priya")
