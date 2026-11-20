# Failure Log & Root-Cause Analysis

Real failures observed while building and running the system, with root cause, fix and the
regression test that now guards against each one. Newest at the bottom.

| ID | Date | Where | Severity | Status |
|----|------|-------|----------|--------|
| F1 | 2026-11-19 | Supplier Analyst (Acme quote) | Low - self-recovered | Logging improved |
| F2 | 2026-11-19 | Supplier Analyst (Gamma quote, price missing) | **High** - supplier dropped | Fixed + regression test |
| F3 | 2026-11-19 | Workflow metrics | Medium - misleading metrics | Fixed + regression test |
| F4 | 2026-11-19 | Test environment (pytest 9.2) | Medium - tests could not run | Pinned dependency |
| F5 | 2026-11-19 | Windows antivirus vs pytest | Low - operator friction | Config change |
| F6 | 2026-11-19 | Gemini free tier - HTTP 429 during proxy-user test | **High** - 3 of 4 suppliers not read | Fixed + regression tests |
| F7 | 2026-11-19 | Recommendation on partial data looked complete | **Critical** - could mislead an approver | Fixed + regression test |
| F8 | 2026-11-19 | Gemini 503 "model overloaded" - single provider = single point of failure | **High** - 3 of 4 suppliers not read (again) | Provider chain + regression tests |
| F9 | 2026-11-19 | Configured fallback model retired by Google (404) | Medium - backup silently unusable | Pre-flight check script + new default |
| F10 | 2026-11-19 | Processing killed by a page rerun (user typed during the run) | **High** - status stuck, run button disabled | Background job + resume + regression tests |
| F11 | 2026-11-19 | Evaluation harness under-reported check agreement (85.7%) | Medium - wrong metric, system was right | Harness fixed + regression test |
| F12 | 2026-11-19 | Per-minute 429 misread as "daily quota used up" | Medium - could stop a batch early | Quota-ID based detection + regression test |
| F13 | 2026-11-19 | AI silently converted "INR 0.21 per gram" to 210 per kg | **High** - invisible arithmetic by the AI | Prompt rule + deterministic evidence check + tests |

---

## F1 - First-attempt schema violation, recovered by repair retry
- **Observed:** `supplier_analyst invalid_output attempt=1: ValidationError`, then `status=ok attempts=2`
  (latency 22.6 s instead of ~7 s).
- **Root cause:** unknown - the log only recorded the exception type, not which field failed.
- **Impact:** none on correctness (repair retry worked); ~3x latency and ~2x tokens for that call.
- **Fix:** log now records the failing *field paths* (never values, which may be confidential), e.g.
  `fields=['evidence.unit_price']`, and they are stored in run metrics (`invalid_fields`).
- **Lesson:** observability first - you cannot fix what the logs cannot name. F2 was diagnosed in
  minutes because of this change.

## F2 - Quote with missing price was dropped entirely
- **Observed (try_workflow run, RFQ-DEMO-123537):** Gamma_Quotation.pdf ("Price: to be confirmed")
  failed validation twice: attempt 1 `fields=['evidence.unit_price']`, attempt 2
  `fields=['evidence.currency','evidence.tax_status','evidence.unit_price']` -> ExtractionError ->
  supplier excluded from the comparison.
- **Root cause:** Gemini correctly returned `unit_price: null`, but also `"evidence": {"unit_price": null}`.
  The schema required every evidence entry to be an object. The repair prompt pushed the model to
  "fill" evidence for more null fields, making it worse.
- **Why it matters:** this is exactly the "missing information" case (TC-02) the system exists to
  handle. A missing price must surface as `UNKNOWN`, not make the supplier disappear.
- **Fix (defense in depth):**
  1. Schema: absent value = absent evidence. Null evidence entries are dropped, not rejected;
     null lists become `[]`; confidence `95` is read as `0.95`; unparseable page numbers become `null`.
  2. Prompt: explicit rule "omit evidence keys for null fields"; "to be confirmed / on request" = null price.
- **Regression tests:** `tests/test_llm_regressions.py::test_f2_*` (uses the exact failing shape).
- **Note:** intermittent - the same input passed on the next identical run (temperature 0). LLM output is
  not perfectly deterministic, so the *system* must tolerate variation instead of assuming it away.

