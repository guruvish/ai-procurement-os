# AI collaboration note

This project was built with a lot of help from AI, and it also uses AI inside the product. This note covers which
tools I used and for what, how I checked their work, what I threw out or had corrected, and which decisions were mine.

## 1. The tools and what each one did

| Tool | What I used it for |
|---|---|
| **Claude** (claude.ai, Claude Opus 5.5) | My pair-engineer for the whole build. It proposed the scope and architecture, wrote the application code, the tests and the evaluation harness, created the synthetic test cases and their answer keys, and drafted the documentation. It sent each step to me as a patch script, which I ran on my machine; the script backs up every file before replacing it |
| **Google Gemini API** (`gemini-2.5-flash`, `gemini-3.5-flash-lite`) | Part of the product itself. It reads the RFQ and the quotes, scans included, and fills a fixed form, quoting the line each value came from |
| **OpenRouter** (two free models) | Backups inside the product, added after an outage, in case both Gemini models are unavailable |
| **Anthropic Claude API** (`claude-haiku-5-5`) | Set up as another backup, but never used, because the account has no credit |

## 2. What I handed to AI

- Writing the code for every part of the app, the 90 automated tests and the evaluation harness.
- Creating the 10 test cases and their correct answers, the sample documents, and the illustration on the
  dashboard (drawn in code).
- Working out what had gone wrong from my terminal output and screenshots, and suggesting fixes.
- The plain-AI comparison: Claude wrote the script that runs the same cases through one plain prompt. I ran it,
  and Claude wrote up the results from the output.
- Estimating the manual time. I didn't have time to time myself doing the cases by hand, so Claude built an
  estimate with its assumptions spelled out. It's labelled as an estimate everywhere it appears.
- First drafts of every document, this one included.
- Near the end, at my request, a second pass on the look and the wording: a new colour scheme and fonts, the Back
  button, pages opening at the top, and rewriting the on-screen text and all the documents in plainer language.
  The facts and figures didn't change.

## 3. How I checked the AI's work

1. **I ran everything myself, every step.** I applied each patch, ran the tests (5 at the start, 90 by the end)
   and pasted the output back. Nothing went in because it "should work".
2. **I checked the extraction by hand** against the documents in the early runs. For example, at step 6 I checked
   that purity and moisture were marked as must-haves, "Rs." became INR, "GST 18% extra" was read as tax not
   included, "3 weeks" became 21 days, and the validity date was right.
3. **I used the app as a stand-in buyer** in the browser, from upload to decision, and reported every point where
   I got stuck, with screenshots. That came to 14 issues, each of which led to a change
   ([user_feedback.md](user_feedback.md)).
4. **I measured it against the answer keys** with the evaluation harness, and questioned results that didn't add
   up. When fields and verdicts were at 100% but checks were at 85.7%, the measurement turned out to be wrong (F11).
5. **I looked at the output.** I opened the PDFs and looked at the screens before accepting them.
6. **I compared it with plain AI.** I ran the same cases through a plain prompt, so the system's numbers have
   something to be measured against.

Claude also tested each patch in its own environment before sending it, using stand-ins for libraries it didn't
have, and said whenever something could only be tested on my machine.

## 4. What I rejected, or what had to be corrected

| What came out | What was wrong | What happened |
|---|---|---|
| "Edit this line" instructions | Easy to get wrong when applying them by hand | I asked for one downloadable patch per step instead |
| Balloons when a decision was approved | Wrong tone for a business tool | Replaced with a calm "decision recorded" card |
| Circled numbers on the tabs | Looked amateurish | Icons instead |
| The first version of the on-screen text and docs | Read as stiff and machine-written, with arrows, strings of fragments and jargon like "normalised" | Rewritten in plain language, from the buyer's side |
| A purple gradient design | Generic | Navy and teal, with the Bricolage Grotesque and IBM Plex Sans fonts |
| Navigation | No way back, and pages opened scrolled halfway down | A Back button, and every page opens at the top |
| `gemini-2.5-flash-lite` as the backup model | Google had retired it for new users | The check script caught it; switched to `gemini-3.5-flash-lite` (F9) |
| The evaluation scorer | Compared requirement names letter by letter, so the score was wrong | Fixed, with a test (F11) |
| The theme's CSS | Broke Streamlit's icons, which showed up as text like "keyboard_double_arrow_left" | Fixed |
| Processing inside the page | Any click during a run killed it (F10) | Moved to the background, with Resume |
| Quota detection | Mistook a per-minute limit for the daily one (F12) | Now reads Google's quota IDs |
| A helper for running actions | Could have made a failed approval look like it succeeded | Caught in review before I ever used it, and fixed |
| A claim that my virtual environment wasn't active | Wrong; that's just how Windows starts it | Withdrawn |
| A sentence in the report saying a test had caught an error in my answer key | Overstated; I'd caught it by review | Corrected |
| My own idea of rotating several free Gemini keys | Against Google's terms, and it only hides the capacity problem | Dropped in favour of backup providers |
| Gemini inside the app turning "0.21 per gram" into 210 per kg | Broke the "never convert" rule (F13) | A stricter prompt and an evidence check in plain code; TC-03 went from 36 to 38 out of 38 |
| The tests on a fresh copy of the repository | Crashed without a `.env` file (F15) | Fixed when I went back through the brief |

## 5. The decisions that were mine

- **The problem.** Supplier quote comparison in procurement, and the original blueprint. I picked it because
  comparing quotes is repetitive, error-prone work that every manufacturer does, the documents are messy enough
  to need AI, and the final decision still has to stay with a person. That made it a good test of using AI where
  it helps and keeping it away from what it shouldn't decide.
- **Scope.** I agreed to drop a separate API layer, OCR and Google Drive import to finish a working,
  evaluated system in time.
- **The core rule:** AI reads, rules decide, a person approves. A low price must never hide a failed requirement.
- **What the AI is not allowed to decide:** which supplier wins, whether a missing value counts as a pass, or
  anything that approves or commits money.
- **Providers.** Adding backup providers after the real outages, and keeping them optional because every one of
  them sees the documents.
- **How it should look and feel:** professional rather than playful, icons for navigation, and the added
  insights and analytics.
- **Testing it as the user**, and deciding which problems had to be fixed before submitting.
- **How the work reached my machine:** one patch per step, which I applied and tested myself.
- **Being honest in the submission:** the manual time is labelled as an estimate, the bad outage run is kept and
  explained rather than hidden, and this note says what AI did.

## 6. Looking back

Working with an AI pair-engineer made this far quicker than I could have managed alone in five days. It wrote the
code, the tests and the evaluation, and it could read my terminal output and screenshots and find the cause of a
failure fast. What still needed me was judgement. I had to say when something felt wrong for a real buyer (the
balloons, the generic look, getting lost between pages), and I had to run everything myself instead of trusting
that it worked. The most useful lessons came from the failures: the AI in the product quietly converted a price,
and a partial result once looked complete. Both taught me to build checks around the AI instead of relying on it.
Next time I'd time the manual process with a real buyer on day one, and try it on real supplier documents much earlier.
