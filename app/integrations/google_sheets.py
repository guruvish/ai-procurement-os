"""Google Sheets export (integration): writes the evaluation tables into a shared spreadsheet.
Setup: docs/google_sheets_setup.md. Uses a Google Cloud service account; the spreadsheet must be shared
with the service account's e-mail (Editor). If not configured, the app offers Excel download instead."""
from pathlib import Path

from app import config, db
from app.log import get_logger
from app.services.report_service import collect, tables

log = get_logger("sheets")
TABS = ["Summary", "Decision analysis", "Comparison", "Scorecard", "Compliance matrix", "Findings", "Evidence", "Approvals"]


def is_configured() -> bool:
    return bool(config.GOOGLE_SHEET_ID) and Path(config.GOOGLE_SERVICE_ACCOUNT_FILE).is_file()


def _client():
    import gspread  # imported lazily: the app works without Google set up
    return gspread.service_account(filename=str(config.GOOGLE_SERVICE_ACCOUNT_FILE))


def export(rid: str, actor: str) -> str:
    """Writes one tab per table, named '<RFQ> - <table>' (re-export overwrites). Returns the sheet URL."""
    if not is_configured():
        raise ValueError("Google Sheets is not set up. See docs/google_sheets_setup.md - or download the Excel report.")
    import gspread
    d = collect(rid)
    data = tables(d)
    try:
        sh = _client().open_by_key(config.GOOGLE_SHEET_ID)
    except gspread.exceptions.SpreadsheetNotFound:
        raise ValueError("Spreadsheet not found. Check GOOGLE_SHEET_ID and share the sheet with the service account e-mail.")
    except gspread.exceptions.APIError as e:
        log.error(f"sheets_open_failed status={getattr(e.response, 'status_code', '?')}")
        raise ValueError("Google refused access. Share the spreadsheet with the service account e-mail as Editor.")
    rfq = d["req"]["rfq_number"]
    for name in TABS:
        rows = [["" if c is None else (c if isinstance(c, (int, float)) else str(c)) for c in r] for r in data[name]]
        title = f"{rfq} - {name}"[:100]
        try:
            ws = sh.worksheet(title)
            ws.clear()
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title=title, rows=max(len(rows) + 5, 20), cols=max(len(rows[0]) + 2, 6))
        ws.update(range_name="A1", values=rows)
        try:
            ws.format("1:1", {"textFormat": {"bold": True}, "backgroundColor": {"red": .31, "green": .27, "blue": .9}})
            ws.freeze(rows=1)
        except Exception:  # formatting is cosmetic - never fail the export for it
            pass
    db.audit(rid, "EXPORTED_TO_GOOGLE_SHEETS", f"{len(TABS)} tabs -> spreadsheet {config.GOOGLE_SHEET_ID[:8]}...", actor)
    log.info(f"request={rid} exported to google sheets tabs={len(TABS)}")
    return sh.url
