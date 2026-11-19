"""Single safe gateway to the AI models.

Provider chain (first available wins; order set by AI_PROVIDER_ORDER in .env):
  gemini  - GEMINI_MODEL, then GEMINI_FALLBACK_MODEL (separate quota / capacity)
  claude  - Anthropic Messages API (ANTHROPIC_API_KEY, ANTHROPIC_MODEL); reads PDFs directly too
  backups - LLM2_..LLM5_: any OpenAI-compatible API (OpenAI/ChatGPT, Groq, OpenRouter, Ollama...)
A backend that is overloaded (5xx), rate-limited (429), out of daily quota, or unreachable is skipped
and the next one is tried. Output of every backend is validated against the same Pydantic schema,
with one repair retry. Logs record which backend answered - never document contents or keys.
"""
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app import config
from app.log import get_logger

log = get_logger("llm")

TRANSIENT_CODES = {408, 500, 502, 503, 504, 529}  # 529 = Anthropic "overloaded"
MAX_TRANSIENT_RETRIES = 2      # 5xx/network when this is the LAST backend: 2s, 4s
MAX_RATE_LIMIT_RETRIES = 3     # 429 per-minute when this is the LAST backend
MAX_RATE_LIMIT_WAIT_S = 65
SHORT_WAIT_S = 10              # with a backup available, only wait for short delays
MAX_REPAIR_RETRIES = 1
HTTP_TIMEOUT_S = 90
_clients: dict = {}
_last_call_at = 0.0


class ExtractionError(Exception):
    """AI extraction failed; message is safe to show to users.
    .meta carries the CallMeta of the failed call so its cost/retries are still counted."""

    def __init__(self, message: str, meta=None):
        super().__init__(message)
        self.meta = meta


class QuotaExhaustedError(ExtractionError):
    """Daily AI quota used up for every configured backend. Retrying now is pointless."""


class _BackendUnavailable(Exception):
    def __init__(self, reason: str, daily_quota: bool = False):
        super().__init__(reason)
        self.reason, self.daily_quota = reason, daily_quota


@dataclass
class Backend:
    name: str
    kind: str          # "gemini" | "anthropic" | "openai"
    model: str
    api_key: str = field(repr=False, default="")
    base_url: str = ""

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"


@dataclass
class CallMeta:
    component: str
    attempts: int = 0
    latency_s: float = 0.0
    used_vision: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    invalid_fields: list = field(default_factory=list)  # schema fields that failed validation on retries
    model: str = ""                                     # backend:model that produced the answer
    rate_limit_waits: int = 0
    fallbacks: list = field(default_factory=list)       # backends skipped, with reason

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Answer:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------- backends
def backends(needs_vision: bool = False) -> list:
    groups = {"gemini": [], "claude": [], "backups": []}
    if config.GEMINI_API_KEY:
        groups["gemini"].append(Backend("gemini", "gemini", config.GEMINI_MODEL, config.GEMINI_API_KEY))
        if config.GEMINI_FALLBACK_MODEL and config.GEMINI_FALLBACK_MODEL != config.GEMINI_MODEL:
            groups["gemini"].append(Backend("gemini", "gemini", config.GEMINI_FALLBACK_MODEL, config.GEMINI_API_KEY))
    if config.ANTHROPIC_API_KEY and config.ANTHROPIC_MODEL:
        groups["claude"].append(Backend("claude", "anthropic", config.ANTHROPIC_MODEL, config.ANTHROPIC_API_KEY,
                                        "https://api.anthropic.com/v1"))
    if not needs_vision:  # scanned PDFs need a model that reads PDFs directly (Gemini / Claude)
        for p in config.EXTRA_PROVIDERS:
            groups["backups"].append(Backend(p["name"], "openai", p["model"], p["api_key"], p["base_url"]))
    order = [g.strip() for g in config.AI_PROVIDER_ORDER.split(",") if g.strip() in groups]
    order += [g for g in groups if g not in order]
    return [b for g in order for b in groups[g]]


def _gemini_client(api_key: str):
    if api_key not in _clients:
        _clients[api_key] = genai.Client(api_key=api_key)
    return _clients[api_key]


