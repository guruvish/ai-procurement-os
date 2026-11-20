# Evaluation report

## 1. What I wanted to find out

Four things. Does the system read the quotes correctly? Does it reach the same verdicts and the same
recommendation a careful buyer would? Does it notice when information is missing? And is it faster than doing
the job by hand? I wanted the answer for ordinary RFQs, for the awkward ones, and for the ones where something
is broken.

## 2. The test set

Ten cases, defined in `evaluation/cases.py`. Running the evaluation turns them into real files in
`evaluation/dataset/`.

| Case | What's in it | Files | What it tests |
|---|---|---|---|
| TC-01 | A normal RFQ with three complete quotes | PDF, Excel and Word | Mixed formats and ranking |
| TC-02 | One supplier writes "price to be confirmed" | PDF | A missing price stays unknown and is never read as 0 |
| TC-03 | One price per tonne, one per gram, quantity in tonnes | PDF | Unit conversion |
| TC-04 | A scanned quote, image only | Image PDF | Reading a scan, and asking a person to check it |
| TC-05 | Purity 99.8% in the quote but 99.2% on the attached certificate | Two-page PDF | Spotting a contradiction |
| TC-06 | No Certificate of Analysis | PDF | Missing documents |
| TC-07 | Delivery in "6 weeks" against a 30-day limit | PDF | A clear rule failure, and weeks to days |
| TC-08 | A quote that has already expired | PDF | Validity dates |
| TC-09 | One price includes 18% GST, one doesn't say | PDF | Tax handling, and a price that can't be compared |
| TC-10 | A damaged PDF and a CSV renamed to .xlsx | Broken files | A clear rejection, while the rest still goes through |

That's 21 quotes, 440 fields and 143 requirement checks. Dates are set relative to the day of the run so the
validity cases don't go stale.

I wrote the correct answers (`ground_truth.json` in each case folder) by hand from the document text. Because
I could get those wrong too, there's a test that feeds the correct answers straight into the scoring as if
they were the AI's output. Everything has to come out at 100%, so if one of my hand-written verdicts
contradicts the rules, the build fails. That's not hypothetical: while writing the cases I got TC-03
FibreChem's verdict wrong. I caught it by reviewing it, and the test now stops it happening again.

The obvious limitation is that I wrote these documents myself. They're short and tidy, and real quotes won't be.

## 3. How it's scored

| Measure | What counts as right | Target |
|---|---|---|
| Fields read correctly | The value matches the correct answer. Numbers must be exact; units, currencies and certificate names count if they mean the same thing | 95% |
| Supplier verdicts | Compliant, needs clarification or not compliant, same as my answer | 95% |
| Requirement checks | Each requirement gets the same result the rules give on the correct answers | 95% |
| Recommendation | The same supplier I'd pick | all 10 |
| Missing information | Of the things that really are missing or unclear, how many get flagged (and how many flags are false alarms) | 90% caught |
| Broken files | Rejected with a message a buyer understands, and the rest carries on | all |
| Speed, cost, human checks | Seconds per case, AI calls, tokens, documents that need a person to look | reported |

## 4. Results

The full run on 19 November, 15:26 to 15:31 (`evaluation/results/results_20261119_153126.json`):

| Measure | Result | Target | |
|---|---|---|---|
| Fields read correctly | **99.5%** (438 of 440) | 95% | met |
| Supplier verdicts | **100%** (21 of 21) | 95% | met |
| Requirement checks | **100%** (143 of 143) | 95% | met |
| Recommendation | **10 of 10** | all | met |
| Missing information caught / false alarms | **100% / none** | 90% | met |
| Broken files rejected with a clear message | **2 of 2** | all | met |
| Time per case | **31.7 seconds** on average (22 to 49) | | |
| AI calls | 31, none failed; two "overloaded" replies were absorbed by a retry | | |
| Tokens | about 2,800 in and 2,200 out per case | | |
| Documents sent to a person to check | 2, both on purpose (the scan in TC-04, the contradiction in TC-05) | | |

One thing to be upfront about: the main model, `gemini-2.5-flash`, had already used up its free daily quota
during development, so 29 of the 31 calls were answered by the backup, `gemini-3.5-flash-lite`. These numbers
describe the backup model. Re-running on the main model is on the list for next time.

