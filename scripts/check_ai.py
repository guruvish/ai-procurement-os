"""Checks every configured AI provider with a tiny request (a few tokens each).
Run:  python scripts/check_ai.py"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.agents import llm  # noqa: E402

PROMPT = 'Reply with exactly this JSON: {"ok": true}'

print("Provider order:", config.AI_PROVIDER_ORDER)
chain = llm.backends()
if not chain:
    sys.exit("No provider configured - check .env")
for b in chain:
    t0 = time.time()
    try:
        if b.kind == "gemini":
            ans = llm._call_gemini(b, PROMPT, None)
        elif b.kind == "anthropic":
            ans = llm._call_anthropic(b, PROMPT, None)
        else:
            ans = llm._call_openai_compatible(b, PROMPT)
        ok = json.loads(llm._strip_fences(ans.text)).get("ok") is True
        print(f"  {'OK  ' if ok else 'ODD '} {b.label:<45} {time.time() - t0:5.1f}s  reply={ans.text.strip()[:40]!r}")
    except Exception as e:
        code, text = llm._classify(e)
        print(f"  FAIL {b.label:<45} {time.time() - t0:5.1f}s  {code or ''} {text[:160]}")

if config.ANTHROPIC_API_KEY:
    try:
        r = httpx.get("https://api.anthropic.com/v1/models", timeout=20,
                      headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": config.ANTHROPIC_VERSION})
        ids = [m["id"] for m in r.json().get("data", [])]
        print("\nClaude models available to your key:", ", ".join(ids) or r.text[:200])
    except Exception as e:
        print("\nCould not list Claude models:", type(e).__name__)
