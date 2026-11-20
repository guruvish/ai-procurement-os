# Evaluation report

## 1. Question
Does the system extract quotation data correctly, reach the same supplier verdicts and recommendation a careful
buyer would, detect missing information, and do it faster than the manual process - across normal, edge and
failure scenarios?

## 2. Dataset - 10 cases (`evaluation/cases.py`, generated into `evaluation/dataset/`)

| Case | Scenario | Documents | What is being tested |
|---|---|---|---|
| TC-01 | Normal RFQ, 3 complete quotes | PDF + **Excel + Word** | Formats, ranking |
| TC-02 | Price "to be confirmed" | PDF | Missing value stays UNKNOWN, never 0 |
| TC-03 | Price per **MT** vs per **gram**, quantity in MT | PDF | Unit normalization |
| TC-04 | **Scanned** quote (image only) | image PDF | Vision extraction, "please verify" flag |
| TC-05 | Purity 99.8% on quote, **99.2% on attached CoA** | 2-page PDF | Conflict detection |
| TC-06 | No Certificate of Analysis | PDF | Documentation incomplete |
| TC-07 | Delivery "6 weeks" vs 30-day limit | PDF | Rule failure, weeks -> days |
| TC-08 | Quotation **expired** | PDF | Validity check |
| TC-09 | Price **incl. GST 18%** / tax **not stated** | PDF | Tax normalization, incomparable price |
| TC-10 | **Corrupted PDF** + CSV renamed to .xlsx | broken files | Clear rejection, batch continues |

21 supplier quotations, 440 scored fields, 143 requirement checks. Dates are relative to the run date.
**Ground truth** (`ground_truth.json` per case) was written by hand from the document text. Its consistency
is itself tested: a "perfect extractor" run (`tests/test_eval_harness.py`) must give 100% everywhere, so a
hand-written verdict that contradicts the rules fails the build. (While authoring the cases, one such verdict -
TC-03 FibreChem - was found by review and corrected; the test now guards against repeats.)

**Limitation:** documents are synthetic and cleanly formatted; real supplier documents will be harder.

## 3. Rubric (pass/fail criteria)

| Metric | Definition | Target |
|---|---|---|
| Extraction accuracy | Required fields equal to ground truth (numbers exact; units/currencies/certificates by meaning) | ≥ 95% |
| Verdict accuracy | Supplier verdict (Compliant / Needs clarification / Not compliant) equals the hand-written verdict | ≥ 95% |
| Check agreement | Each requirement status equals the status the rules give on the ground truth | ≥ 95% |
| Recommendation | Recommended supplier equals expected | all |
| Missing-info detection | Precision / recall of UNKNOWN + REVIEW_REQUIRED checks | recall ≥ 90% |
| Bad files | Rejected with a user-readable message, batch continues | all |
| Speed / cost / human touch | Seconds per case, AI calls, tokens, documents needing human review | reported |

## 4. Results - full run, 19 Nov 2026 15:26-15:31 (`evaluation/results/results_20261119_153126.json`)

| Metric | Result | Target | |
|---|---|---|---|
| Extraction accuracy | **99.5%** (438 / 440) | 95% | PASS |
| Verdict accuracy | **100%** (21 / 21) | 95% | PASS |
| Check agreement | **100%** (143 / 143) | 95% | PASS |
| Recommendation correct | **100%** (10 / 10) | all | PASS |
| Missing-info recall / precision | **100% / 100%** | 90% | PASS |
| Bad files rejected with message | **2 / 2** | all | PASS |
| Avg processing time per case | **31.7 s** (22-49 s) | - | |
| AI calls | 31 - **0 failed**, 0 repair retries, 2 overloads (503) absorbed by retry | - | |
| Tokens | ≈ 27.8k input / 21.5k output for 10 cases (≈ 2.8k / 2.2k per case) | - | free tier |
| Documents flagged for human check | 2 by design (scanned TC-04, conflict TC-05) | - | |

**Models:** the primary `gemini-2.5-flash` had used its free daily quota during development testing, so the
provider chain answered **29 of 31 calls with `gemini-3.5-flash-lite`**. The numbers therefore describe
Flash-Lite. A comparison run on the primary model after the quota reset is in the next-iteration plan.

