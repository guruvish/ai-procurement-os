"""Runs the 10 evaluation cases through the REAL system and scores the results against ground truth.

    python -m evaluation.run_evaluation                 # all 10 cases (~40 AI calls, ~10 min)
    python -m evaluation.run_evaluation --cases TC-01,TC-04

Writes evaluation/dataset/<case>/ (the generated documents + ground_truth.json) and
evaluation/results/latest.md + results_<time>.json. Uses its own database (data/evaluation.db),
so evaluation runs never appear in the app's dashboard.
"""
import argparse
import csv
import json
import time
from datetime import datetime
from pathlib import Path

from app import config, db
from app.agents import workflow
from app.schemas import CheckStatus
from app.services.analytics import payment_days
from app.services.document_parser import DocumentError, parse_document
from app.services.evaluation_engine import _cert_key, _find_spec, _related, evaluate_all, recommend
from app.services.normalization import convert, normalize_currency, same_unit
from evaluation.cases import TODAY, build_cases

ROOT = Path(__file__).resolve().parent
DATASET, RESULTS = ROOT / "dataset", ROOT / "results"
TARGETS = {"extraction_accuracy": 95.0, "verdict_accuracy": 95.0, "check_agreement": 95.0, "missing_recall": 90.0}
MISSING = (CheckStatus.UNKNOWN, CheckStatus.REVIEW_REQUIRED)


# ---------------------------------------------------------------- documents
def render(spec_format: str, text: str, mode: str = "real") -> bytes:
    """Turns case text into a real document. mode='text' (tests) writes plain CSV-safe text instead."""
    if spec_format == "corrupt_pdf":
        return b"%PDF-1.4\n%\xe2\xe3 this file was damaged in transit \x00\x01\x02 trailer"
    if spec_format == "fake_xlsx":
        return b"Item,Price\nParacetamol,180\n"   # a CSV renamed to .xlsx
    if mode == "text":
        return text.replace(",", ";").encode()
    if spec_format in ("pdf", "scanned"):
        import pymupdf as fitz
        doc = fitz.open()
        for part in text.split("\n\nATTACHED"):
            page_text = part if part.startswith("QUOTATION") or part.startswith("REQUEST") else "ATTACHED" + part
            doc.new_page().insert_textbox(fitz.Rect(50, 50, 550, 800), page_text, fontsize=10)
        if spec_format == "scanned":   # image-only PDF: what a scanner produces
            scanned = fitz.open()
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                new = scanned.new_page(width=page.rect.width, height=page.rect.height)
                new.insert_image(new.rect, stream=pix.tobytes("png"))
            return scanned.tobytes()
        return doc.tobytes()
    if spec_format == "xlsx":
        from io import BytesIO
        import pandas as pd
        rows = [(line.split(":", 1) + [""])[:2] if ":" in line else [line, ""] for line in text.splitlines() if line.strip()]
        buf = BytesIO()
        pd.DataFrame(rows, columns=["Field", "Value"]).to_excel(buf, index=False)
        return buf.getvalue()
    if spec_format == "docx":
        from io import BytesIO
        from docx import Document
        doc = Document()
        for line in text.splitlines():
            doc.add_paragraph(line)
        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()
    raise ValueError(spec_format)


def doc_name(spec: dict, mode: str) -> str:
    name = spec["file"]
    if mode == "text" and spec.get("format") not in ("corrupt_pdf", "fake_xlsx"):
        name = name.rsplit(".", 1)[0] + ".csv"
    return name


# ---------------------------------------------------------------- field comparison
def _num_eq(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))
    except (TypeError, ValueError):
        return False


def _row(scope, field, expected, got, ok):
    return {"scope": scope, "field": field, "expected": None if expected is None else str(expected),
            "got": None if got is None else str(got), "ok": bool(ok)}


