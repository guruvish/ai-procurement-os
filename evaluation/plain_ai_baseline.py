"""The "just ask an AI" baseline: what you get by pasting the RFQ and the quotes into a chat model.

Same 10 cases and the same AI models as the real system, but none of the system around them: one prompt per
RFQ, no schema per document, no evidence quotes, no evidence check, no unit or tax rules, no rule engine.
The model is asked for a verdict per supplier, a comparable price and a recommendation, and is scored
against the same ground truth as the system.

    python -m evaluation.plain_ai_baseline            # 10 AI calls, about 3 minutes
    python -m evaluation.plain_ai_baseline --cases TC-03,TC-09

It is deliberately generous to the chat model: it gets the clean text of every readable document,
including the scanned one (as if it had read the image perfectly). Files that can't be opened are left
out with a note, as a person would. Writes evaluation/results/plain_ai_<time>.json and plain_ai_latest.md.
"""
import argparse
import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.agents import llm
from app.services.evaluation_engine import evaluate_all, recommend
from evaluation.cases import TODAY, build_cases
from evaluation.run_evaluation import RESULTS

VERDICTS = ("COMPLIANT", "NEEDS_CLARIFICATION", "NOT_COMPLIANT")


class PlainSupplier(BaseModel):
    name: str = ""
    verdict: str = ""
    price_per_unit_excl_tax: Optional[float] = None
    reason: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _norm(cls, v):
        return str(v or "").strip().upper().replace(" ", "_").replace("-", "_")

    @field_validator("price_per_unit_excl_tax", mode="before")
    @classmethod
    def _num(cls, v):
        if v in (None, "", "null", "unknown", "N/A"):
            return None
        try:
            return float(str(v).replace(",", "").replace("INR", "").strip())
        except ValueError:
            return None


class PlainAnswer(BaseModel):
    suppliers: list[PlainSupplier] = []
    recommended_supplier: Optional[str] = None


def build_prompt(case: dict) -> str:
    rfq = case["rfq_truth"]
    parts = [f"Today's date is {TODAY:%d %B %Y}.",
             "I sent the RFQ below to suppliers and received the quotations that follow. Please compare them.",
             "For each supplier, tell me whether the quotation is COMPLIANT (meets every requirement), "
             "NEEDS_CLARIFICATION (nothing clearly fails, but something required is missing or unclear) or "
             f"NOT_COMPLIANT (clearly fails a requirement). Give its price in {rfq.currency} per {rfq.unit} "
             "excluding GST (null if you can't tell). Then tell me which supplier to choose.",
             'Reply only with JSON: {"suppliers": [{"name": "...", "verdict": "...", '
             '"price_per_unit_excl_tax": 0, "reason": "..."}], "recommended_supplier": "..."}',
             "", "=== RFQ ===", case["rfq"]]
    for q in case["quotes"]:
        if q.get("expect_rejected") or q.get("format") in ("corrupt_pdf", "fake_xlsx"):
            parts += ["", f"=== {q['file']} ===", "(this file could not be opened)"]
        else:
            parts += ["", f"=== {q['file']} ===", q["text"]]
    return "\n".join(parts)


def _match(name: str, answer: PlainAnswer) -> Optional[PlainSupplier]:
    key = name.split()[0].lower()
    return next((s for s in answer.suppliers if key in (s.name or "").lower()), None)


def score_case(case: dict, answer: PlainAnswer) -> dict:
    """Scores one answer against the ground truth (no AI involved, so it is unit-tested)."""
    truths = [q for q in case["quotes"] if q.get("truth") and not q.get("expect_rejected")]
    expected_evals = {e.supplier_name: e for e in evaluate_all(case["rfq_truth"], [q["truth"] for q in truths], today=TODAY)}
    rows = []
    for q in truths:
        name = q["truth"].supplier_name
        got = _match(name, answer)
        exp_price = expected_evals[name].normalized_unit_price
        got_price = got.price_per_unit_excl_tax if got else None
        price_ok = (exp_price is None and got_price is None) or (
            exp_price is not None and got_price is not None and abs(got_price - exp_price) <= max(0.01 * exp_price, 0.01))
        rows.append({"supplier": name, "expected_verdict": q["verdict"], "got_verdict": got.verdict if got else "MISSING",
                     "verdict_ok": bool(got and got.verdict == q["verdict"]), "expected_price": exp_price,
                     "got_price": got_price, "price_ok": price_ok,
                     "flagged_gap": bool(got and got.verdict in ("NEEDS_CLARIFICATION", "NOT_COMPLIANT")),
                     "gap_expected": q["verdict"] != "COMPLIANT"})
    exp_rec = case["expect_recommended"] or ""
    got_rec = answer.recommended_supplier or ""
    rec_ok = exp_rec.split()[0].lower() in got_rec.lower() if exp_rec else not got_rec.strip()
    return {"case": case["id"], "title": case["title"], "suppliers": rows,
            "recommendation": {"expected": exp_rec or None, "got": got_rec or None, "ok": rec_ok}}