## F3 - Failed AI calls disappeared from metrics
- **Observed:** same run reported `ai_repair_retries: 0, invalid_fields: []` although Gamma used 2 attempts.
- **Root cause:** metrics were only returned on success; `ExtractionError` carried no call data.
- **Fix:** `ExtractionError.meta` carries the call's attempts/latency/tokens/invalid fields; the
  workflow records failed calls with `status=failed`; new metric `ai_calls_failed`.
- **Regression test:** `test_f3_failed_call_keeps_its_metrics`.

## F4 - pytest 9.2.0 internal crash
- **Observed:** `INTERNALERROR> AttributeError: 'NodeId' object has no attribute '_str_cache'` before any test ran.
- **Root cause:** incompatibility in the newly released pytest 9.2.0 on Python 3.10.0 (not project code).
- **Fix:** pinned `pytest>=8.0,<9` in requirements.txt.

## F5 - Antivirus flagged pytest as "suspicious activity"
- **Observed:** 360 Total Security blocked `.venv\Scripts\pytest.exe` "creating file link".
- **Root cause:** pytest's `tmp_path` creates a `pytest-current` symlink in the system temp folder.
- **Fix:** `addopts = --basetemp=.pytest_tmp` in pytest.ini (no symlink); documented in the runbook
  because corporate PCs often run similar security software.

## F6 - Rate limiting (HTTP 429) dropped 3 of 4 suppliers
- **Observed (UI proxy-user test, RFQ-2026-001):** RFQ and Acme extracted; Beta, Delta and Gamma failed
  with `Gemini API error 429`. Earlier the same day one 429 was absorbed by the retry (12:42 run).
- **Root cause:** the free tier limits requests per minute and per day. The retry policy (2 s, 4 s) was
  designed for server hiccups, not quota windows of ~60 s, so all retries landed inside the same window.
  429 was treated like any other transient error.
- **Fix:**
  1. 429 handled separately: wait the delay the API asks for (`retry in Ns`, +1 s margin, capped at 65 s),
     up to 3 times; logged as `rate_limit_waits`.
  2. Daily quota detected (`PerDay` quota id): no pointless waiting - switch to `GEMINI_FALLBACK_MODEL`;
     if that is exhausted too, stop calling the API, mark remaining documents *pending* with a clear message.
  3. Client-side throttle: minimum gap between calls (`GEMINI_MIN_INTERVAL_S`, default 4 s).
  4. UI: one-click "Read the N remaining documents" - already-read documents are reused, no extra AI cost.
- **Regression tests:** `test_f6_*` (per-minute wait, daily-quota fallback, all-models-exhausted) and
  `test_daily_quota_stops_calls_and_marks_comparison_incomplete`, `test_rerun_after_quota_reset_only_reads_missing_documents`.

## F7 - A recommendation built on partial data looked complete
- **Observed:** after F6, the app recommended Acme with "0 not compliant, 0 need clarification" - true for
  the 1 supplier it saw, but Delta (cheaper, compliant) had never been read. An approver could not tell.
- **Root cause:** `recommend()` only sees evaluated suppliers; nothing compared that list with the uploads.
- **Fix:** the workflow now lists unread quotations; the explanation starts with
  `INCOMPLETE - N quotation(s) could not be read and are NOT included: ...`; Compare and Decision tabs show a
  red banner; approving an incomplete comparison requires an explicit confirmation **and** a comment.
- **Lesson:** "silent partial success" is more dangerous than a crash. Completeness is part of correctness.

## F8 - Provider outage: Gemini returned 503 "model is overloaded"
- **Observed (13:31 re-run of RFQ-2026-001):** all three remaining quotations failed with `Gemini API error 503`
  after 2 retries each (plus two 429 waits of 21 s and 60 s). Run time 128 s, 0 documents read.
- **Root cause:** the F6 fix added a fallback model only for the *daily-quota* case. A provider-side overload
  (503) or a long per-minute limit still had no alternative, so the whole system depended on one model
  being healthy - a single point of failure. Waiting 60 s for a 429 also made the user wait for nothing.
