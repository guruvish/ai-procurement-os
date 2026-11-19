# Evaluation results - 2026-11-19 23:16

Cases: **10** · AI calls: 31 (failed 0, repair retries 0, rate-limit waits 0) · Models: gemini:gemini-2.5-flash, gemini:gemini-3.5-flash-lite

| Metric | Result | Target | |
|---|---|---|---|
| Extraction accuracy (required fields) | 99.5% of 440 | 95% | PASS |
| Supplier verdict accuracy | 100.0% of 21 | 95% | PASS |
| Requirement-check agreement | 100.0% of 143 | 95% | PASS |
| Recommendation correct | 100.0% | - | |
| Missing-info detection - recall | 100.0% | 90% | PASS |
| Missing-info detection - precision | 100.0% | - | |
| Bad files rejected with a message | 2/2 | all | |
| Avg processing time per case | 31.7 s | - | |

## Per case

| Case | Scenario | Fields | Verdicts | Recommendation | Time | AI calls | Notes |
|---|---|---|---|---|---|---|---|
| TC-01 | Normal RFQ - three complete quotations (PDF, Excel, Word) | 58/58 | 3/3 | OK (Delta Life Sciences, Pune) | 45.9 s | 4 |  |
| TC-02 | Supplier quotation missing price | 43/43 | 2/2 | OK (Acme Chem Industries) | 22.0 s | 3 |  |
| TC-03 | Different measurement units (price per MT vs per gram) | 36/38 | 2/2 | OK (Cellutech Industries) | 26.3 s | 3 |  |
| TC-04 | Scanned quotation PDF (image only, no text layer) | 43/43 | 2/2 | OK (Kappa Fine Chemicals, Chennai) | 34.3 s | 3 |  |
| TC-05 | Conflicting purity values in one quotation | 43/43 | 2/2 | OK (Acme Chem Industries) | 24.9 s | 3 |  |
| TC-06 | Missing Certificate of Analysis | 43/43 | 2/2 | OK (Acme Chem Industries) | 27.8 s | 3 |  |
| TC-07 | Supplier delivery exceeds the limit | 43/43 | 2/2 | OK (Acme Chem Industries) | 22.6 s | 3 |  |
| TC-08 | Quotation has expired | 43/43 | 2/2 | OK (Acme Chem Industries) | 25.2 s | 3 |  |
| TC-09 | GST treatment differs (inclusive / exclusive / unclear) | 58/58 | 3/3 | OK (Theta Healthcare) | 48.7 s | 4 |  |
| TC-10 | Corrupted / wrong documents among valid ones | 28/28 | 3/3 | OK (Acme Chem Industries, Hyderabad) | 39.3 s | 2 |  |

## Every mismatch (input for failure analysis)

| Case | Where | Field / check | Expected | Got |
|---|---|---|---|---|
| TC-03 | FibreChem Pvt Ltd | unit_price | 0.21 | 210.0 |
| TC-03 | FibreChem Pvt Ltd | price_per | g | kg |

## Baseline comparison (manual process)

Not filled yet: time yourself doing a case by hand and enter it in `evaluation/baseline.csv`.
