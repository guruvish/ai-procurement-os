# Operator runbook

For whoever installs the app, sets it up and keeps it running.

## Install / update
```bash
python -m venv .venv && .venv\Scripts\activate      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                               # then edit .env
pytest -q                                            # 87 passed = healthy install
```
Python 3.10+. pytest is pinned `<9` (9.2 crashed on Python 3.10.0 - F4).

## Before every demo / after changing `.env`
```bash
python scripts/check_ai.py
```
Every configured provider must print **OK**. Typical problems:

| Output | Meaning | Action |
|---|---|---|
| `404 ... no longer available` | Model ID retired by the provider (F9) | Pick a current, pinned, non-preview model from the list the script prints / the provider console |
| `429 daily quota ids=[...PerDay...]` | Free daily quota used | Wait for reset (Gemini: midnight US Pacific ≈ 13:30 IST) or rely on the fallback model |
| `credit balance is too low` | Claude account without credit | Add credit, or remove `ANTHROPIC_API_KEY` |
| `401` / `403` | Wrong key | Replace the key in `.env` |

## Run
`python run.py` -> http://localhost:8501. Stop with **Ctrl+C**. Data: `data/procurement.db`, uploads in
`data/uploads/`, reports in `data/reports/`, logs in `data/logs/app.log`.

## Logs - what to look for
`data/logs/app.log` (never contains document text or keys):
- `component=supplier_analyst status=ok model=... attempts=1 latency=...` - normal.
- `invalid_output ... fields=[...]` - AI broke the schema; repair retry follows (F1/F2).
- `unavailable: overloaded / rate limited / daily quota` + `answered by fallback backend=...` - provider chain working.
- `request=... outcome=... metrics={...}` - one line per processing run (time, AI calls, failures, models).

## Common situations

| Situation | What to do |
|---|---|
| The last run was interrupted | The app was closed while reading documents. Press **Resume processing**; anything already read is kept (F10) |
| Some documents "not read" | Click **Read the N remaining documents** (only those are sent to the AI) |
| Every provider busy | Wait a minute and retry; consider adding a backup provider (`.env.example`) |
| Antivirus blocks `pytest.exe` | It is the project's own test runner (F5); allow it, `pytest.ini` already avoids temp symlinks |
| Wrong value after review | User corrects it in 🔍 Review; the correction is audited |
| Delete an evaluation | 📁 Documents -> 🗑 Delete (removes files and records) |

## Backups and data
Back up `data/procurement.db` and `data/uploads/` (copy while the app is stopped). `data/` and `.env` are
git-ignored. To start fresh, stop the app and delete `data/procurement.db`.

## Evaluation (quality check after any prompt / model change)
```bash
python -m evaluation.run_evaluation          # all 10 cases, ~35 AI calls
```
Compare `evaluation/results/latest.md` with the previous run. Any new mismatch -> add to `docs/failure_log.md`,
fix, add a regression test, re-run. Uses its own database (`data/evaluation.db`).

## Optional integrations
- Google Sheets export: [google_sheets_setup.md](google_sheets_setup.md).
- Backup AI providers: see comments in `.env.example`. **Each enabled provider receives document contents** -
  get approval before using real company documents.
