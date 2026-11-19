"""One-command start:  python run.py   -> opens the app in your browser. Stop with Ctrl+C."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    if not (ROOT / ".env").exists():
        sys.exit("Missing .env file. Copy .env.example to .env and put your Gemini API key in it.")
    try:
        sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(ROOT / "streamlit_app.py")], cwd=ROOT))
    except KeyboardInterrupt:
        print("\nApp stopped.")
