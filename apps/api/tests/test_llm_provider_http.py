import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import app.intent.llm as intent_llm
import app.investigation.llm as investigation_llm
from app.core.config import Settings, settings


def _chat_response(payload: dict) -> bytes:
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(payload)}}]}
    ).encode("utf-8")


class _ProviderState:
    def __init__(self) -> None:
        self.status = 200
        self.body = b"{}"
        self.delay = 0.0
        self.requests: list[dict] = []


@pytest.fixture
def provider_server(monkeypatch: pytest.MonkeyPatch):
    state = _ProviderState()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            state.requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(raw),
                }
            )
            if state.delay:
                time.sleep(state.delay)
            try:
                self.send_response(state.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(state.body)))
                self.end_headers()
                self.wfile.write(state.body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setattr(settings, "AI_LLM_ENABLED", True)
    monkeypatch.setattr(
        settings, "AI_LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1"
    )
    monkeypatch.setattr(settings, "AI_LLM_API_KEY", "controlled-test-key")
    monkeypatch.setattr(settings, "AI_LLM_MODEL", "controlled-test-model")
    monkeypatch.setattr(settings, "AI_LLM_TIMEOUT", 1.0)
    monkeypatch.setattr(
        investigation_llm, "is_safe_llm_base_url", lambda _value: True
    )
    monkeypatch.setattr(intent_llm, "is_safe_llm_base_url", lambda _value: True)

    try:
        yield server, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_investigator_uses_controlled_provider_and_valid_narrative(provider_server):
    _server, state = provider_server
    state.body = _chat_response(
        {
            "headline": "Suspicious payout",
            "summary": "The bounded evidence records a blocked payout.",
            "why_suspicious": "A new payee and large amount were recorded.",
            "uncertainty_notes": ["Advisory only."],
        }
    )

    narrative = investigation_llm.generate_llm_narrative(
        {"incident": {"incident_id": "incident-1", "risk_score": 96.0}},
        requested=True,
    )

    assert narrative is not None
    assert narrative.generated_by == "llm"
    assert len(state.requests) == 1
    request = state.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer controlled-test-key"
    prompt = request["body"]["messages"][1]["content"]
    assert "<EVIDENCE_JSON>" in prompt
    assert "incident-1" in prompt


def test_intent_narrator_uses_controlled_provider_and_valid_narrative(provider_server):
    _server, state = provider_server
    state.body = _chat_response(
        {
            "headline": "Advisory intent",
            "summary": "The deterministic classification remains advisory.",
            "uncertainty_notes": ["Derived evidence only."],
        }
    )

    narrative = intent_llm.generate_intent_llm_narrative(
        {"primary_intent": "ACCOUNT_TAKEOVER", "confidence": 0.82},
        requested=True,
    )

    assert narrative is not None
    assert narrative.generated_by == "llm"
    assert len(state.requests) == 1
    assert state.requests[0]["path"] == "/v1/chat/completions"


def test_provider_http_error_uses_fallback_without_leaking_key(
    provider_server, monkeypatch: pytest.MonkeyPatch
):
    _server, state = provider_server
    state.status = 503
    state.body = b'{"error":"provider unavailable"}'
    warnings: list[str] = []
    monkeypatch.setattr(
        investigation_llm.logger,
        "warning",
        lambda message, *args: warnings.append(message % args if args else message),
    )

    narrative = investigation_llm.generate_llm_narrative(
        {"incident": {"incident_id": "incident-1"}}, requested=True
    )

    assert narrative is None
    assert len(state.requests) == 1
    rendered = "\n".join(warnings)
    assert "controlled-test-key" not in rendered
    assert "HTTPStatusError" in rendered


def test_provider_malformed_json_uses_fallback(provider_server):
    _server, state = provider_server
    state.body = b"{not-json"

    assert (
        investigation_llm.generate_llm_narrative(
            {"incident": {"incident_id": "incident-1"}}, requested=True
        )
        is None
    )


def test_provider_missing_choices_uses_fallback(provider_server):
    _server, state = provider_server
    state.body = b'{"choices":[]}'

    assert (
        intent_llm.generate_intent_llm_narrative(
            {"primary_intent": "UNKNOWN_INSUFFICIENT_EVIDENCE"}, requested=True
        )
        is None
    )


def test_oversized_provider_response_is_rejected_before_parsing(
    provider_server, monkeypatch: pytest.MonkeyPatch
):
    _server, state = provider_server
    monkeypatch.setattr(settings, "AI_LLM_MAX_RESPONSE_BYTES", 1024)
    state.body = b'{"choices":[]}' + (b" " * 2048)

    assert (
        investigation_llm.generate_llm_narrative(
            {"incident": {"incident_id": "incident-1"}}, requested=True
        )
        is None
    )


def test_provider_timeout_uses_fallback(provider_server, monkeypatch: pytest.MonkeyPatch):
    _server, state = provider_server
    monkeypatch.setattr(settings, "AI_LLM_TIMEOUT", 0.05)
    state.delay = 0.25
    state.body = _chat_response(
        {
            "headline": "Too late",
            "summary": "This response must not be accepted.",
            "why_suspicious": "The timeout fires first.",
            "uncertainty_notes": [],
        }
    )

    assert (
        investigation_llm.generate_llm_narrative(
            {"incident": {"incident_id": "incident-1"}}, requested=True
        )
        is None
    )


def test_llm_configuration_requires_an_exact_egress_host():
    configuration = {
        "AI_LLM_ENABLED": True,
        "AI_LLM_BASE_URL": "https://narrator.example.com/v1",
        "AI_LLM_API_KEY": "controlled-test-key",
        "AI_LLM_MODEL": "controlled-test-model",
    }

    configured = Settings(
        _env_file=None,
        **configuration,
        AI_LLM_EGRESS_HOST="narrator.example.com",
    )
    assert configured.AI_LLM_EGRESS_HOST == "narrator.example.com"

    with pytest.raises(ValueError, match="AI_LLM_EGRESS_HOST"):
        Settings(
            _env_file=None,
            **configuration,
            AI_LLM_EGRESS_HOST="other.example.com",
        )