def summarise(results: list) -> dict:
    rows = [r for res in results for r in res["suppliers"]]
    pct = lambda a, b: round(100 * a / b, 1) if b else None  # noqa: E731
    gaps = [r for r in rows if r["gap_expected"]]
    return {"cases": len(results), "suppliers": len(rows),
            "verdict_accuracy": pct(sum(r["verdict_ok"] for r in rows), len(rows)),
            "price_accuracy": pct(sum(r["price_ok"] for r in rows), len(rows)),
            "recommendation_accuracy": pct(sum(r["recommendation"]["ok"] for r in results), len(results)),
            "gap_recall": pct(sum(r["flagged_gap"] for r in gaps), len(gaps)),
            "failed_calls": sum(1 for r in results if r.get("error"))}


def _latest_system_summary() -> Optional[dict]:
    from evaluation.run_evaluation import summarise as sys_summarise
    for f in sorted(RESULTS.glob("results_*.json"), reverse=True):
        data = json.loads(f.read_text(encoding="utf-8"))
        res = data.get("results", data) if isinstance(data, dict) else data
        if isinstance(res, list) and len(res) >= 10:
            return {"file": f.name, **sys_summarise(res)}
    return None


def report_md(summary: dict, results: list) -> str:
    sysm = _latest_system_summary()
    show = lambda v: "-" if v is None else f"{v}%"  # noqa: E731
    lines = [f"# Plain-AI baseline - {datetime.now():%Y-%m-%d %H:%M}", "",
             "The same 10 RFQs pasted into a chat model with one plain prompt: no rules, no source quotes, no checks.", "",
             "| Metric | Plain AI | This system |", "|---|---|---|",
             f"| Supplier verdict correct | {show(summary['verdict_accuracy'])} | {show(sysm['verdict_accuracy']) if sysm else '-'} |",
             f"| Comparable price correct (per unit, excl. tax) | {show(summary['price_accuracy'])} | see extraction accuracy |",
             f"| Recommendation correct | {show(summary['recommendation_accuracy'])} | {show(sysm['recommendation_accuracy']) if sysm else '-'} |",
             f"| Gaps flagged (quotes that should not pass) | {show(summary['gap_recall'])} | {show(sysm['missing_recall']) if sysm else '-'} |",
             "| Every value traceable to a source line | no | yes |", "",
             f"System figures from {sysm['file'] if sysm else 'no full system run found'}.", "",
             "## Where the plain AI went wrong", "",
             "| Case | Supplier | Expected | Got | Price expected | Price got |", "|---|---|---|---|---|---|"]
    for res in results:
        if res.get("error"):
            lines.append(f"| {res['case']} | (call failed) | | {res['error'][:80]} | | |")
        for r in res["suppliers"]:
            if not (r["verdict_ok"] and r["price_ok"]):
                lines.append(f"| {res['case']} | {r['supplier']} | {r['expected_verdict']} | {r['got_verdict']} | "
                             f"{r['expected_price']} | {r['got_price']} |")
        rec = res["recommendation"]
        if not rec["ok"]:
            lines.append(f"| {res['case']} | recommendation | {rec['expected']} | {rec['got']} | | |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", help="comma-separated case ids, e.g. TC-03,TC-09")
    args = ap.parse_args(argv)
    cases = build_cases()
    if args.cases:
        wanted = {c.strip().upper() for c in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in wanted]

    results = []
    for case in cases:
        print(f"=== {case['id']} - {case['title']}")
        try:
            answer, meta = llm.call_json("plain_ai_baseline", build_prompt(case), PlainAnswer)
            res = score_case(case, answer)
            res.update(model=meta.model, raw=answer.model_dump())
        except llm.ExtractionError as e:
            res = score_case(case, PlainAnswer())
            res["error"] = str(e)
        ok = sum(r["verdict_ok"] for r in res["suppliers"])
        print(f"    verdicts {ok}/{len(res['suppliers'])} · recommendation {'OK' if res['recommendation']['ok'] else 'WRONG'}"
              + (f" · {res['error'][:80]}" if res.get("error") else ""))
        results.append(res)

    summary = summarise(results)
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (RESULTS / f"plain_ai_{stamp}.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2,
                                                                default=str), encoding="utf-8")
    md = report_md(summary, results)
    (RESULTS / "plain_ai_latest.md").write_text(md, encoding="utf-8")
    print("\n" + md.split("## Where")[0])
    print(f"Full report: {RESULTS / 'plain_ai_latest.md'}")


if __name__ == "__main__":
    main()
