"""The plain-AI baseline scorer, checked without any AI call."""
from app.services.evaluation_engine import evaluate_all
from evaluation.cases import TODAY, build_cases
from evaluation.plain_ai_baseline import PlainAnswer, PlainSupplier, build_prompt, score_case, summarise


def _perfect(case):
    truths = [q for q in case["quotes"] if q.get("truth") and not q.get("expect_rejected")]
    evals = {e.supplier_name: e for e in evaluate_all(case["rfq_truth"], [q["truth"] for q in truths], today=TODAY)}
    return PlainAnswer(suppliers=[PlainSupplier(name=q["truth"].supplier_name, verdict=q["verdict"],
                                                price_per_unit_excl_tax=evals[q["truth"].supplier_name].normalized_unit_price)
                                  for q in truths], recommended_supplier=case["expect_recommended"])


def test_perfect_answer_scores_100():
    results = [score_case(c, _perfect(c)) for c in build_cases()]
    s = summarise(results)
    assert s["verdict_accuracy"] == s["price_accuracy"] == s["recommendation_accuracy"] == s["gap_recall"] == 100.0


def test_wrong_answer_is_caught():
    case = build_cases()[8]                       # TC-09: tax inclusive / exclusive / unclear
    ans = _perfect(case)
    ans.suppliers[1].price_per_unit_excl_tax = 212.40   # forgot to take GST out
    ans.suppliers[2].verdict = "compliant"              # treated "tax not stated" as fine
    ans.recommended_supplier = "Lambda Chem"
    r = score_case(case, ans)
    assert [x["price_ok"] for x in r["suppliers"]] == [True, False, True]
    assert [x["verdict_ok"] for x in r["suppliers"]] == [True, True, False]
    assert r["recommendation"]["ok"] is False


def test_unreadable_files_are_left_out_of_the_prompt():
    tc10 = build_cases()[9]
    prompt = build_prompt(tc10)
    assert "(this file could not be opened)" in prompt
    assert "RFQ" in prompt and "Today's date" in prompt
