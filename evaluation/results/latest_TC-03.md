# Evaluation results - 2026-11-19 16:18

Cases: **1** · AI calls: 3 (failed 0, repair retries 0, rate-limit waits 0) · Models: gemini:gemini-3.5-flash-lite

| Metric | Result | Target | |
|---|---|---|---|
| Extraction accuracy (required fields) | 100.0% of 38 | 95% | PASS |
| Supplier verdict accuracy | 100.0% of 2 | 95% | PASS |
| Requirement-check agreement | 100.0% of 10 | 95% | PASS |
| Recommendation correct | 100.0% | - | |
| Missing-info detection - recall | n/a (nothing to measure in these cases) | 90% | - |
| Missing-info detection - precision | n/a (nothing to measure in these cases) | - | |
| Bad files rejected with a message | 0/0 | all | |
| Avg processing time per case | 30.3 s | - | |

## Per case

| Case | Scenario | Fields | Verdicts | Recommendation | Time | AI calls | Notes |
|---|---|---|---|---|---|---|---|
| TC-03 | Different measurement units (price per MT vs per gram) | 38/38 | 2/2 | OK (Cellutech Industries) | 30.3 s | 3 |  |

## Every mismatch (input for failure analysis)

None - every field, verdict and check matched the ground truth.

## Baseline comparison (manual process)

Not filled yet: time yourself doing a case by hand and enter it in `evaluation/baseline.csv`.
