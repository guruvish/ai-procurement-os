"""Regression tests for real failures seen in live runs (no API calls - Gemini is faked).

FAILURE F2 (2026-11-19, Gamma_Quotation.pdf): quote said "Price: to be confirmed".
Gemini correctly returned unit_price=null but ALSO "evidence": {"unit_price": null, ...}.
Schema rejected it, the repair retry made it worse, the supplier was dropped.
Fix: absent value = no evidence (dropped, not an error) + prompt rule to omit such keys.
"""
import json

import pytest

from app.agents import llm
from app.agents.llm import ExtractionError, call_json
from app.schemas import Evidence, SupplierQuotation

GAMMA_LIKE = {
    "supplier_name": "Gamma Organics Ltd", "quotation_date": "2026-10-01", "valid_until": "2026-10-31",
    "unit_price": None, "currency": None, "tax_status": "unknown", "delivery_days": 28,
    "payment_terms": "50% advance, balance within 15 days",
    "specifications": [{"name": "purity", "value": 99.6, "unit": "%",
                        "evidence": {"page": 1, "quote": "Assay NLT 99.6%", "confidence": 0.9}}],
    "certificates": ["Certificate of Analysis"], "exclusions": None, "conflicts": [],
    "evidence": {"supplier_name": {"page": 1, "quote": "Gamma Organics Ltd", "confidence": 0.95},
                 "unit_price": None, "currency": None, "tax_status": None},
}


def test_f2_null_evidence_entries_no_longer_break_validation():
    q = SupplierQuotation.model_validate(GAMMA_LIKE)
    assert q.unit_price is None                       # missing price stays missing
    assert set(q.evidence) == {"supplier_name"}       # null evidence dropped, real evidence kept
    assert q.exclusions == []                         # null list tolerated


def test_evidence_confidence_percent_and_odd_pages_are_normalised():
    ev = Evidence(page="1-2", quote="x", confidence=95)
    assert ev.page is None and ev.confidence == pytest.approx(0.95)


class _Resp:
    def __init__(self, payload):
        self.text = payload if isinstance(payload, str) else json.dumps(payload)
        self.usage_metadata = None
        self.input_tokens = self.output_tokens = 0


def _fake_generate(responses):
    it = iter(responses)
    return lambda component, prompt, pdf_bytes, meta: _Resp(next(it))


def test_f2_gamma_shape_passes_on_first_attempt(monkeypatch):
    monkeypatch.setattr(llm, "_generate", _fake_generate([GAMMA_LIKE]))
    q, meta = call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert meta.attempts == 1 and q.supplier_name == "Gamma Organics Ltd"


def test_repair_retry_recovers_and_records_failing_fields(monkeypatch):
    bad = dict(GAMMA_LIKE, tax_status="maybe")
    monkeypatch.setattr(llm, "_generate", _fake_generate([bad, GAMMA_LIKE]))
    _, meta = call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert meta.attempts == 2 and meta.invalid_fields == ["tax_status"]


def test_f3_failed_call_keeps_its_metrics(monkeypatch):
    """FAILURE F3: a call that failed all attempts lost its metrics (summary showed 0 retries)."""
    monkeypatch.setattr(llm, "_generate", _fake_generate(["not json", "{still not json"]))
    with pytest.raises(ExtractionError) as exc:
        call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert exc.value.meta.attempts == 2
    assert "<invalid JSON>" in exc.value.meta.invalid_fields


# ---------- F6 / F8: rate limits (429), overload (503) and the provider chain ----------
from google.genai import errors  # noqa: E402

from app import config  # noqa: E402
from app.agents.llm import QuotaExhaustedError, backends  # noqa: E402


class _FakeAPIError(errors.APIError):
    """An API error without depending on the SDK's constructor signature."""

    def __init__(self, code, text):  # noqa
        Exception.__init__(self, text)
        self.code, self._text = code, text

    def __str__(self):
        return self._text


def _429(text):
    return _FakeAPIError(429, text)


def _503():
    return _FakeAPIError(503, "503 UNAVAILABLE. The model is overloaded. Please try again later.")