def compare_rfq(t, g) -> list:
    s = "RFQ"
    out = [_row(s, "product_name", t.product_name, g.product_name,
                bool(g.product_name) and t.product_name.lower() in g.product_name.lower()),
           _row(s, "required_quantity", t.required_quantity, g.required_quantity,
                _num_eq(t.required_quantity, convert(g.required_quantity, g.unit, t.unit) if g.unit else g.required_quantity)),
           _row(s, "unit", t.unit, g.unit, same_unit(t.unit, g.unit)),
           _row(s, "max_delivery_days", t.max_delivery_days, g.max_delivery_days, _num_eq(t.max_delivery_days, g.max_delivery_days)),
           _row(s, "currency", t.currency, g.currency, normalize_currency(t.currency) == normalize_currency(g.currency)),
           _row(s, "payment_days", payment_days(t.payment_terms), payment_days(g.payment_terms),
                payment_days(t.payment_terms) == payment_days(g.payment_terms)),
           _row(s, "required_certificates", sorted(_cert_key(c) for c in t.required_certificates),
                sorted(_cert_key(c) for c in g.required_certificates),
                {_cert_key(c) for c in t.required_certificates} == {_cert_key(c) for c in g.required_certificates})]
    for tr in t.technical_requirements:
        gr = next((r for r in g.technical_requirements if _related(r.name, tr.name)), None)
        out += [_row(s, f"req:{tr.name}.operator", tr.operator, gr and gr.operator, gr is not None and gr.operator == tr.operator),
                _row(s, f"req:{tr.name}.value", tr.value, gr and gr.value, gr is not None and _num_eq(tr.value, gr.value)),
                _row(s, f"req:{tr.name}.mandatory", tr.mandatory, gr and gr.mandatory, gr is not None and gr.mandatory == tr.mandatory)]
    return out


def compare_quote(t, g) -> list:
    s = t.supplier_name
    if g is None:
        return [_row(s, "extracted", "yes", "no", False)]
    first = t.supplier_name.split()[0].lower()
    out = [_row(s, "supplier_name", t.supplier_name, g.supplier_name, first in (g.supplier_name or "").lower()),
           _row(s, "unit_price", t.unit_price, g.unit_price, _num_eq(t.unit_price, g.unit_price)),
           _row(s, "price_per", t.price_per, g.price_per,
                (t.price_per is None and g.price_per is None) or (t.price_per is not None and same_unit(t.price_per, g.price_per))),
           _row(s, "currency", t.currency, g.currency,
                t.unit_price is None or normalize_currency(t.currency) == normalize_currency(g.currency)),
           _row(s, "tax_status", t.tax_status, g.tax_status, t.tax_status == g.tax_status),
           _row(s, "tax_rate_percent", t.tax_rate_percent, g.tax_rate_percent, _num_eq(t.tax_rate_percent, g.tax_rate_percent)),
           _row(s, "delivery_days", t.delivery_days, g.delivery_days, _num_eq(t.delivery_days, g.delivery_days)),
           _row(s, "valid_until", t.valid_until, g.valid_until, t.valid_until == g.valid_until),
           _row(s, "quotation_date", t.quotation_date, g.quotation_date, t.quotation_date == g.quotation_date),
           _row(s, "quantity", f"{t.quantity} {t.unit}", f"{g.quantity} {g.unit}",
                _num_eq(t.quantity, convert(g.quantity, g.unit, t.unit) if (g.unit and t.unit) else g.quantity)),
           _row(s, "payment_days", payment_days(t.payment_terms), payment_days(g.payment_terms),
                payment_days(t.payment_terms) == payment_days(g.payment_terms)),
           _row(s, "certificates", sorted(_cert_key(c) for c in t.certificates), sorted(_cert_key(c) for c in g.certificates),
                {_cert_key(c) for c in t.certificates} == {_cert_key(c) for c in g.certificates}),
           _row(s, "conflict_flagged", bool(t.conflicts), bool(g.conflicts), bool(t.conflicts) == bool(g.conflicts))]
    for ts in t.specifications:
        gs = _find_spec(g, ts.name)
        out.append(_row(s, f"spec:{ts.name}", ts.value, gs and gs.value, gs is not None and _num_eq(ts.value, gs.value)))
    return out


# ---------------------------------------------------------------- one case
def check_key(name: str) -> str:
    """Match checks by meaning, not spelling: 'certificate: GMP Certificate' == 'certificate: GMP certificate'."""
    if name.startswith("certificate: "):
        return "certificate:" + _cert_key(name.split(": ", 1)[1])
    return name


def find_check(ev, requirement: str):
    if ev is None:
        return None
    key = check_key(requirement)
    exact = next((c for c in ev.checks if check_key(c.requirement) == key), None)
    if exact or requirement.startswith("certificate: "):
        return exact
    return next((c for c in ev.checks if _related(c.requirement, requirement)), None)