### Per case
| Case | Fields | Verdicts | Recommendation | Time |
|---|---|---|---|---|
| TC-01 | 58/58 | 3/3 | ✅ Delta | 45.9 s |
| TC-02 | 43/43 | 2/2 | ✅ Acme | 22.0 s |
| TC-03 | **36/38** | 2/2 | ✅ Cellutech | 26.3 s |
| TC-04 | 43/43 | 2/2 | ✅ Kappa (scanned) | 34.3 s |
| TC-05 | 43/43 | 2/2 | ✅ Acme | 24.9 s |
| TC-06 | 43/43 | 2/2 | ✅ Acme | 27.8 s |
| TC-07 | 43/43 | 2/2 | ✅ Acme | 22.6 s |
| TC-08 | 43/43 | 2/2 | ✅ Acme | 25.2 s |
| TC-09 | 58/58 | 3/3 | ✅ Theta (212.40 incl. 18% = 180.00) | 48.7 s |
| TC-10 | 28/28 | 3/3 (incl. 2 rejections) | ✅ Acme | 39.3 s |

## 5. Failure analysis and before / after

| | Run 1 (15:31) | After fix (16:18) |
|---|---|---|
| TC-03 fields | 36/38 | **38/38** |
| FibreChem price | 210 per kg (AI converted "0.21 per gram") | 0.21 per g (as written) |

**F13** - the AI silently converted units although told not to. Economically right by luck, but invisible
arithmetic outside the tested code. Fixed with a sharper prompt rule plus a **deterministic evidence check**
that flags any price not found in its own source quote (regression tests replay the exact AI output).
One re-run; LLM output varies (F2), so the evidence check remains as the safety net.

Earlier evaluation runs also exposed two problems *in the measurement and infrastructure*:
**F11** (scorer matched checks by exact spelling -> 85.7% reported while the system was right) and
**F12** (per-minute rate limit misread as a daily quota). All 13 failures: [failure_log.md](failure_log.md).