def _call_gemini(b: Backend, prompt: str, pdf_bytes: Optional[bytes]) -> _Answer:
    contents = ([types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")] if pdf_bytes else []) + [prompt]
    resp = _gemini_client(b.api_key).models.generate_content(
        model=b.model, contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0))
    um = getattr(resp, "usage_metadata", None)
    return _Answer(resp.text or "", (um.prompt_token_count or 0) if um else 0,
                   (um.candidates_token_count or 0) if um else 0)


def _call_anthropic(b: Backend, prompt: str, pdf_bytes: Optional[bytes]) -> _Answer:
    import base64
    content = []
    if pdf_bytes:
        content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                        "data": base64.b64encode(pdf_bytes).decode()}})
    content.append({"type": "text", "text": prompt})
    headers = {"x-api-key": b.api_key, "anthropic-version": config.ANTHROPIC_VERSION,
               "content-type": "application/json"}
    if config.ANTHROPIC_WORKSPACE_ID:
        headers["anthropic-workspace-id"] = config.ANTHROPIC_WORKSPACE_ID
    body = {"model": b.model, "max_tokens": 4096, "temperature": 0,
            "system": "You extract procurement data. Reply with one valid JSON object only - no prose, no code fences.",
            "messages": [{"role": "user", "content": content}]}
    r = httpx.post(f"{b.base_url}/messages", json=body, headers=headers, timeout=HTTP_TIMEOUT_S)
    if r.status_code >= 400:
        raise _HTTPError(r.status_code, r.text + f" retry-after={r.headers.get('retry-after', '')}")
    data = r.json()
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    usage = data.get("usage") or {}
    return _Answer(text, usage.get("input_tokens", 0), usage.get("output_tokens", 0))


class _HTTPError(Exception):
    def __init__(self, code: int, text: str):
        super().__init__(f"{code} {text[:300]}")
        self.code, self.text = code, text


def _call_openai_compatible(b: Backend, prompt: str) -> _Answer:
    headers = {"Content-Type": "application/json"}
    if b.api_key:
        headers["Authorization"] = f"Bearer {b.api_key}"
    body = {"model": b.model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": "You extract procurement data. Reply with valid JSON only."},
                         {"role": "user", "content": prompt}]}
    r = httpx.post(f"{b.base_url}/chat/completions", json=body, headers=headers, timeout=HTTP_TIMEOUT_S)
    if r.status_code >= 400:
        raise _HTTPError(r.status_code, r.text + f" retry-after={r.headers.get('retry-after', '')}")
    data = r.json()
    usage = data.get("usage") or {}
    return _Answer(data["choices"][0]["message"]["content"] or "",
                   usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))


# ---------------------------------------------------------------- retry policy
def _strip_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    return m.group(1) if m else t


def _error_fields(e: Exception) -> list:
    """Field paths that failed (never the values - documents may be confidential)."""
    if isinstance(e, ValidationError):
        return sorted({".".join(str(p) for p in err["loc"]) or "<root>" for err in e.errors()})
    return ["<invalid JSON>"]


def _retry_delay_seconds(text: str):
    m = re.search(r"retry(?:Delay|-after)?['\"]?\s*(?:in|:|=)\s*['\"]?(\d+(?:\.\d+)?)s?", text, re.I)
    return float(m.group(1)) if m else None


def _quota_ids(text: str) -> list:
    return sorted(set(re.findall(r"quotaId['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9_\-]+)", text)))


def _is_daily_quota(text: str) -> bool:
    """Only a DAILY limit justifies skipping a model for the rest of the run. Google's 429 body can mention
    several quotas; if a per-minute quota is among the violated ones, treat it as a short rate limit (F12)."""
    ids = [i.lower() for i in _quota_ids(text)]
    if ids:
        return all("perday" in i for i in ids)
    t = text.lower().replace("_", "").replace("-", "")
    if "perminute" in t:
        return False
    return "perday" in t or "requestsperday" in t


def _throttle():
    """Keep a minimum gap between calls so a batch stays under per-minute limits."""
    global _last_call_at
    gap = config.GEMINI_MIN_INTERVAL_S - (time.time() - _last_call_at)
    if gap > 0:
        time.sleep(gap)
    _last_call_at = time.time()


def _classify(e: Exception):
    """-> (status_code or None, text)"""
    if isinstance(e, errors.APIError):
        return getattr(e, "code", None), str(e)
    if isinstance(e, _HTTPError):
        return e.code, e.text
    return None, f"{type(e).__name__}"