def run_case(case: dict, mode: str = "real", out_dir: Path = DATASET) -> dict:
    stamp = datetime.now().strftime("%H%M%S")
    folder = out_dir / f"{case['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    rid = db.create_request(f"{case['rfq_truth'].rfq_id}-{stamp}", title=case["title"], department="Evaluation",
                            buyer="Synthetic dataset", actor="evaluation")
    uploads, rejected = [], {}
    for role, spec in [("RFQ", {"file": f"RFQ_{case['id']}.pdf", "format": "pdf", "text": case["rfq"]})] + \
                      [("QUOTATION", q) for q in case["quotes"]]:
        name = doc_name(spec, mode)
        data = render(spec["format"], spec.get("text", ""), mode)
        (folder / name).write_bytes(data)
        try:
            parsed = parse_document(name, data, config.MAX_FILE_MB)
            db.save_document(rid, name, data, parsed.sha256, parsed.file_type, role, "evaluation")
            uploads.append((name, spec))
        except DocumentError as e:
            rejected[name] = str(e)
    (folder / "ground_truth.json").write_text(json.dumps({
        "case": case["id"], "title": case["title"], "rfq": case["rfq_truth"].model_dump(mode="json"),
        "quotes": [{"file": doc_name(q, mode), "expected_verdict": q.get("verdict"),
                    "expect_rejected": q.get("expect_rejected", False),
                    "truth": q["truth"].model_dump(mode="json") if q.get("truth") else None} for q in case["quotes"]],
        "expect_recommended": case["expect_recommended"]}, indent=2), encoding="utf-8")

    t0 = time.time()
    try:
        res = workflow.run_processing(rid, actor="evaluation")
    except Exception as e:  # recorded as a failed case, the run continues
        res = {"outcome": "crashed", "error": f"{type(e).__name__}: {e}", "metrics": {}, "doc_errors": []}
    seconds = round(time.time() - t0, 1)

    fields, decisions, notes = [], [], []
    got_rfq = db.get_rfq(rid)
    fields += compare_rfq(case["rfq_truth"], got_rfq) if got_rfq else [_row("RFQ", "extracted", "yes", "no", False)]
    by_file = {d["id"]: d["filename"] for d in db.list_documents(rid)}
    got_quotes = {by_file[x["document_id"]]: x["quotation"] for x in db.list_quotations(rid)}
    got_evals = {e.supplier_name: e for e in db.get_evaluations(rid)}
    truth_quotes = [q["truth"] for q in case["quotes"] if q.get("truth")]
    truth_evals = {e.supplier_name: e for e in evaluate_all(case["rfq_truth"], truth_quotes, today=TODAY)}

    tp = fp = fn = 0
    for q in case["quotes"]:
        name = doc_name(q, mode)
        if q.get("expect_rejected"):
            ok = name in rejected
            decisions.append({"supplier": name, "type": "rejected_with_message", "expected": True, "got": ok, "ok": ok})
            continue
        if name in rejected:
            notes.append(f"{name} was rejected unexpectedly: {rejected[name]}")
        g = got_quotes.get(name)
        fields += compare_quote(q["truth"], g)
        ge = got_evals.get(g.supplier_name) if g else None
        te = truth_evals[q["truth"].supplier_name]
        decisions.append({"supplier": q["truth"].supplier_name, "type": "verdict", "expected": q["verdict"],
                          "got": ge.overall_status if ge else "NOT EVALUATED", "ok": bool(ge and ge.overall_status == q["verdict"])})
        if te.overall_status != q["verdict"]:
            notes.append(f"Ground-truth inconsistency: hand-written verdict {q['verdict']} for {te.supplier_name}, "
                         f"rules on ground truth give {te.overall_status}")
        for tc in te.checks:
            gc = find_check(ge, tc.requirement)
            gs = gc.status if gc else None
            decisions.append({"supplier": te.supplier_name, "type": f"check:{tc.requirement}", "expected": tc.status.value,
                              "got": gs.value if gs else None, "ok": gs == tc.status})
            exp_m, got_m = tc.status in MISSING, gs in MISSING
            tp += exp_m and got_m
            fp += (not exp_m) and got_m
            fn += exp_m and not got_m

    rec = db.get_recommendation(rid) or {}
    got_rec = rec.get("recommended_supplier") or ""
    rec_ok = case["expect_recommended"].split()[0].lower() in got_rec.lower() if case["expect_recommended"] else not got_rec
    m = res.get("metrics", {})
    return {"case": case["id"], "title": case["title"], "outcome": res.get("outcome"), "error": res.get("error"),
            "seconds": seconds, "ai_calls": m.get("ai_calls", 0), "ai_calls_failed": m.get("ai_calls_failed", 0),
            "repair_retries": m.get("ai_repair_retries", 0), "rate_limit_waits": m.get("rate_limit_waits", 0),
            "models_used": m.get("models_used", []), "vision_calls": m.get("vision_calls", 0),
            "fields": fields, "decisions": decisions, "missing": {"tp": tp, "fp": fp, "fn": fn},
            "recommendation": {"expected": case["expect_recommended"], "got": got_rec or None, "ok": rec_ok},
            "rejected": rejected, "notes": notes}