- **Fix - provider chain:** Gemini primary -> Gemini fallback model -> optional OpenAI-compatible backups
  (OpenAI, Groq, OpenRouter, local Ollama) configured in `.env`. A backend that is overloaded (after one
  quick retry), rate-limited for more than 10 s, out of quota, unreachable, or misconfigured is skipped.
  Every backend's output goes through the same Pydantic contract. Scanned PDFs stay on Gemini (vision).
  The answering backend is recorded per call (`model`) and shown in the UI ("Answered by ...").
- **Trade-offs:** (1) every enabled provider receives the documents - backups are opt-in and documented
  as a privacy decision; (2) different models extract differently - the evaluation set should be re-run per
  provider before trusting it; (3) rotating several free keys of one provider to dodge limits was rejected:
  it breaks provider terms and only hides the capacity problem.
- **Regression tests:** `test_f8_overloaded_primary_falls_back_after_one_quick_retry`,
  `test_f8_openai_compatible_backup_answers_when_gemini_is_down`, `test_f6_long_per_minute_limit_moves_to_backup_instead_of_waiting`,
  `test_scanned_pdfs_are_never_sent_to_text_only_backups`, `test_all_backends_down_gives_actionable_message`.

## F9 - Fallback model retired by the provider
- **Observed:** `scripts/check_ai.py` -> `gemini-2.5-flash-lite: 404 ... no longer available to new users`.
  The model was valid when the code was written and still appeared in the model list.
- **Root cause:** model IDs are external, versioned dependencies. A backup that is never exercised can be
  broken for weeks without anyone noticing - until the day it is needed.
- **Fix:** `scripts/check_ai.py` sends a tiny request to every configured backend (and lists the Claude
  model IDs the key can use). It is now a step in the runbook: run it after changing `.env` and before
  every demo. Default fallback changed to the pinned, non-preview `gemini-3.5-flash-lite`.
  `-latest` aliases and `-preview` models were rejected: they change behaviour without notice, which would
  make evaluation results irreproducible.

## F10 - Processing interrupted by a page rerun
- **Observed (13:57 run of RFQ-2026-001):** the user typed in the sidebar while processing ran. All three
  documents were extracted, but the status stayed `EXTRACTING`; the run button was disabled and the header
  said "The AI is reading the documents" forever.
- **Root cause:** in Streamlit every widget interaction re-runs the page script and stops the current run.
  The 60-second processing ran *inside* the page script, so it was killed between extraction and evaluation.
- **Fix:**
  1. Processing runs in a background job (thread); the page only *shows* progress (auto-refresh every 2 s),
     so clicks, typing and tab switches no longer affect it. One job per request (double start rejected).
  2. Interrupted runs are detected (`status = processing` but no job running) -> header shows "Interrupted",
     button becomes **Resume processing**; extractions already done are reused.
- **Regression tests:** `test_background_job_finishes_and_keeps_its_progress_log`,
  `test_interrupted_run_is_detected_and_can_be_resumed`, `test_same_request_cannot_be_processed_twice_at_once`.
- **Limitation:** jobs live in the app process. If the app itself is stopped mid-run, the run is marked
  interrupted and resumed manually - acceptable for a single-user MVP; a job queue is in the next-iteration plan.

## F11 - The measurement was wrong, not the system
- **Observed (first evaluation run, TC-01 + TC-04):** extraction 100% (101/101 fields), verdicts 100%,
  recommendations 100% - but requirement-check agreement only 85.7% (30/35).
- **Root cause:** the scorer matched checks by exact name. The AI wrote the RFQ certificate as "GMP Certificate",
  the ground truth says "GMP certificate"; the check names differed only in spelling, so 5 checks (one per
  supplier) were counted as missing. The application itself matches certificates by meaning - the scorer did not.
  The offline harness test did not catch it because there the names were identical.
- **Fix:** the scorer matches checks the same way the engine does (certificate aliases, related spec names).
  Regression test with differently spelled certificate names. `--report-only` rebuilds reports without AI calls.
- **Lesson:** validate the evaluator, not only the system. A metric that disagrees with the metrics it is
  derived from (100% fields + 100% verdicts, but 85.7% checks) is a signal to inspect the measurement first.

## F12 - Per-minute rate limit misread as a daily quota
- **Observed:** `gemini-2.5-flash unavailable: daily quota used up`, yet the very next call to the same model
  succeeded. The fallback model answered, so nothing failed - but if both models were misread the whole batch
  would have stopped with "daily quota used up".
