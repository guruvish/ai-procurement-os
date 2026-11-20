# Case study: RFQ Evaluator

*Built by Kavuturu Guru Vishnu during the 5-day remote AI OS sprint, with Python, Streamlit, LangGraph,
Gemini and SQLite.*

## The person and the problem

The user I had in mind is a procurement executive at a mid-sized pharmaceutical manufacturer. They send RFQs
for raw materials such as APIs and excipients, and each one brings back three to six quotes in whatever format
the supplier likes: PDF, Excel, Word, and occasionally a scan.
I didn't interview a buyer for this sprint. The user and their workflow are based on how RFQ comparison is
commonly done, and all the documents are synthetic ones I created for testing.

The job comes round with every RFQ: take a pile of quotes that all look different and turn them into a supplier
choice that's fair and that you can defend afterwards.

Done by hand, it goes like this. You read each quote, and every supplier lays theirs out differently. You
retype the price, tax, delivery time, validity, specs and certificates into Excel, which is slow and invites
typos. You convert per-gram prices to per-kilo, take GST out and check the currency on a calculator, and that
working rarely gets written down. You check each mandatory requirement by eye, which is where things slip,
because a quote that simply doesn't mention something looks the same as one that complies. Then you chase
the gaps with one-off emails, and justify the final choice from memory and a spreadsheet.

### The workflow today, step by step

| | Today, by hand | With RFQ Evaluator |
|---|---|---|
| **Trigger** | Quotes come back by email after an RFQ goes out, usually 3 to 6 per RFQ, for every purchase | Same |
| **Input** | The RFQ plus quotes as PDF, Excel, Word, sometimes scans, each laid out differently | The same files, uploaded together |
| **Judgment** | Which values matter, whether a quote meets each requirement, what "not mentioned" means | The AI reads; fixed rules judge each requirement; "not stated" is never a pass |
| **Tool** | Email, a PDF reader, Excel, a calculator | The app (AI model, rule engine, SQLite) |
| **Approval** | Buyer, sometimes with a manager, often justified from memory | Buyer approves in the app under their name; a note is required for exceptions |
| **Output** | An Excel comparison and an email saying who won | Recommendation, PDF and Excel report, clarification emails, audit log |
| **Exception** | A missing price, a contradiction or an unreadable file means emails back and forth, or gets missed | Flagged on screen with a drafted email; unreadable files are named straight away |

Baseline: by a task-time estimate (not a stopwatch measurement), comparing three quotes by hand takes a buyer
about 23 to 28 minutes per RFQ, against about 6 minutes with the system including review. The assumptions
are in [evaluation_report.md §6](evaluation_report.md).

## What I built, and what I left out

The app covers the whole path: upload, AI extraction with a source line for every value, a rule-based
evaluation, a review step where people correct the values, the decision, and a PDF and Excel report. There's
an analytics page on top.

With about two days of the five left, I dropped a few things on purpose and wrote down why: a separate FastAPI
layer (Streamlit calls the services directly), Tesseract OCR (Gemini can read scans itself), importing from
Google Drive, and user logins. Purchase orders, ERP integration, payments, supplier onboarding, negotiation and
any kind of automatic approval were never in scope.

## The main design choice

The rule I kept coming back to was that the AI reads, the rules decide, and a person approves.

The model's only job is to fill in a fixed form and quote the line each value came from. Everything after that
is ordinary, tested Python: unit and tax conversion, the requirement checks, the verdicts and the
recommendation. That means the same quotes always give the same answer, every verdict has a written reason, and
a cheap quote can't hide a failed must-have. A quote that's silent on a requirement is never counted as meeting it.

The trade-offs I made along the way (more in [architecture.md](architecture.md)):

- **Fixed rules over a weighted AI score.** A clever ranking is hard to defend in front of an auditor. The
  scorecard shows the real figures and nothing else.
- **A chain of models over a single one.** Gemini first, then Gemini Flash-Lite, then Claude or an
  OpenAI-compatible model if set up. It's more moving parts, and each extra provider is another company that
  sees the documents, so they're all optional.
- **One process over a separate API.** Streamlit and the services run together, with the LangGraph workflow in
  a background job. Fine for one user, not for a team.
- **Approval outside the workflow.** Approving is a separate, logged action a person takes, not a step the
  graph can reach on its own.