# ---------------------------------------------------------------- summary + report
def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def _show(v, unit="%"):
    return "n/a (nothing to measure in these cases)" if v is None else f"{v}{unit}"


def summarise(results: list) -> dict:
    fields = [f for r in results for f in r["fields"]]
    verdicts = [d for r in results for d in r["decisions"] if d["type"] == "verdict"]
    checks = [d for r in results for d in r["decisions"] if d["type"].startswith("check:")]
    rejections = [d for r in results for d in r["decisions"] if d["type"] == "rejected_with_message"]
    tp = sum(r["missing"]["tp"] for r in results)
    fp = sum(r["missing"]["fp"] for r in results)
    fn = sum(r["missing"]["fn"] for r in results)
    return {"cases": len(results),
            "extraction_accuracy": _pct(sum(f["ok"] for f in fields), len(fields)), "fields_total": len(fields),
            "verdict_accuracy": _pct(sum(d["ok"] for d in verdicts), len(verdicts)), "verdicts_total": len(verdicts),
            "check_agreement": _pct(sum(d["ok"] for d in checks), len(checks)), "checks_total": len(checks),
            "recommendation_accuracy": _pct(sum(r["recommendation"]["ok"] for r in results), len(results)),
            "missing_precision": _pct(tp, tp + fp), "missing_recall": _pct(tp, tp + fn),
            "bad_files_rejected": f"{sum(d['ok'] for d in rejections)}/{len(rejections)}",
            "avg_seconds_per_case": round(sum(r["seconds"] for r in results) / len(results), 1) if results else None,
            "ai_calls": sum(r["ai_calls"] for r in results), "ai_calls_failed": sum(r["ai_calls_failed"] for r in results),
            "repair_retries": sum(r["repair_retries"] for r in results),
            "rate_limit_waits": sum(r["rate_limit_waits"] for r in results),
            "models_used": sorted({m for r in results for m in r["models_used"]}),
            "crashed_cases": [r["case"] for r in results if r["outcome"] == "crashed"]}


def load_baseline() -> dict:
    path = ROOT / "baseline.csv"
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["case", "manual_minutes", "manual_errors", "notes"])
            for c in build_cases():
                w.writerow([c["id"], "", "", ""])
        return {}
    rows = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("manual_minutes") or "").strip():
                rows[r["case"]] = {"minutes": float(r["manual_minutes"]),
                                   "errors": int(r["manual_errors"] or 0), "notes": r.get("notes", "")}
    return rows


