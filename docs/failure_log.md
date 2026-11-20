# Failure log

Everything that actually went wrong while I built, tested and ran this, in the order it happened. For each one:
what I saw, why it happened, what I changed, and the test that now catches it if it comes back.

| # | What went wrong | How bad | Where it ended up |
|---|---|---|---|
| F1 | The AI's first answer didn't fit the form; a retry fixed it | Minor, fixed itself | Better logging |
| F2 | A quote with no price was dropped from the comparison | Serious | Fixed, with a test |
| F3 | Failed AI calls vanished from the run statistics | Moderate | Fixed, with a test |
| F4 | A new pytest release crashed before any test ran | Moderate | Version pinned |
| F5 | The antivirus blocked pytest | Minor | Setting changed |
| F6 | Rate limits stopped 3 of 4 quotes from being read | Serious | Fixed, with tests |
| F7 | A recommendation built on partial data looked complete | Critical | Fixed, with a test |
| F8 | Gemini was overloaded, and with one provider there was no plan B | Serious | Backup providers, with tests |
| F9 | Google retired the backup model | Moderate | Check script and a new default |
| F10 | Typing during a run killed the processing | Serious | Background processing, with tests |
| F11 | My scorer was wrong, not the system | Moderate | Scorer fixed, with a test |
| F12 | A per-minute limit was mistaken for the daily quota | Moderate | Fixed, with a test |
| F13 | The AI converted a price it was told to leave alone | Serious | Prompt and evidence check, with tests |
| F14 | Every AI service was down at the same time | Serious | Documented; more backups added |
| F15 | The tests failed on a fresh copy of the repository | Moderate | Fixed |

All of these happened on 19 or 20 November 2026.

---

## F1. The AI's first answer didn't fit the form

The log showed `invalid_output attempt=1`, then success on the second attempt, with that call taking 22.6
seconds instead of the usual 7. The retry worked, so nothing was wrong in the result, but the call cost three
times as long and twice the tokens.

The real problem was that I couldn't tell *why* it failed, because the log only recorded the type of error. Now
it records which fields failed (never their values, since those may be confidential), for example
`fields=['evidence.unit_price']`, and keeps them in the run statistics. That small change is what let me work
out F2 in a few minutes.

## F2. A quote with no price was dropped from the comparison

Gamma's quote says "Price: to be confirmed". The AI failed on it twice, the second time worse than the first,
and the workflow gave up and left Gamma out of the comparison completely.

The AI had done the right thing by returning no price. But it also returned an empty source entry for that price,
and my form insisted every source entry be filled in. The retry message then nudged it to fill in *more* empty
entries, which made things worse. That stung, because a missing price is exactly the situation (TC-02) the
system is meant to handle: it should show up as "unknown", not make the supplier disappear.

I fixed it in two places. The form now treats "no value" as "no source needed" and quietly tidies up similar
slips, such as an empty list, a confidence of 95 meaning 0.95, or a page number it can't read. The prompt now
says to leave out source entries for empty fields, and that "to be confirmed" or "on request" means no price.
`tests/test_llm_regressions.py` replays the exact answer that failed.

Worth noting: the same file went through fine on the next identical run. AI output isn't perfectly repeatable
even at temperature 0, so the system has to cope with variation instead of assuming it away.

## F3. Failed AI calls vanished from the run statistics

The same run reported no retries, although Gamma had taken two attempts. The statistics were only recorded when
a call succeeded, so failures left no trace. A failed call now keeps its attempts, timing and tokens, it's
recorded as failed, and there's a new count of failed calls. Test: `test_f3_failed_call_keeps_its_metrics`.

## F4. A new pytest release crashed before any test ran

The newest pytest, 9.2.0, crashed with an internal error on Python 3.10 before running a single test. It wasn't my code. I pinned `pytest>=8.0,<9` in `requirements.txt`.

## F5. The antivirus blocked pytest

360 Total Security flagged pytest as suspicious because it creates a shortcut-style link in the system temp
folder. I set pytest to use a temp folder inside the project instead (`--basetemp=.pytest_tmp` in
`pytest.ini`), which doesn't need the link. It's in the runbook too, because company laptops often run
similar software.

## F6. Rate limits stopped 3 of 4 quotes from being read

