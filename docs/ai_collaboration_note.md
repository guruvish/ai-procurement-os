# AI collaboration note

*How AI was used to build this project, how its output was verified, and which decisions stayed with me.*

## 1. AI tools and their roles

| Tool | Role |
|---|---|
| **Claude (claude.ai, Claude Opus 5.5)** | Pair-engineer during the build: scope proposal, architecture, all application code, tests, evaluation harness, synthetic dataset and ground truth, documentation drafts. Delivered each step as a self-applying patch script that backs up files before replacing them |
| **Google Gemini API** (`gemini-2.5-flash`, `gemini-3.5-flash-lite`) | Runtime component *inside the product*: reads RFQs and quotations (including scanned PDFs) into a strict schema with source quotes |
| **Anthropic Claude API** (`claude-haiku-5-5`) | Configured as an optional backup provider; not used in the evaluation (account without credit) |

## 2. Work delegated to AI
- Writing the code for every module, the 90 automated tests and the evaluation harness.
- Generating the 10 synthetic test cases and their ground truth, the sample documents and the 3D illustration (code-generated SVG).
- Diagnosing failures from my terminal output and screenshots, and proposing fixes.
- First drafts of all documentation, including this note. I reviewed and edited the personal sections.
- The manual baseline: I didn't have time to time myself doing the cases by hand, so Claude built a
  task-time estimate with its assumptions listed. It is labelled as an estimate everywhere it appears.
- Near the end, at my request, a second pass on the interface: a new colour scheme and typefaces, a Back
  button, scrolling to the top on every page change, and rewriting the on-screen text, README, user guide and
  case study in plainer language. The facts and figures were left as they were.

## 3. How I verified AI-generated results
1. **Ran everything myself after every step**: applied each patch, ran `pytest -q` (from 5 tests at the first step to 90),
   and pasted the output back. Nothing was accepted on the basis of "it should work".
2. **Checked the AI extraction by hand** against the source documents in early runs (e.g. Step 6: purity/moisture
   mandatory flags, Rs. -> INR, "GST 18% extra" -> exclusive, "3 weeks" -> 21 days, validity date).
3. **Used the product as a proxy user** in the browser - upload, review, compare, decide - and reported every
   friction point with screenshots (13 observations, all changed: [user_feedback.md](user_feedback.md)).
4. **Measured against ground truth** with the evaluation harness (440 fields, 21 verdicts, 143 checks), and
   questioned results that did not add up (F11: 100% fields but 85.7% checks -> the metric was wrong).
5. **Visual checks** of generated PDFs and UI states before accepting them.
6. Claude tested each patch in its own sandbox before sending it, where possible with stand-ins for
   unavailable libraries; it stated when a test could only run on my machine (e.g. PyMuPDF, Streamlit AppTest).

## 4. Important results I rejected or that had to be corrected

| What the AI produced | Problem | Outcome |
|---|---|---|
| Inline "edit this line" instructions | Error-prone to apply by hand | I asked for one downloadable patch per step that applies all changes and backs up files |
| Balloons animation on approval | Not appropriate for a premium client | Replaced with a calm "Decision recorded" card |
| Numbered tab labels (①②③) | Looked unprofessional | Icon labels |
| First interface text and docs | Read as stiff and machine-written (arrows, dot-separated lists, jargon like "normalized") | Rewritten in plain language from the buyer's side |
| Purple gradient theme | Looked generic | Navy, teal and status colours with Bricolage Grotesque and IBM Plex Sans |
| Page navigation | No way back, and new pages opened scrolled down | Back button with history; every page change scrolls to the top |
| Default fallback model `gemini-2.5-flash-lite` | Retired by Google for new users (404) | Caught by the pre-flight script; pinned `gemini-3.5-flash-lite` (F9) |
| Evaluation scorer | Compared check names letter by letter -> wrong metric (85.7%) | Fixed + regression test (F11) |
| Theme CSS | Overrode Streamlit's icon font ("keyboard_double_arrow_left" shown as text) | Fixed |
| Processing inside the page script | Killed by any click during a run (F10) | Background jobs + resume |
| Quota detection | Read a per-minute limit as daily (F12) | Uses Google's quota IDs |
| `run_with_errors` helper | Could make a failed approval look successful | Found in AI self-review before release; sentinel value |
| Claim that a terminal path meant the venv was not active | Wrong (Windows venv launcher) | Retracted |
| Draft evaluation report sentence about a test catching a ground-truth error | Overstated - it was caught by review | Rewritten accurately |
| My own idea: rotate several free Gemini keys | Breaks provider terms, hides the capacity problem | Replaced by a multi-provider fallback chain |
| Runtime AI (Gemini) converting "0.21 per gram" to 210 per kg | Broke the "never convert" rule (F13) | Prompt rule + deterministic evidence check; TC-03 36/38 -> 38/38 |

## 5. Decisions I owned
- **The problem:** supplier quotation evaluation for procurement, and the original blueprint. I chose it because
  comparing quotes is repetitive, error-prone work that every manufacturer does, the documents are messy enough
  to need AI, and yet the final decision has to stay with a person. That made it a good test of using AI where
  it helps and keeping it out of where it shouldn't decide.
- **Scope:** accepted cutting FastAPI, OCR and Drive import to finish a working, evaluated system in time.
- **The principle "AI reads, rules decide, a human approves"** - and that a low price must never hide a failed requirement.
- **Providers:** adding a multi-provider chain and Claude as a backup after real outages; keeping backups opt-in for privacy.
- **Product feel:** premium visual design, icon navigation, no playful effects; adding BI insights and analytics.
- **Acting as the proxy user**, and which failures were worth fixing before submission.
- **What the AI may not decide:** which supplier wins, whether a missing value counts as a pass, and anything
  that approves or commits money. Those stay with fixed rules and with a person.
- **How the work was delivered:** one downloadable patch per step that I applied and tested myself, rather than
  hand-editing files from instructions.
- **Honesty in the submission:** the manual baseline is labelled as an estimate, and this note says where AI was used.

## 6. Reflection

Working with an AI pair-engineer made the build much faster than I could have managed alone in five days:
it wrote the code, the tests and the evaluation harness, and it could read my terminal output and screenshots
to find the cause of a failure quickly. The part that still needed me was judgement. I had to say when the
product felt wrong for a real buyer (the balloons, the generic look, getting lost between pages), and I had to
run everything myself rather than trust that it worked. The most useful lesson came from the failures: the
AI inside the product quietly converted a price, and a partial result once looked complete, so I learned to
build checks around the AI instead of relying on it. Next time I would measure the manual baseline with a
real buyer on day one, and test on real supplier documents earlier.