| Case | Fields | Verdicts | Recommended | Time |
|---|---|---|---|---|
| TC-01 | 58/58 | 3/3 | Delta ✅ | 45.9 s |
| TC-02 | 43/43 | 2/2 | Acme ✅ | 22.0 s |
| TC-03 | **36/38** | 2/2 | Cellutech ✅ | 26.3 s |
| TC-04 | 43/43 | 2/2 | Kappa, from the scan ✅ | 34.3 s |
| TC-05 | 43/43 | 2/2 | Acme ✅ | 24.9 s |
| TC-06 | 43/43 | 2/2 | Acme ✅ | 27.8 s |
| TC-07 | 43/43 | 2/2 | Acme ✅ | 22.6 s |
| TC-08 | 43/43 | 2/2 | Acme ✅ | 25.2 s |
| TC-09 | 58/58 | 3/3 | Theta (212.40 including 18% GST is 180.00 without) ✅ | 48.7 s |
| TC-10 | 28/28 | 3/3, including both rejections | Acme ✅ | 39.3 s |

## 5. What went wrong, and what changed

The two wrong fields were both in TC-03, and they mattered more than their number suggests.

| | First run (15:31) | After the fix (16:18) |
|---|---|---|
| TC-03 fields | 36/38 | **38/38** |
| FibreChem's price | 210 per kg: the AI converted "0.21 per gram" itself | 0.21 per gram, as written |

The model had been told not to convert units, and did it anyway. The answer happened to be right, but it was
arithmetic nobody could see, done outside the code I'd tested. I tightened the prompt and, more importantly,
added a plain-code check: every price must actually appear in the line the AI quoted it from. If it doesn't,
the quote is flagged for a person to look at. One re-run isn't proof, since AI output varies from run to run,
which is exactly why the check stays in as a safety net. This is failure F13 in the [failure log](failure_log.md).

Earlier runs also showed problems in my measuring rather than in the system. In F11 the scorer reported 85.7%
on checks while the system was actually right, and in F12 a per-minute limit was mistaken for the daily quota.
The failure log covers all 15 failures I hit.

**A run during an outage (F14).** I ran everything again at 23:01 the same night and hit a moment when every AI
service was unavailable at once: the daily quota was gone, the backup was overloaded, and the Claude account had
no credit. 5 of 26 calls failed, so 5 documents were never read, and the scores dropped to 57.1% on verdicts and
50% on recommendations. What was read was still 96.4% right, and the app marked every affected comparison as
incomplete rather than presenting it as finished. That run is kept in `evaluation/results/outage_run/`. The
headline numbers above are from the afternoon run, when the services were up. Since then I've added two free
backup models through OpenRouter.

**Cost.** Everything ran on Gemini's free tier, so it cost nothing. At Gemini 2.5 Flash's list prices ($0.30
per million input tokens, $2.50 per million output), a three-quote RFQ like TC-01 (3,842 tokens in and 2,729
out, measured) works out at about $0.008, so under a cent. Every evaluation run now prints this in `latest.md`.

## 6. Baselines: compared with what?

### 6a. Just asking an AI (measured)

The obvious alternative to my app is pasting everything into a chat assistant, so I measured that. Same 10
cases, same models, but one plain prompt per RFQ with all the documents pasted in, and nothing else: no rules,
no source lines, no checks. It was scored against the same answers (`python -m evaluation.plain_ai_baseline`,
20 November; results in `evaluation/results/plain_ai_latest.md`). I gave it every advantage I could, including
clean text for the scanned quote.

| | Plain AI | My system |
|---|---|---|
| Supplier verdicts | 85.7% (18 of 21) | 100% (21 of 21) |
| Recommendation | 9 of 10 | 10 of 10 |
| Price per unit without tax | 100% | 99.5% of all fields |
| Problem quotes flagged in some way | 100% | 100% |
| Can you see where each number came from? | no | yes |

Honestly, it did better than I expected. It got every price right and noticed every problem quote. Its three
mistakes were all judgement calls in the trap cases:

