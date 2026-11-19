import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")  # used only if daily quota runs out
GEMINI_MIN_INTERVAL_S = float(os.getenv("GEMINI_MIN_INTERVAL_S", "4"))  # gap between AI calls (free-tier friendly)

# Optional backup providers (OpenAI-compatible APIs: OpenAI/ChatGPT, Groq, OpenRouter, Ollama, ...).
# Configure LLM2_..LLM5_ in .env; a provider is active only when BASE_URL and MODEL are set.
EXTRA_PROVIDERS = []
for _i in range(2, 6):
    _base, _model = os.getenv(f"LLM{_i}_BASE_URL", "").strip(), os.getenv(f"LLM{_i}_MODEL", "").strip()
    if _base and _model:
        EXTRA_PROVIDERS.append({"name": os.getenv(f"LLM{_i}_NAME", f"backup{_i}").strip() or f"backup{_i}",
                                "base_url": _base.rstrip("/"), "model": _model,
                                "api_key": os.getenv(f"LLM{_i}_API_KEY", "").strip()})

DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "procurement.db"
MAX_FILE_MB = 15

for d in (UPLOAD_DIR, REPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Anthropic Claude (optional; also reads scanned PDFs)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5").strip()
ANTHROPIC_VERSION = os.getenv("ANTHROPIC_VERSION", "2023-06-01").strip()
ANTHROPIC_WORKSPACE_ID = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()

# Google Sheets export (optional integration) - see docs/google_sheets_setup.md
GOOGLE_SERVICE_ACCOUNT_FILE = ROOT / os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/google_service_account.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()

# Which provider group is tried first: any order of gemini, claude, backups
AI_PROVIDER_ORDER = os.getenv("AI_PROVIDER_ORDER", "gemini,claude,backups")

if not GEMINI_API_KEY and not ANTHROPIC_API_KEY:
    raise RuntimeError("No AI key found. Copy .env.example to .env and add GEMINI_API_KEY and/or ANTHROPIC_API_KEY.")