- **Root cause:** detection looked for words like "daily"/"PerDay" anywhere in Google's 429 message, which
  can describe several quotas at once.
- **Fix:** read the violated `quotaId`s; only skip a model for the day when *all* violated quotas are daily.
  The quota IDs are now logged, so the next occurrence is diagnosable from the log alone.
- **Regression test:** `test_f12_per_minute_limit_is_not_mistaken_for_daily_quota`.

## F13 - The AI silently did a unit conversion it was told not to do
- **Observed (full evaluation run, TC-03, gemini-3.5-flash-lite):** only 2 of 440 fields wrong:
  FibreChem `unit_price` expected 0.21, got **210.0**; `price_per` expected g, got **kg**.
  Source text: "Price: INR 0.21 per gram, GST 12% extra".
- **Why it matters although the verdict was right:** 0.21/g x 1000 = 210/kg, so total cost, verdict and
  recommendation were correct - by luck. The prompt says "do not convert"; the design keeps all arithmetic in
  tested Python. An AI that converts once can convert wrongly next time (21 or 2,100 per kg), and the stored
  value no longer matches its evidence, so a reviewer cannot verify it. Without the evaluation harness this
  would never have been noticed.
- **Root cause:** the instruction "Do not convert" was a short clause at the end of a rule; the model applied
  its own "helpful" normalisation toward the RFQ unit (kg), which the prompt also mentions.
- **Fix (two layers):**
  1. Prompt: "the number EXACTLY as written ... NEVER convert", with this exact case as an example.
  2. **Deterministic evidence check** (`app/services/verification.py`): the extracted price must appear in the
     AI's own quoted source text. If not, the quotation is flagged (HIGH finding, price = REVIEW_REQUIRED,
     supplier = NEEDS_CLARIFICATION) until a human corrects or confirms it - the confirmation is audited.
     This catches the whole class (conversions, misread digits, invented numbers), not only this case.
- **Trade-off:** a false alarm costs a reviewer ~30 seconds; a silent wrong price costs money. Indian number
  formats ("1,95,000") are handled so they do not cause false alarms.
- **Regression tests:** `tests/test_verification.py` (replays the exact AI output from TC-03).
- **Re-run:** `python -m evaluation.run_evaluation --cases TC-03` -> see evaluation/results/latest_TC-03.md.

## F14 - Every AI provider unavailable at once during a re-run
- **Observed (full evaluation re-run, 19 Nov 2026 23:01-23:09, `evaluation/results/outage_run/`):** the main model's
  free daily quota ran out after two calls (429), the fallback `gemini-3.5-flash-lite` returned 503 "overloaded"
  repeatedly, and the Claude backup returned 400 because the account has no credit. 5 of 26 AI calls failed, so
  5 documents were never read (two RFQs, three quotations).
- **Effect on the scores:** the harness counts an unread document as wrong, so verdict accuracy fell to 57.1% and
  recommendations to 50%. Values that *were* read were 96.4% correct, in line with the earlier run.
- **What the product did:** the right thing. Every affected comparison was marked incomplete, and approving one
  needs an explicit confirmation (the F7 safeguard). Nothing wrong was presented as complete.
- **Root cause:** the fallback chain only helps if at least one provider is working. On free tiers, all of them
  can be down at the same time, and the backup chain had one provider without credit.
- **What I changed:** nothing in the code. I kept this run as evidence, moved it to its own folder so it isn't
  mistaken for the headline result, and removed the Claude backup from `AI_PROVIDER_ORDER` until it has credit.
- **What would fix it properly:** a paid tier or a second working provider, and retrying failed documents once
  after a pause before giving up. The user can already do this with *Read the remaining documents*.

## F15 - The tests failed on a fresh copy of the repository
- **Observed (review against the brief, 20 Nov 2026):** on a new clone with no `.env`, `pytest` stopped at the first
  import with "No AI key found", so none of the tests ran. On my machine they passed only because `.env` existed.
- **Root cause:** the startup check that refuses to run without an AI key is right for the app, but the tests import
  the same configuration, and they never call an AI service.
- **Fix:** `tests/conftest.py` gives the tests a placeholder key when no `.env` exists. The app itself still refuses
  to start without a real key.
- **Lesson:** "it works on my machine" isn't reproducibility. A reviewer's first step is a fresh clone, so that's
  how it should be tested.