class _FakeGemini:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        step = self.script.pop(0) if self.script else _503()
        if isinstance(step, Exception):
            raise step
        return _Resp(step)


@pytest.fixture
def chain(monkeypatch):
    slept = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(config, "GEMINI_MIN_INTERVAL_S", 0)
    monkeypatch.setattr(config, "GEMINI_MODEL", "primary")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODEL", "fallback")
    monkeypatch.setattr(config, "EXTRA_PROVIDERS", [])
    monkeypatch.setattr(config, "GEMINI_API_KEY", "g-key")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "AI_PROVIDER_ORDER", "gemini,claude,backups")
    return slept


def _use(monkeypatch, fake):
    monkeypatch.setattr(llm, "_gemini_client", lambda key: fake)


def test_f6_short_per_minute_limit_waits_then_succeeds(monkeypatch, chain):
    _use(monkeypatch, _FakeGemini([_429("429 RESOURCE_EXHAUSTED PerMinute. Please retry in 3s."), GAMMA_LIKE]))
    _, meta = call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert chain == [4.0]                      # API asked 3s, we wait 3s + 1s margin
    assert meta.rate_limit_waits == 1 and meta.model == "gemini:primary"


def test_f6_long_per_minute_limit_moves_to_backup_instead_of_waiting(monkeypatch, chain):
    fake = _FakeGemini([_429("429 PerMinute. Please retry in 45s."), GAMMA_LIKE])
    _use(monkeypatch, fake)
    _, meta = call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert chain == [] and fake.calls == ["primary", "fallback"] and meta.model == "gemini:fallback"


def test_f6_daily_quota_switches_to_fallback_model(monkeypatch, chain):
    fake = _FakeGemini([_429("429 quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"), GAMMA_LIKE])
    _use(monkeypatch, fake)
    _, meta = call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert fake.calls == ["primary", "fallback"] and meta.model == "gemini:fallback"
    assert chain == []                         # no pointless waiting on a daily limit


def test_f6_daily_quota_on_all_backends_stops_with_clear_error(monkeypatch, chain):
    daily = "429 GenerateRequestsPerDayPerProjectPerModel-FreeTier"
    _use(monkeypatch, _FakeGemini([_429(daily), _429(daily)]))
    with pytest.raises(QuotaExhaustedError, match="daily AI quota"):
        call_json("supplier_analyst", "prompt", SupplierQuotation)


def test_f8_overloaded_primary_falls_back_after_one_quick_retry(monkeypatch, chain):
    """FAILURE F8 (13:31 run): Gemini 503 'model is overloaded' x3 suppliers, no fallback was tried."""
    fake = _FakeGemini([_503(), _503(), GAMMA_LIKE])
    _use(monkeypatch, fake)
    _, meta = call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert fake.calls == ["primary", "primary", "fallback"]
    assert chain == [2] and meta.model == "gemini:fallback"
    assert meta.fallbacks == ["gemini:primary: overloaded / server error (503)"]


class _HttpResp:
    def __init__(self, status, payload):
        self.status_code, self._payload, self.headers, self.text = status, payload, {}, json.dumps(payload)

    def json(self):
        return self._payload


