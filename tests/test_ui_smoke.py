"""Headless UI smoke tests (Streamlit AppTest): every screen must render without an exception,
including the evaluation workspace with real evaluation data. AI is faked - no API calls."""
from pathlib import Path

import pytest

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

from app import db  # noqa: E402
from app.agents import extractors, workflow  # noqa: E402
from tests.test_workflow import fake_quote, fake_rfq, make_request  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "ui.db")
    monkeypatch.setattr(db, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(extractors, "extract_rfq", fake_rfq)
    monkeypatch.setattr(extractors, "extract_quotation", fake_quote)
    db.init_db()


def _run(page: str, rid: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["user_name"] = "ui-tester"
    at.session_state["nav"] = page
    if rid:
        at.session_state["rid"] = rid
    at.run()
    return at


PAGES = ["🏠 Dashboard", "➕ New evaluation", "📂 Open evaluation", "💡 How it works"]


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders_on_empty_database(page):
    assert not _run(page).exception


def test_workspace_renders_with_real_evaluation_data():
    rid = make_request(quotes=("good.csv", "cheap_fail.csv", "noprice.csv", "broken.csv"))
    workflow.run_processing(rid, actor="ui-tester")
    at = _run(PAGES[2], rid)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Ready for your decision" in text


def test_dashboard_lists_evaluations():
    rid = make_request()
    workflow.run_processing(rid)
    at = _run(PAGES[0])
    assert not at.exception
    assert at.metric[0].value == "1"


def test_workspace_after_approval_renders_locked_state():
    rid = make_request()
    workflow.run_processing(rid)
    db.record_decision(rid, "APPROVED", "ui-tester", "ok", "good")
    at = _run(PAGES[2], rid)
    assert not at.exception
