# Evaluation results - 2026-11-19 23:09

Cases: **10** · AI calls: 26 (failed 5, repair retries 1, rate-limit waits 0) · Models: gemini:gemini-2.5-flash, gemini:gemini-3.5-flash-lite

| Metric | Result | Target | |
|---|---|---|---|
| Extraction accuracy (required fields) | 96.4% of 309 | 95% | PASS |
| Supplier verdict accuracy | 57.1% of 21 | 95% | BELOW TARGET |
| Requirement-check agreement | 62.9% of 143 | 95% | BELOW TARGET |
| Recommendation correct | 50.0% | - | |
| Missing-info detection - recall | 80.0% | 90% | BELOW TARGET |
| Missing-info detection - precision | 80.0% | - | |
| Bad files rejected with a message | 2/2 | all | |
| Avg processing time per case | 52.2 s | - | |

## Per case

| Case | Scenario | Fields | Verdicts | Recommendation | Time | AI calls | Notes |
|---|---|---|---|---|---|---|---|
| TC-01 | Normal RFQ - three complete quotations (PDF, Excel, Word) | 57/58 | 2/3 | OK (Delta Life Sciences, Pune) | 69.8 s | 4 |  |
| TC-02 | Supplier quotation missing price | 28/29 | 1/2 | WRONG (none) | 94.6 s | 3 |  |
| TC-03 | Different measurement units (price per MT vs per gram) | 0/3 | 0/2 | WRONG (none) | 17.8 s | 1 | RFQ could not be processed: All AI providers are busy or unavailable right now (gemini:gemini-2.5-flash - daily quota used up; gemini:gemini-3.5-flash-lite - ov |
| TC-04 | Scanned quotation PDF (image only, no text layer) | 43/43 | 2/2 | OK (Kappa Fine Chemicals, Chennai) | 49.8 s | 3 |  |
| TC-05 | Conflicting purity values in one quotation | 43/43 | 2/2 | OK (Acme Chem Industries) | 81.4 s | 3 |  |
| TC-06 | Missing Certificate of Analysis | 28/29 | 1/2 | WRONG (none) | 64.0 s | 3 |  |
| TC-07 | Supplier delivery exceeds the limit | 28/29 | 1/2 | WRONG (none) | 43.7 s | 3 |  |
| TC-08 | Quotation has expired | 43/43 | 2/2 | OK (Acme Chem Industries) | 49.2 s | 3 |  |
| TC-09 | GST treatment differs (inclusive / exclusive / unclear) | 0/4 | 0/3 | WRONG (none) | 19.8 s | 1 | RFQ could not be processed: All AI providers are busy or unavailable right now (gemini:gemini-2.5-flash - daily quota used up; gemini:gemini-3.5-flash-lite - ov |
| TC-10 | Corrupted / wrong documents among valid ones | 28/28 | 3/3 | OK (Acme Chem Industries) | 31.5 s | 2 |  |

## Every mismatch (input for failure analysis)

| Case | Where | Field / check | Expected | Got |
|---|---|---|---|---|
| TC-01 | Acme Chem Industries | spec:purity | 99.8 | None |
| TC-02 | Acme Chem Industries | extracted | yes | no |
| TC-03 | RFQ | extracted | yes | no |
| TC-03 | Cellutech Industries | extracted | yes | no |
| TC-03 | FibreChem Pvt Ltd | extracted | yes | no |
| TC-06 | Acme Chem Industries | extracted | yes | no |
| TC-07 | Acme Chem Industries | extracted | yes | no |
| TC-09 | RFQ | extracted | yes | no |
| TC-09 | Acme Chem Industries | extracted | yes | no |
| TC-09 | Theta Healthcare | extracted | yes | no |
| TC-09 | Lambda Chem | extracted | yes | no |
| TC-01 | Acme Chem Industries | verdict | COMPLIANT | NEEDS_CLARIFICATION |
| TC-01 | Acme Chem Industries | check:purity | PASS | UNKNOWN |
| TC-02 | Acme Chem Industries | verdict | COMPLIANT | NOT EVALUATED |
| TC-02 | Acme Chem Industries | check:purity | PASS | None |
| TC-02 | Acme Chem Industries | check:moisture | PASS | None |
| TC-02 | Acme Chem Industries | check:certificate: Certificate of Analysis | PASS | None |
| TC-02 | Acme Chem Industries | check:certificate: GMP certificate | PASS | None |
| TC-02 | Acme Chem Industries | check:delivery_days | PASS | None |
| TC-02 | Acme Chem Industries | check:quotation_validity | PASS | None |
| TC-02 | Acme Chem Industries | check:price | PASS | None |
| TC-03 | Cellutech Industries | verdict | COMPLIANT | NOT EVALUATED |
| TC-03 | Cellutech Industries | check:moisture | PASS | None |
| TC-03 | Cellutech Industries | check:certificate: Certificate of Analysis | PASS | None |
| TC-03 | Cellutech Industries | check:delivery_days | PASS | None |
| TC-03 | Cellutech Industries | check:quotation_validity | PASS | None |
| TC-03 | Cellutech Industries | check:price | PASS | None |
| TC-03 | FibreChem Pvt Ltd | verdict | COMPLIANT | NOT EVALUATED |
| TC-03 | FibreChem Pvt Ltd | check:moisture | PASS | None |
| TC-03 | FibreChem Pvt Ltd | check:certificate: Certificate of Analysis | PASS | None |
| TC-03 | FibreChem Pvt Ltd | check:delivery_days | PASS | None |
| TC-03 | FibreChem Pvt Ltd | check:quotation_validity | PASS | None |
| TC-03 | FibreChem Pvt Ltd | check:price | PASS | None |
| TC-06 | Acme Chem Industries | verdict | COMPLIANT | NOT EVALUATED |
| TC-06 | Acme Chem Industries | check:purity | PASS | None |
| TC-06 | Acme Chem Industries | check:moisture | PASS | None |
| TC-06 | Acme Chem Industries | check:certificate: Certificate of Analysis | PASS | None |
| TC-06 | Acme Chem Industries | check:certificate: GMP certificate | PASS | None |
| TC-06 | Acme Chem Industries | check:delivery_days | PASS | None |
| TC-06 | Acme Chem Industries | check:quotation_validity | PASS | None |
| TC-06 | Acme Chem Industries | check:price | PASS | None |
| TC-07 | Acme Chem Industries | verdict | COMPLIANT | NOT EVALUATED |
| TC-07 | Acme Chem Industries | check:purity | PASS | None |
| TC-07 | Acme Chem Industries | check:moisture | PASS | None |
| TC-07 | Acme Chem Industries | check:certificate: Certificate of Analysis | PASS | None |
| TC-07 | Acme Chem Industries | check:certificate: GMP certificate | PASS | None |
| TC-07 | Acme Chem Industries | check:delivery_days | PASS | None |
| TC-07 | Acme Chem Industries | check:quotation_validity | PASS | None |
| TC-07 | Acme Chem Industries | check:price | PASS | None |
| TC-09 | Acme Chem Industries | verdict | COMPLIANT | NOT EVALUATED |
| TC-09 | Acme Chem Industries | check:purity | PASS | None |
| TC-09 | Acme Chem Industries | check:moisture | PASS | None |
| TC-09 | Acme Chem Industries | check:certificate: Certificate of Analysis | PASS | None |
| TC-09 | Acme Chem Industries | check:certificate: GMP certificate | PASS | None |
| TC-09 | Acme Chem Industries | check:delivery_days | PASS | None |
| TC-09 | Acme Chem Industries | check:quotation_validity | PASS | None |
| TC-09 | Acme Chem Industries | check:price | PASS | None |
| TC-09 | Theta Healthcare | verdict | COMPLIANT | NOT EVALUATED |
| TC-09 | Theta Healthcare | check:purity | PASS | None |
| TC-09 | Theta Healthcare | check:moisture | PASS | None |
| TC-09 | Theta Healthcare | check:certificate: Certificate of Analysis | PASS | None |
| TC-09 | Theta Healthcare | check:certificate: GMP certificate | PASS | None |
| TC-09 | Theta Healthcare | check:delivery_days | PASS | None |
| TC-09 | Theta Healthcare | check:quotation_validity | PASS | None |
| TC-09 | Theta Healthcare | check:price | PASS | None |
| TC-09 | Lambda Chem | verdict | NEEDS_CLARIFICATION | NOT EVALUATED |
| TC-09 | Lambda Chem | check:purity | PASS | None |
| TC-09 | Lambda Chem | check:moisture | PASS | None |
| TC-09 | Lambda Chem | check:certificate: Certificate of Analysis | PASS | None |
| TC-09 | Lambda Chem | check:certificate: GMP certificate | PASS | None |
| TC-09 | Lambda Chem | check:delivery_days | PASS | None |
| TC-09 | Lambda Chem | check:quotation_validity | PASS | None |
| TC-09 | Lambda Chem | check:price | REVIEW_REQUIRED | None |

## Baseline comparison (manual process)

Not filled yet: time yourself doing a case by hand and enter it in `evaluation/baseline.csv`.