def report_md(summary: dict, results: list, baseline: dict) -> str:
    def mark(key):
        v = summary[key]
        return "-" if v is None else ("PASS" if v >= TARGETS[key] else "BELOW TARGET")
    lines = [f"# Evaluation results - {datetime.now():%Y-%m-%d %H:%M}", "",
             f"Cases: **{summary['cases']}** · AI calls: {summary['ai_calls']} (failed {summary['ai_calls_failed']}, "
             f"repair retries {summary['repair_retries']}, rate-limit waits {summary['rate_limit_waits']}) · "
             f"Models: {', '.join(summary['models_used']) or '-'}", "",
             "| Metric | Result | Target | |", "|---|---|---|---|",
             f"| Extraction accuracy (required fields) | {summary['extraction_accuracy']}% of {summary['fields_total']} | 95% | {mark('extraction_accuracy')} |",
             f"| Supplier verdict accuracy | {summary['verdict_accuracy']}% of {summary['verdicts_total']} | 95% | {mark('verdict_accuracy')} |",
             f"| Requirement-check agreement | {summary['check_agreement']}% of {summary['checks_total']} | 95% | {mark('check_agreement')} |",
             f"| Recommendation correct | {_show(summary['recommendation_accuracy'])} | - | |",
             f"| Missing-info detection - recall | {_show(summary['missing_recall'])} | 90% | {mark('missing_recall')} |",
             f"| Missing-info detection - precision | {_show(summary['missing_precision'])} | - | |",
             f"| Bad files rejected with a message | {summary['bad_files_rejected']} | all | |",
             f"| Avg processing time per case | {summary['avg_seconds_per_case']} s | - | |", "",
             "## Per case", "", "| Case | Scenario | Fields | Verdicts | Recommendation | Time | AI calls | Notes |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        f_ok, f_n = sum(f["ok"] for f in r["fields"]), len(r["fields"])
        v = [d for d in r["decisions"] if d["type"] in ("verdict", "rejected_with_message")]
        rec = r["recommendation"]
        lines.append(f"| {r['case']} | {r['title']} | {f_ok}/{f_n} | {sum(d['ok'] for d in v)}/{len(v)} | "
                     f"{'OK' if rec['ok'] else 'WRONG'} ({rec['got'] or 'none'}) | {r['seconds']} s | {r['ai_calls']} | "
                     f"{'; '.join(r['notes'] + ([r['error']] if r.get('error') else []))[:160]} |")
    lines += ["", "## Every mismatch (input for failure analysis)", ""]
    misses = [(r["case"], f) for r in results for f in r["fields"] if not f["ok"]]
    misses += [(r["case"], {"scope": d["supplier"], "field": d["type"], "expected": d["expected"], "got": d["got"]})
               for r in results for d in r["decisions"] if not d["ok"]]
    if misses:
        lines += ["| Case | Where | Field / check | Expected | Got |", "|---|---|---|---|---|"]
        lines += [f"| {c} | {m['scope']} | {m['field']} | {m['expected']} | {m['got']} |" for c, m in misses]
    else:
        lines.append("None - every field, verdict and check matched the ground truth.")
    lines += ["", "## Baseline comparison (manual process)", ""]
    if baseline:
        done = [r for r in results if r["case"] in baseline]
        man = sum(baseline[r["case"]]["minutes"] for r in done) / len(done)
        sysm = sum(r["seconds"] for r in done) / len(done) / 60
        lines += [f"Measured on {len(done)} case(s): manual **{man:.1f} min** per case "
                  f"({sum(baseline[r['case']]['errors'] for r in done)} manual errors) vs system processing **{sysm:.1f} min**. "
                  "Human review time with the system must be added - see docs/evaluation_report.md."]
    else:
        lines.append("Not filled yet: time yourself doing a case by hand and enter it in `evaluation/baseline.csv`.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", help="comma-separated case ids, e.g. TC-01,TC-04 (default: all)")
    ap.add_argument("--report-only", action="store_true",
                    help="no AI calls: rebuild latest.md from the newest results file (e.g. after filling baseline.csv)")
    args = ap.parse_args(argv)
    if args.report_only:
        files = sorted(RESULTS.glob("results_*.json"), reverse=True)
        if not files:
            raise SystemExit("No results yet - run the evaluation first.")
        loaded = [(f, json.loads(f.read_text(encoding="utf-8"))) for f in files]
        full = [x for x in loaded if len(x[1]["results"]) == len(build_cases())]
        src, data = (full or loaded)[0]
        files = [src]
        md = report_md(summarise(data["results"]), data["results"], load_baseline())
        (RESULTS / "latest.md").write_text(md, encoding="utf-8")
        print(md.split("## Per case")[0] + f"\nRebuilt from {files[-1].name} -> {RESULTS / 'latest.md'}")
        return
    db.DB_PATH = config.DATA_DIR / "evaluation.db"
    db.UPLOAD_DIR = config.DATA_DIR / "evaluation_uploads"
    db.init_db()
    cases = build_cases()
    if args.cases:
        wanted = {c.strip().upper() for c in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    RESULTS.mkdir(parents=True, exist_ok=True)
    results = []
    for c in cases:
        print(f"\n=== {c['id']} - {c['title']}")
        r = run_case(c)
        results.append(r)
        f_ok = sum(f["ok"] for f in r["fields"])
        print(f"    {r['outcome']} in {r['seconds']}s · fields {f_ok}/{len(r['fields'])} · "
              f"recommendation {'OK' if r['recommendation']['ok'] else 'WRONG'} · AI calls {r['ai_calls']}")
    summary = summarise(results)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (RESULTS / f"results_{stamp}.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2), encoding="utf-8")
    md = report_md(summary, results, load_baseline())
    name = "latest.md" if not args.cases else f"latest_{'_'.join(sorted(c['id'] for c in cases))}.md"
    (RESULTS / name).write_text(md, encoding="utf-8")
    print("\n" + md.split("## Per case")[0])
    print(f"Full report: {RESULTS / name}")


if __name__ == "__main__":
    main()