### Re-run during a provider outage (F14)
A second full run on 19 Nov 2026 at 23:01 hit a moment when all three providers were unavailable (daily quota,
503 overload, and a backup with no credit). 5 of 26 AI calls failed, so 5 documents weren't read, and the scores
fell to 57.1% verdicts and 50% recommendations. Values that were read were 96.4% correct. The app marked every
affected comparison as incomplete instead of presenting it as finished. The results are kept in
`evaluation/results/outage_run/` and described in [failure_log.md](failure_log.md#f14---every-ai-provider-unavailable-at-once-during-a-re-run).
The headline results in section 4 come from the 15:26 run, when the providers were available.

### Cost
The evaluation ran on Gemini's free tier, so the actual cost was nothing. At Gemini 2.5 Flash list prices
($0.30 per million input tokens and $2.50 per million output tokens), a three-quote RFQ like TC-01
(3,842 input and 2,729 output tokens, measured) costs about **$0.008**, so under one US cent per RFQ.
From now on every evaluation run reports this per RFQ in `latest.md`.

## 6. Baselines

### 6a. Plain AI, measured (the "just ask ChatGPT" way)

The same 10 cases and the same models, but one plain prompt per RFQ with all the documents pasted in, the way
a buyer would use a chat assistant. No rules, no source lines, no checks. It was scored against the same ground
truth (`python -m evaluation.plain_ai_baseline`, 20 Nov 2026, `evaluation/results/plain_ai_latest.md`).
The test was generous to the chat model: it got clean text for every readable file, including the scan.

| | Plain AI | This system |
|---|---|---|
| Supplier verdict correct | 85.7% (18 of 21) | 100% (21 of 21) |
| Recommendation correct | 90% (9 of 10) | 100% (10 of 10) |
| Price per unit, excl. tax | 100% | 99.5% of all fields |
| Problem quotes flagged in some way | 100% | 100% |
| Every value traceable to its source line | no | yes |

The plain AI was better than I expected: it got every price right and noticed every problem quote. Its three
misses were all judgement calls in the trap cases:

- **TC-09 (a real, costly error).** It took GST out of Theta's tax-inclusive price correctly (180 per kg), then
  still marked Theta as needing clarification because the quote included GST, and recommended Acme at 185.
  On 10,000 kg that is **₹50,000 more** for the same material, with no requirement missed.
- **TC-05.** Sigma's quote gives two purity values (99.8% in the quote, 99.2% in the attached certificate).
  The plain AI picked the lower one and rejected Sigma. That's a reasonable reading, but it settled a
  contradiction on its own and the buyer would never know there was one. The system flags the conflict and asks.
- **TC-08.** It marked an expired quote as not compliant, where the system asks the supplier to re-validate.
  That's a policy difference rather than an error; the point is that the plain AI picks its own policy each time.

What this says: a chat model is a strong reader. Where it falls down is applying a consistent policy and
showing its working. That's what the rules, source lines and evidence check add. The gap is real but small, on
10 clean synthetic cases from one run, so I wouldn't claim more than that.

### 6b. Manual process (estimated, not measured)

**These manual times are an estimate, not a stopwatch measurement.** There wasn't time to time a buyer doing the
cases by hand before the deadline, so I built a simple task-time model from what each case actually contains
(number of quotes, fields per quote, requirements to check, extra work for the trap in each case). The
assumptions are listed so anyone can check them or replace them with real timings in `evaluation/baseline.csv`.

**Assumptions for a buyer working with Excel and a calculator:**

| Task | Time |
|---|---|
| Read the RFQ and list what's required (product, quantity, purity, moisture, delivery limit, certificates) | 3 min |
| Set up a comparison sheet | 2 min |
| Per quote: open and read a one-page quote | 1.5 min |
| Per quote: find and type about 10 values (price, tax, delivery, validity, payment, specs, certificates), ~15 s each | 2.5 min |
| Per quote: put the price on the same unit and tax basis | 0.5 min |
| Per quote: check about 6 requirements, ~10 s each | 1 min |
| Choose a supplier and note why | 2 min |
| Spot a contradiction inside a quote (TC-05) | +2 min |
| Back GST out of a tax-inclusive price (TC-09) | +1 min |
| Write a clarification email to a supplier (TC-05, TC-09) | +3 min each |

With the system, the review time assumes about 1 minute to check the RFQ, about 1 minute per quote to compare
values against their source lines, 1 minute to decide, and half a minute to edit a drafted clarification email.

| Case | Quotes | Manual (estimated) | Manual errors | System processing (measured) | System + human review (estimated) | Time saved |
|---|---|---|---|---|---|---|
| TC-01 | 3 | 24 min | not measured | 45.9 s | 6 min | 75% |
| TC-05 | 2 | 23 min | not measured | 24.9 s | 5 min | 78% |
| TC-09 | 3 | 28 min | not measured | 48.7 s | 6 min | 79% |
| **Average** | | **25 min** | | **40 s** | **5.7 min** | **about 77%** |

Manual error counts are left out on purpose: they can't be estimated honestly without someone doing the work.
What the system run *does* show is that the two traps a tired person is most likely to miss (the conflicting
purity in TC-05 and the unstated tax in TC-09) were both caught.

**Caveat:** the documents are short and clean, which makes the manual times *shorter* than real life. Real
quotes run to several pages, arrive in mixed formats and need more searching, so the real saving is likely larger.
The estimate should be replaced with a real timing as soon as one is available.

Proxy-user end-to-end test in the UI (RFQ-2026-001, 4 suppliers + 1 corrupted file): create + upload ~3 min,
AI processing ~1 min, review to decision ~4 min ([user_feedback.md](user_feedback.md)).

## 7. What the numbers do and do not show
- They show the pipeline is correct end-to-end on representative, edge and failure inputs, that decisions are
  explainable, and that infrastructure failures (quota, overload, bad files) do not corrupt results.
- They do **not** show accuracy on real, messy supplier documents, on languages other than English, or on very
  long multi-product RFQs. Confidence values are the model's own and are not calibrated.

## 8. Reproduce
```bash
python scripts/check_ai.py
python -m evaluation.run_evaluation            # ~6 min, ~35 AI calls
```
