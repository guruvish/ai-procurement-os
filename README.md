# RFQ Evaluator

When you send out an RFQ, the quotes come back in every format imaginable: a PDF from one supplier, an
Excel sheet from another, a Word file, now and then a scan. Someone has to read them all, retype the numbers,
convert grams to kilos, strip out GST and work out who actually meets the spec. This app does the reading
and the arithmetic and leaves the decision to you.

The split is deliberate. An AI model reads the documents and fills in a fixed form, quoting the line each
value came from. Plain, tested Python does the comparing, so the same quotes always give the same result
and every verdict comes with a reason. A person approves the supplier, and that approval is logged.

**Who it's for:** a purchase or procurement executive comparing three to six quotes against an RFQ.

**What changes:** instead of retyping every quote into Excel, you upload the files, wait about half a minute,
check the values against their source lines, and approve. You get a PDF and Excel report at the end.

**How well it works:** on 10 test RFQs (21 quotes) it got 99.5% of fields right, every supplier verdict
right and every recommendation right, and it caught every piece of missing information. The same cases
pasted into a plain AI prompt got 85.7% of verdicts and 9 of 10 recommendations right; its one wrong pick
would have cost ₹50,000 more on the order. The details,
including where it went wrong, are in the [evaluation report](docs/evaluation_report.md).

## Getting started

You need Python 3.10 or newer. On Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
```

On macOS or Linux, use `source .venv/bin/activate` and `cp .env.example .env` instead.

Open `.env` and paste in a Gemini API key (you can get one free at aistudio.google.com). A Claude key works
too. Then check that the key is picked up and start the app:

```bash
python scripts/check_ai.py
python run.py
```

The app opens at http://localhost:8501.

If you want something to try it on, `python scripts/make_sample_data.py` creates a sample RFQ with four quotes
in `sample_data/RFQ-2026-001/`. One of the files is broken on purpose, so you can see what happens.

## Using it

1. **New evaluation.** Give the RFQ a number, then add the RFQ document and all the quotes.
2. **Documents tab.** Press *Read documents and compare*. It runs in the background and takes 10 to 15
   seconds per file.
3. **Review tab.** Every value sits next to the line it was read from. Fix anything that's wrong, save,
   and re-evaluate.
4. **Compare, Risks and Insights tabs.** See who qualifies and why, what each order would cost, which
   questions are still open (with a draft email to the supplier), and how much the choice saves.
5. **Decision tab.** Approve or reject under your name, then download the reports. If you pick a supplier
   that doesn't meet every requirement, you'll be asked to say why.

The [user guide](docs/user_guide.md) walks through each screen in more detail.

## How it's put together

The interface is Streamlit. When you start processing, a LangGraph workflow runs in a background thread.
Each file is turned into page-numbered text, or flagged as a scan. The AI extractors fill a Pydantic schema
and quote their source for every value. If Gemini is busy or out of quota, the next model in the chain
takes over (Gemini Flash-Lite, then Claude or any OpenAI-compatible model you've set up).

After that there's no more AI. A check confirms that each price actually appears in the text it was quoted
from. Prices are put on the same unit and tax basis. The evaluation engine marks each requirement as met,
missed, not stated or needing a second look, gives each supplier a verdict, and recommends the cheapest one
that qualifies. Everything is stored in SQLite with an audit log. [architecture.md](docs/architecture.md)
has the full picture.

```
app/
  agents/        llm.py (model chain and retries), extractors.py (prompts), workflow.py (LangGraph)
  services/      parsing, normalisation, evaluation, evidence check, clarification emails,
                 analytics, reports
  integrations/  google_sheets.py (optional export)
  db.py          SQLite storage and audit log
  schemas.py     the data shapes everything agrees on
streamlit_app.py the interface
run.py           starts the app
evaluation/      10 test cases with known answers, plus the scorer
scripts/         check_ai.py and make_sample_data.py
tests/           90 offline tests (AI and Google are faked; no key needed)
docs/            guides, the evaluation report, the failure log and the case study
```

## Tests and evaluation

```bash
pytest -q                                          # 90 tests, offline, about a minute
python -m evaluation.run_evaluation                # all 10 cases against the real models (~35 AI calls, ~6 min)
python -m evaluation.run_evaluation --cases TC-03  # a single case
python -m evaluation.run_evaluation --report-only  # rebuild the report, e.g. after filling in baseline.csv
python -m evaluation.plain_ai_baseline            # the same 10 cases with a plain AI prompt, for comparison
```

## Settings

Everything lives in `.env`, which git ignores. `.env.example` has no secrets in it.

| Setting | What it does |
|---|---|
| `GEMINI_API_KEY`, `GEMINI_MODEL` | The main model (`gemini-2.5-flash` by default) |
| `GEMINI_FALLBACK_MODEL` | Used when the main model is busy or out of quota (`gemini-3.5-flash-lite`) |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Optional Claude backup, which can also read scans |
| `LLM2_*` to `LLM5_*` | Optional OpenAI-compatible backups: OpenAI, Groq, OpenRouter or a local Ollama |
| `AI_PROVIDER_ORDER` | The order to try them in, for example `gemini,claude,backups` |
| `GOOGLE_SHEET_ID` | Optional Google Sheets export ([setup](docs/google_sheets_setup.md)) |

Every backup you add is another company that sees your documents, so only add the ones you're comfortable with.

## What it doesn't do (yet)

- The test documents are ones I wrote for this project. Real supplier quotes are messier, so expect lower
  scores on them.
- Most evaluation runs were answered by `gemini-3.5-flash-lite`, because the free tier of the main model ran out.
- It's a single-user app running on your own machine, not a shared service.
- It recommends; it never places orders. It only converts currencies at a rate you've approved.

The [case study](docs/case_study.md) and the [failure log](docs/failure_log.md) go into what went wrong along
the way and what I changed.
