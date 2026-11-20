"""Lets the offline tests run on a fresh copy of the repository.

The app refuses to start without an AI key, which is right for real use. The tests never call an AI service
(everything is faked), so if no key is configured at all we give them a placeholder."""
import os
from pathlib import Path

if not (Path(__file__).resolve().parent.parent / ".env").exists():
    os.environ.setdefault("GEMINI_API_KEY", "placeholder-for-offline-tests")