def _call_backend(b: Backend, component: str, prompt: str, pdf_bytes, meta: CallMeta, has_next: bool) -> _Answer:
    """Calls one backend with retries. Raises _BackendUnavailable to move on to the next one."""
    transient_tries = rate_tries = 0
    while True:
        _throttle()
        try:
            if b.kind == "gemini":
                return _call_gemini(b, prompt, pdf_bytes)
            if b.kind == "anthropic":
                return _call_anthropic(b, prompt, pdf_bytes)
            return _call_openai_compatible(b, prompt)
        except Exception as e:  # classified below
            code, text = _classify(e)
        if code == 429:
            ids = _quota_ids(text)
            if _is_daily_quota(text):
                log.warning(f"component={component} backend={b.label} 429 daily quota ids={ids or '-'}")
                raise _BackendUnavailable("daily quota used up", daily_quota=True)
            if ids:
                log.warning(f"component={component} backend={b.label} 429 quota ids={ids}")
            delay = _retry_delay_seconds(text) or 10.0 * (rate_tries + 1)
            limit = MAX_RATE_LIMIT_RETRIES if not has_next else 1
            if rate_tries < limit and (not has_next or delay <= SHORT_WAIT_S):
                rate_tries += 1
                meta.rate_limit_waits += 1
                wait = min(delay + 1, MAX_RATE_LIMIT_WAIT_S)
                log.warning(f"component={component} backend={b.label} rate-limited (429); waiting {wait:.0f}s")
                time.sleep(wait)
                continue
            raise _BackendUnavailable("rate limited (429)")
        if code is None or code in TRANSIENT_CODES:
            reason = "overloaded / server error" if code else f"unreachable ({text})"
            limit = MAX_TRANSIENT_RETRIES if not has_next else 1
            if transient_tries < limit:
                transient_tries += 1
                wait = 2 ** transient_tries
                log.warning(f"component={component} backend={b.label} {code or text}; retry {transient_tries} in {wait}s")
                time.sleep(wait)
                continue
            raise _BackendUnavailable(f"{reason} ({code or text})")
        # 400/401/403/404...: configuration problem with this backend - log loudly, try the next one
        log.error(f"component={component} backend={b.label} error {code}: check model name / API key")
        raise _BackendUnavailable(f"error {code} - check model name / API key")


def _generate(component: str, prompt: str, pdf_bytes: Optional[bytes], meta: CallMeta) -> _Answer:
    chain = backends(needs_vision=pdf_bytes is not None)
    reasons = []
    for i, b in enumerate(chain):
        try:
            ans = _call_backend(b, component, prompt, pdf_bytes, meta, has_next=i < len(chain) - 1)
            meta.model = b.label
            if reasons:
                log.warning(f"component={component} answered by fallback backend={b.label}")
            return ans
        except _BackendUnavailable as u:
            reasons.append((b, u))
            meta.fallbacks.append(f"{b.label}: {u.reason}")
            log.warning(f"component={component} backend={b.label} unavailable: {u.reason}")
    if not chain:
        raise ExtractionError("No AI provider is configured. Add GEMINI_API_KEY or ANTHROPIC_API_KEY to .env.")
    if all(u.daily_quota for _, u in reasons):
        raise QuotaExhaustedError("The daily AI quota is used up for every configured AI provider. Gemini resets "
                                  "at midnight US Pacific time (about 1:30 PM India time). Already processed "
                                  "documents are kept - run again later, or add a backup provider in .env.")
    summary = "; ".join(f"{b.label} - {u.reason}" for b, u in reasons)
    raise ExtractionError(f"All AI providers are busy or unavailable right now ({summary}). "
                          "Please run again in a minute - already processed documents will be reused.")


def call_json(component: str, prompt: str, model_cls: type, pdf_bytes: Optional[bytes] = None):
    meta = CallMeta(component=component, used_vision=pdf_bytes is not None)
    start = time.time()
    current, last_err = prompt, ""

    for _ in range(MAX_REPAIR_RETRIES + 1):
        meta.attempts += 1
        try:
            ans = _generate(component, current, pdf_bytes, meta)
        except ExtractionError as e:
            meta.latency_s = round(time.time() - start, 2)
            raise type(e)(str(e), meta) from e
        meta.input_tokens += ans.input_tokens
        meta.output_tokens += ans.output_tokens
        try:
            obj = model_cls.model_validate(json.loads(_strip_fences(ans.text)))
            meta.latency_s = round(time.time() - start, 2)
            log.info(f"component={component} status=ok model={meta.model} attempts={meta.attempts} "
                     f"latency={meta.latency_s}s vision={meta.used_vision} tokens={meta.input_tokens}/{meta.output_tokens}")
            return obj, meta
        except (json.JSONDecodeError, ValidationError) as e:
            fields = _error_fields(e)
            meta.invalid_fields.extend(fields)
            last_err = str(e)[:800]
            log.warning(f"component={component} invalid_output attempt={meta.attempts} "
                        f"error={type(e).__name__} fields={fields}")
            current = (prompt + "\n\nYOUR PREVIOUS ANSWER WAS INVALID:\n" + last_err +
                       "\nReturn ONLY corrected JSON matching the shape above.")

    meta.latency_s = round(time.time() - start, 2)
    raise ExtractionError(f"{component}: AI output failed validation after {meta.attempts} attempts "
                          f"(fields: {', '.join(sorted(set(meta.invalid_fields)))}). Manual review needed.",
                          meta)