- **TC-09 is a real, costly mistake.** It took the GST out of Theta's price correctly, getting 180 per kg, then
  marked Theta as needing clarification anyway just because the quote included GST, and recommended Acme at 185.
  On a 10,000 kg order that's ₹50,000 more for the same material, with nothing wrong with Theta.
- **TC-05.** Sigma's quote states two purity values. The chat model went with the lower one and rejected Sigma.
  That's a defensible reading, but it decided a contradiction on its own and the buyer would never have known
  there was one. My system flags the contradiction and asks the supplier.
- **TC-08.** It called an expired quote not compliant, where my system asks the supplier to re-validate it. I'd
  call that a difference in policy rather than an error. The trouble is that the chat model chooses its own
  policy each time.

So a chat model is a good reader. What it doesn't do is apply the same policy every time and show its working,
and that's what the rules, source lines and evidence check add. The gap is real but small, and it comes from one
run on 10 tidy cases, so I wouldn't claim more than that.

### 6b. Doing it by hand (estimated)

**These times are an estimate, not a stopwatch measurement.** I didn't get to time a buyer before the deadline,
so I built the estimate up from what each case actually involves: how many quotes, how many values to type, how
many requirements to check, and the extra work each trap causes. The assumptions are below so anyone can
question them, or replace them with real timings in `evaluation/baseline.csv`.

For a buyer working in Excel with a calculator:

| Task | Time |
|---|---|
| Read the RFQ and note what's required (product, quantity, purity, moisture, delivery, certificates) | 3 min |
| Set up a comparison sheet | 2 min |
| For each quote: open it and read it (one page) | 1.5 min |
| For each quote: find and type about 10 values, at roughly 15 seconds each | 2.5 min |
| For each quote: get the price onto the same unit and tax basis | 0.5 min |
| For each quote: check about 6 requirements | 1 min |
| Pick a supplier and write down why | 2 min |
| Notice a contradiction inside a quote (TC-05) | 2 min extra |
| Take GST out of a price that includes it (TC-09) | 1 min extra |
| Write to a supplier to ask about a gap (TC-05, TC-09) | 3 min extra each |

With the app, I assumed about a minute to check the RFQ, a minute per quote to look over the values and their
source lines, a minute to decide, and half a minute to tidy up a drafted email.

| Case | Quotes | By hand (estimated) | App processing (measured) | App plus checking (estimated) | Time saved |
|---|---|---|---|---|---|
| TC-01 | 3 | 24 min | 46 s | 6 min | 75% |
| TC-05 | 2 | 23 min | 25 s | 5 min | 78% |
| TC-09 | 3 | 28 min | 49 s | 6 min | 79% |
| **Average** | | **25 min** | **40 s** | **5.7 min** | **about 77%** |

I haven't put a number on manual mistakes, because there's no honest way to guess that without someone doing
the work. What I can say is that the system caught both of the traps a tired person is most likely to miss: the
contradiction in TC-05 and the missing tax information in TC-09.

These documents are short and clean, which makes the manual times shorter than they'd be in real life. Real
quotes run to several pages and need more hunting through, so I'd expect the real saving to be bigger. Either
way, a real timing should replace this estimate as soon as there is one.

For comparison, when I went through RFQ-2026-001 in the app as a stand-in user (four quotes and a broken file),
creating it and uploading took about 3 minutes, the reading about a minute, and reviewing through to a decision
about 4 minutes. That's in [user_feedback.md](user_feedback.md).

## 7. What these numbers do and don't show

They show that the whole thing works from start to finish on normal, awkward and broken inputs, that every
decision can be explained, and that problems like quotas, outages and bad files don't quietly corrupt a result.

They don't show how it does on real, messy supplier documents, on anything not in English, or on long RFQs with
many products. The confidence figures come from the model itself and haven't been calibrated.

## 8. Running it yourself

```bash
python scripts/check_ai.py                  # checks each AI service with one tiny request
python -m evaluation.run_evaluation         # the full 10 cases, about 6 minutes and 35 AI calls
python -m evaluation.plain_ai_baseline      # the plain-AI comparison, about 3 minutes and 10 calls
```