During my first run-through as a stand-in user, the RFQ and Acme's quote were read, then Beta, Delta and Gamma
all failed with error 429, "too many requests".

The free tier limits requests per minute and per day. My retry waited 2 and then 4 seconds, which is fine for a
brief hiccup but useless against a limit that resets after about a minute, so every retry landed in the same
blocked window. I'd treated a rate limit like any other passing error.

Now a rate limit is handled on its own terms. The app waits as long as Google asks (up to 65 seconds, at most
three times) and logs each wait. If the *daily* quota is gone, it doesn't wait at all; it switches to the backup
model, and if that's out too, it stops and marks the remaining documents as waiting with a clear message. There's
also a minimum gap between calls (4 seconds by default). In the app, the run button becomes "Read the N remaining
documents", and anything already read is reused at no extra cost. Tests: the `test_f6_` group, plus two
workflow tests for the daily-quota case and for re-running after the quota resets.

## F7. A recommendation built on partial data looked complete

This was the worst one. After F6, the app recommended Acme with "0 not compliant, 0 need clarification". That
was true for the one supplier it had seen, but Delta, which was cheaper and compliant, had never been read. Someone
approving it would have had no way to tell.

The recommendation only looked at the suppliers that had been evaluated, and nothing compared that list with
what had been uploaded. Now the workflow keeps track of unread quotes, the explanation starts with "INCOMPLETE",
the Compare and Decision tabs show a red warning, and approving an incomplete comparison needs a ticked
confirmation and a written note.

A partial result that looks complete is more dangerous than a crash. Completeness is part of being correct.

## F8. Gemini was overloaded, and with one provider there was no plan B

Re-running the same RFQ at 13:31, all three remaining quotes failed with error 503, "model overloaded", after two
retries each. Two rate-limit waits of 21 and 60 seconds came on top. It took 128 seconds and read nothing.

The F6 fix only added a backup model for the daily-quota case. When Google was overloaded there was still nowhere
else to go, so the whole system depended on one model being healthy.

I added a chain of providers: Gemini, then a second Gemini model, then any OpenAI-compatible service set up in
`.env` (OpenAI, Groq, OpenRouter or a local Ollama). Claude can be added too. A provider that's overloaded after
one quick retry, rate-limited for more than 10 seconds, out of quota, unreachable or misconfigured gets skipped.
Every provider's answer goes through the same form check, scanned PDFs only go to models that can read images,
and the app shows which model answered.

There are trade-offs. Every provider you switch on sees your documents, so backups are opt-in and the privacy
side is written down. Different models read differently, so the evaluation should be re-run before trusting a
new one. I also considered rotating several free Gemini keys to get around the limits, and decided against it:
it breaks Google's terms and just hides the capacity problem. Five tests cover the chain.

## F9. Google retired the backup model

My new check script reported that `gemini-2.5-flash-lite` was "no longer available to new users". It had been fine
when I wrote the code and still showed up in the model list.

Model names are outside dependencies that can change under you, and a backup that's never used can be broken for
weeks without anyone noticing, right up until the day you need it. `scripts/check_ai.py` now sends a tiny request
to every configured model, and the runbook says to run it after changing `.env` and before any demo. I made
`gemini-3.5-flash-lite` the default backup. I avoided "-latest" and "-preview" model names on purpose, because they
can change without warning, and then evaluation results can't be reproduced.

## F10. Typing during a run killed the processing

At 13:57 I typed my name in the sidebar while documents were being read. All three were read, but the status
stayed on "reading" forever, the run button stayed greyed out, and nothing finished.

In Streamlit, every click or keystroke reruns the page script and stops whatever it was doing. The processing ran
inside that script, so my typing killed it halfway between reading and comparing.

Processing now runs in the background, and the page just shows its progress, refreshing every two seconds.
Clicking, typing and switching tabs no longer affect it, and the same RFQ can't be started twice at once. If a run
does get interrupted, the app notices, and the button becomes "Resume processing", reusing whatever was already
read. Three tests cover this. One limitation remains: the background job lives inside the app, so if you close the
app mid-run, you resume by hand. That's fine for one user, and a proper job queue is in the plan.

## F11. My scorer was wrong, not the system

The first evaluation run showed 100% on fields, 100% on verdicts and 100% on recommendations, but only 85.7% on
requirement checks. Those numbers can't all be true at once.

