"""The evaluation harness, run offline with fake extractors.
1) A PERFECT extractor (returns the ground truth) must score 100% everywhere - this also proves the
   hand-written ground truth agrees with the evaluation rules (no inconsistent expected verdicts).
2) An extractor with one injected mistake must be caught and listed as a mismatch."""
import pytest

from app import db
from app.agents import extractors
from app.agents.llm import CallMeta
from evaluation import run_evaluation as E
from evaluation.cases import build_cases

CASES = build_cases()
RFQS = {f"RFQ_{c['id']}.csv": c["rfq_truth"] for c in CASES}
QUOTES = {E.doc_name(q, "text"): q["truth"] for c in CASES for q in c["quotes"] if q.get("truth")}


def perfect_rfq(parsed, rfq_id=""):
    return RFQS[parsed.filename].model_copy(deep=True), CallMeta("rfq_analyst", attempts=1)


def perfect_quote(parsed, rfq):
    q = QUOTES[parsed.filename].model_copy(deep=True)
    q.source_document = parsed.filename
    q.extraction_status = "review_required" if q.conflicts else "extracted"
    return q, CallMeta("supplier_analyst", attempts=1)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "eval.db")
    monkeypatch.setattr(db, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(extractors, "extract_rfq", perfect_rfq)
    monkeypatch.setattr(extractors, "extract_quotation", perfect_quote)
    db.init_db()


def test_perfect_extractor_scores_100_and_ground_truth_is_consistent(tmp_path):
    results = [E.run_case(c, mode="text", out_dir=tmp_path) for c in CASES]
    notes = [n for r in results for n in r["notes"]]
    assert notes == []                                     # no ground-truth inconsistencies
    s = E.summarise(results)
    assert s["cases"] == 10
    assert s["extraction_accuracy"] == 100.0 and s["verdict_accuracy"] == 100.0
    assert s["check_agreement"] == 100.0 and s["recommendation_accuracy"] == 100.0
    assert s["missing_recall"] == 100.0 and s["missing_precision"] == 100.0
    assert s["bad_files_rejected"] == "2/2"
    md = E.report_md(s, results, {})
    assert "None - every field, verdict and check matched" in md


def test_injected_extraction_error_is_caught_and_reported(tmp_path, monkeypatch):
    def flawed_quote(parsed, rfq):
        q, meta = perfect_quote(parsed, rfq)
        if q.supplier_name.startswith("Delta"):
            q.unit_price = 200.0                              # AI misread 180 as 200
        return q, meta
    monkeypatch.setattr(extractors, "extract_quotation", flawed_quote)
    tc01 = next(c for c in CASES if c["id"] == "TC-01")
    r = E.run_case(tc01, mode="text", out_dir=tmp_path)
    bad = [f for f in r["fields"] if not f["ok"]]
    assert [(f["scope"], f["field"], f["expected"], f["got"]) for f in bad] == \
        [("Delta Life Sciences", "unit_price", "180.0", "200.0")]
    assert r["recommendation"]["ok"] is False             # wrong price changed the winner -> detected
    assert "unit_price" in E.report_md(E.summarise([r]), [r], {})


def test_f11_check_agreement_ignores_certificate_spelling(tmp_path, monkeypatch):
    """FAILURE F11 (measurement bug): real run showed 85.7% check agreement with 100% correct fields, because
    the AI wrote 'GMP Certificate' where the ground truth says 'GMP certificate'. Same certificate."""
    def rfq_spelled_differently(parsed, rfq_id=""):
        r, meta = perfect_rfq(parsed, rfq_id)
        r.required_certificates = ["Certificate of Analysis (CoA)", "GMP Certificate"]
        return r, meta
    monkeypatch.setattr(extractors, "extract_rfq", rfq_spelled_differently)
    tc01 = next(c for c in CASES if c["id"] == "TC-01")
    s = E.summarise([E.run_case(tc01, mode="text", out_dir=tmp_path)])
    assert s["check_agreement"] == 100.0 and s["extraction_accuracy"] == 100.0