## What the AI does and what stays with people

At runtime, Gemini reads the documents (scans included), works out that "assay" means purity and "LOD" means
moisture, quotes the source line for each value, and points out where a document contradicts itself.

People correct the values (every correction is logged), choose the supplier, approve or reject, explain
themselves when they pick a supplier that doesn't qualify or approve with quotes missing, and send the
clarification emails.

Everything in between, the evidence check, normalisation, compliance and ranking, is deterministic code.

## Results

Across 10 test RFQs with 21 quotes:

| What was measured | Result | Target |
|---|---|---|
| Fields read correctly | 99.5% (438 of 440); TC-03 later fixed to 38 of 38 | 95% |
| Supplier verdicts | 100% (21 of 21) | 95% |
| Recommendations | 100% (10 of 10) | |
| Missing information caught, and false alarms avoided | 100% and 100% | 90% |
| Broken files rejected with a clear message | 2 of 2 | all |
| Processing time | 31.7 seconds per RFQ on average | |
| Time saved compared with doing it by hand | about 77% (estimated: 25 min down to 5.7 min) | at least half |

In a walkthrough with a stand-in user, a full RFQ with four suppliers and one broken file went from upload to
an approved decision in about eight minutes, review included. I noted 13 things that confused or slowed them
down and changed something for each ([user_feedback.md](user_feedback.md)).

## What went wrong, and what I learned

I logged 13 real failures, each with its cause, the fix and a test that would catch it again
([failure_log.md](failure_log.md)). These five taught me the most.

**A partial result that looked complete (F7).** After a rate-limit error, three of the four quotes were missing,
yet the screen still recommended a supplier and showed "0 not compliant". Incomplete comparisons are now
labelled as such, and approving one needs an explicit confirmation. Completeness turned out to be part of
being correct.

**Relying on one provider (F6, F8, F12).** Free-tier rate limits and a 503 "overloaded" error quietly dropped
suppliers from the comparison. I added a chain of models that moves past a busy one within seconds, and I tell
daily and per-minute quota errors apart using the quota IDs Google sends back. In the final run, none of the
31 AI calls failed, even though the main model had run out of quota.

**The model doing sums it was told not to (F13).** "INR 0.21 per gram" came back as 210 per kilo. Right by
luck, but invisible and impossible to trace. I tightened the prompt and added an evidence check in plain code:
every price has to appear in the line it was quoted from. TC-03 went from 36 of 38 to 38 of 38.

**My own measuring was off (F11).** Every field was right, but "check agreement" came out at 85.7%, because
the scorer compared requirement names letter by letter. Now I test the scorer as well as the system.

**The interface stopping its own work (F10).** Typing into a box while documents were being read reloaded the
page and killed the run. Processing now runs in the background, shows live progress, and can pick up where it
left off.

## Limitations

The test documents are clean, synthetic ones I wrote alongside the answers, so real quotes will score lower.
Most of the evaluation was answered by `gemini-3.5-flash-lite`. It only handles English, it's a single-user
app on one machine, and the model's confidence numbers aren't calibrated. The manual baseline is an
estimate rather than a measurement. The Google Sheets export is built
and tested against a fake client, but it hasn't been verified against a live Google Sheet.

## The next two weeks

The app already records what I'd want to watch (on the Analytics page, in the `runs` table and in the audit
log): evaluations per week, how many RFQs get through without a re-upload, corrections per evaluation (a rough
measure of how well it reads real documents), how often the recommendation is accepted, time from upload to
decision, how often the evidence check fires, and failed AI calls.

In the first week I'd run it on 10 to 20 real, anonymised RFQs with a buyer, turn every correction they make
into a new test case, compare `gemini-2.5-flash` with Flash-Lite on the full evaluation, and stop retrying
models that have run out of quota.

In the second week I'd extend the evidence check to delivery, validity and specs, support RFQs with several
products, and add a FastAPI layer with logins so a team could share it. Google Drive import would come after that.

## Links

Repository: `[FILL]`. Demo video: `[FILL]`.
See also the [evaluation report](evaluation_report.md), the [AI collaboration note](ai_collaboration_note.md),
the [user guide](user_guide.md) and the [operator runbook](operator_runbook.md).