My scorer matched requirements by their exact name. The AI wrote "GMP Certificate"; my answer key said "GMP
certificate". The app treats those as the same thing, but the scorer didn't, so five checks were counted as
missing. My offline test of the scorer hadn't caught it, because there the names were spelled identically.

The scorer now matches requirements the same way the app does, there's a test with differently spelled names,
and `--report-only` rebuilds the report without calling the AI again. The lesson: test the thing doing the
measuring, not only the thing being measured. When one number disagrees with the numbers it's built from, check
the measurement first.

## F12. A per-minute limit was mistaken for the daily quota

The log said the main model's daily quota was used up, and then the very next call to that model worked. Nothing
broke, because the backup answered, but if both models had been misjudged like that, the whole batch would have
stopped for the day for no reason.

I'd been looking for words like "daily" anywhere in Google's error message, and one message can mention several
limits at once. Now the app reads the exact quota IDs Google sends, and only gives up on a model for the day when
every limit it hit is a daily one. The IDs are logged, so the next surprise can be explained from the log alone.
Test: `test_f12_per_minute_limit_is_not_mistaken_for_daily_quota`.

## F13. The AI converted a price it was told to leave alone

In the full evaluation, only 2 of 440 fields were wrong, both in TC-03. FibreChem's quote says "INR 0.21 per gram,
GST 12% extra". The AI stored it as 210 per kg.

The verdict was still right, since 0.21 per gram really is 210 per kg, but only by luck. The whole design keeps
arithmetic in tested code, and the prompt said not to convert. A model that converts once can convert wrongly the
next time (21 or 2,100 per kg), and the stored number no longer matches the line it supposedly came from, so a
reviewer can't check it. Without the evaluation I'd never have noticed. The "don't convert" instruction was a short
clause tacked onto another rule, and the prompt also mentions the RFQ's unit, which seems to have encouraged the
model to be helpful.

I fixed it at two levels. The prompt now says to copy the number exactly as written and never convert it, using
this exact case as the example. More importantly, there's a plain-code check (`app/services/verification.py`):
the price has to appear in the text the AI quoted as its source. If it doesn't, the quote is flagged, the price is
marked for review, and the supplier goes to "needs clarification" until someone corrects or confirms it, and that
confirmation is logged. This catches the whole family of problems, such as conversions, misread digits and
invented numbers, not just this one case. A false alarm costs a reviewer half a minute; a wrong price nobody sees
costs money. Indian number formats like "1,95,000" are understood, so they don't trigger false alarms.
`tests/test_verification.py` replays the exact answer from TC-03, and a re-run brought TC-03 to 38 of 38.

## F14. Every AI service was down at the same time

I re-ran the full evaluation at 23:01 that night, and everything was unavailable at once: the main model's daily
quota ran out after two calls, the backup kept answering "overloaded", and the Claude backup refused because the
account had no credit. 5 of 26 calls failed, so two RFQs and three quotes were never read.

The scorer counts an unread document as wrong, so verdicts fell to 57.1% and recommendations to 50%. What *was*
read was 96.4% right, in line with the earlier run. The app behaved properly: every affected comparison was marked
incomplete, and approving one needs the confirmation from F7. Nothing wrong was shown as finished.

A chain of backups only helps if at least one link works, and on free tiers they can all fail together. I kept this
run as evidence in `evaluation/results/outage_run/`, so nobody mistakes it for the headline result, and took Claude
out of the provider order until it has credit. Later that night I added two free models through OpenRouter as extra
backups, and both answered in the check script. A paid tier would fix this properly, along with retrying a failed
document once after a pause. In the app you can already do that by hand with "Read the remaining documents".

## F15. The tests failed on a fresh copy of the repository

Going through the brief again, I realised I'd only ever run the tests on my own machine. On a fresh copy with no
`.env` file, pytest stops at the first import with "No AI key found", so no tests run at all.

The app is right to refuse to start without a key, but the tests load the same settings and never call an AI
service. `tests/conftest.py` now gives them a placeholder key when there's no `.env`. The app itself still needs a
real one.

"It works on my machine" isn't the same as reproducible. A reviewer's first step is a fresh copy, so that's how it
needs testing.