def test_f8_openai_compatible_backup_answers_when_gemini_is_down(monkeypatch, chain):
    monkeypatch.setattr(config, "EXTRA_PROVIDERS", [{"name": "groq", "base_url": "https://api.example/v1",
                                                     "model": "some-model", "api_key": "k"}])
    _use(monkeypatch, _FakeGemini([]))         # every Gemini call -> 503
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, body=json, headers=headers)
        return _HttpResp(200, {"choices": [{"message": {"content": __import__("json").dumps(GAMMA_LIKE)}}],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    q, meta = call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert meta.model == "groq:some-model" and q.supplier_name == "Gamma Organics Ltd"
    assert sent["url"] == "https://api.example/v1/chat/completions"
    assert sent["body"]["response_format"] == {"type": "json_object"} and sent["body"]["temperature"] == 0
    assert sent["headers"]["Authorization"] == "Bearer k"
    assert meta.input_tokens == 10 and len(meta.fallbacks) == 2


def test_scanned_pdfs_are_never_sent_to_text_only_backups(monkeypatch, chain):
    monkeypatch.setattr(config, "EXTRA_PROVIDERS", [{"name": "groq", "base_url": "u", "model": "m", "api_key": ""}])
    assert [b.name for b in backends(needs_vision=True)] == ["gemini", "gemini"]
    assert [b.name for b in backends(needs_vision=False)] == ["gemini", "gemini", "groq"]


def test_all_backends_down_gives_actionable_message(monkeypatch, chain):
    _use(monkeypatch, _FakeGemini([]))
    with pytest.raises(ExtractionError, match="All AI providers are busy") as exc:
        call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert "run again" in str(exc.value) and exc.value.meta is not None


# ---------- Claude (Anthropic Messages API) ----------
def _claude(monkeypatch, model="claude-test"):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "a-key")
    monkeypatch.setattr(config, "ANTHROPIC_MODEL", model)
    monkeypatch.setattr(config, "ANTHROPIC_VERSION", "2023-06-01")
    monkeypatch.setattr(config, "ANTHROPIC_WORKSPACE_ID", "")


def test_claude_answers_when_gemini_is_overloaded(monkeypatch, chain):
    _claude(monkeypatch)
    _use(monkeypatch, _FakeGemini([]))         # every Gemini call -> 503
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, body=json, headers=headers)
        return _HttpResp(200, {"content": [{"type": "text", "text": __import__("json").dumps(GAMMA_LIKE)}],
                               "usage": {"input_tokens": 12, "output_tokens": 7}})
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    q, meta = call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert meta.model == "claude:claude-test" and q.supplier_name == "Gamma Organics Ltd"
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["headers"]["x-api-key"] == "a-key" and sent["headers"]["anthropic-version"] == "2023-06-01"
    assert sent["body"]["temperature"] == 0 and sent["body"]["messages"][0]["content"][-1]["text"] == "prompt"
    assert meta.input_tokens == 12


def test_claude_receives_scanned_pdfs_as_documents(monkeypatch, chain):
    _claude(monkeypatch)
    monkeypatch.setattr(config, "AI_PROVIDER_ORDER", "claude,gemini")
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(body=json)
        return _HttpResp(200, {"content": [{"type": "text", "text": __import__("json").dumps(GAMMA_LIKE)}]})
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    call_json("supplier_analyst", "prompt", SupplierQuotation, pdf_bytes=b"%PDF-1.4 scanned")
    block = sent["body"]["messages"][0]["content"][0]
    assert block["type"] == "document" and block["source"]["media_type"] == "application/pdf"


def test_provider_order_is_configurable_and_vision_keeps_claude(monkeypatch, chain):
    _claude(monkeypatch)
    monkeypatch.setattr(config, "EXTRA_PROVIDERS", [{"name": "groq", "base_url": "u", "model": "m", "api_key": ""}])
    monkeypatch.setattr(config, "AI_PROVIDER_ORDER", "claude,gemini,backups")
    assert [b.label for b in backends()] == ["claude:claude-test", "gemini:primary", "gemini:fallback", "groq:m"]
    assert [b.name for b in backends(needs_vision=True)] == ["claude", "gemini", "gemini"]


def test_claude_overloaded_529_moves_on(monkeypatch, chain):
    _claude(monkeypatch)
    monkeypatch.setattr(config, "AI_PROVIDER_ORDER", "claude,gemini")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: _HttpResp(529, {"type": "error",
                        "error": {"type": "overloaded_error"}}))
    _use(monkeypatch, _FakeGemini([GAMMA_LIKE]))
    _, meta = call_json("supplier_analyst", "prompt", SupplierQuotation)
    assert meta.model == "gemini:primary" and meta.fallbacks[0].startswith("claude:claude-test: overloaded")


def test_f12_per_minute_limit_is_not_mistaken_for_daily_quota():
    """FAILURE F12: primary model marked 'daily quota used up', yet its next call succeeded."""
    both = ("429 RESOURCE_EXHAUSTED {'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'} "
            "{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}")
    assert llm._is_daily_quota(both) is False
    assert llm._is_daily_quota("429 {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}") is True
    assert llm._is_daily_quota("429 Please retry in 3s. Learn about daily limits at ...") is False
