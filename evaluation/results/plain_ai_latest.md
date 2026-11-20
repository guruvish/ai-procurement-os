# Plain-AI baseline - 2026-11-20 10:00

The same 10 RFQs pasted into a chat model with one plain prompt: no rules, no source quotes, no checks.

| Metric | Plain AI | This system |
|---|---|---|
| Supplier verdict correct | 85.7% | 100.0% |
| Comparable price correct (per unit, excl. tax) | 100.0% | see extraction accuracy |
| Recommendation correct | 90.0% | 100.0% |
| Gaps flagged (quotes that should not pass) | 100.0% | 100.0% |
| Every value traceable to a source line | no | yes |

System figures from results_20261119_153126.json.

## Where the plain AI went wrong

| Case | Supplier | Expected | Got | Price expected | Price got |
|---|---|---|---|---|---|
| TC-05 | Sigma Actives | NEEDS_CLARIFICATION | NOT_COMPLIANT | 178.0 | 178.0 |
| TC-08 | Omega Drugs | NEEDS_CLARIFICATION | NOT_COMPLIANT | 174.0 | 174.0 |
| TC-09 | Theta Healthcare | COMPLIANT | NEEDS_CLARIFICATION | 180.0 | 180.0 |
| TC-09 | recommendation | Theta Healthcare | Acme Chem Industries | | |
