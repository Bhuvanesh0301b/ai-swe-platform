"""Tests for Groq -> Gemini fallback and Gemini retry-with-backoff.
No real API calls are made: both providers and time.sleep are mocked."""
import httpx
import pytest
from google.genai import errors as genai_errors
from groq import APIStatusError

from core import llm_client


def _groq_error(status=429):
    request = httpx.Request("POST", "https://api.groq.com/test")
    response = httpx.Response(status, request=request)
    return APIStatusError("groq failure", response=response, body=None)


def _gemini_error(code=503):
    return genai_errors.APIError(code, {"error": {"code": code, "message": "boom", "status": "X"}})


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: calls.append(s))
    return calls


def _groq_fails(monkeypatch, status=429):
    def fail(*a, **k):
        raise _groq_error(status)
    monkeypatch.setattr(llm_client, "_call_groq", fail)


def test_groq_success_never_touches_gemini(monkeypatch, sleeps):
    monkeypatch.setattr(llm_client, "_call_groq", lambda *a, **k: ("groq ok", None))
    monkeypatch.setattr(llm_client, "_call_gemini",
                        lambda *a, **k: pytest.fail("Gemini should not be called"))
    assert llm_client.ask_llm("hi") == "groq ok"


def test_groq_failure_falls_back_to_gemini(monkeypatch, sleeps):
    _groq_fails(monkeypatch, 429)
    monkeypatch.setattr(llm_client, "_call_gemini", lambda *a, **k: ("gemini ok", None))
    assert llm_client.ask_llm("hi") == "gemini ok"
    assert sleeps == []


def test_groq_413_also_falls_back(monkeypatch, sleeps):
    _groq_fails(monkeypatch, 413)
    monkeypatch.setattr(llm_client, "_call_gemini", lambda *a, **k: ("gemini ok", None))
    assert llm_client.ask_llm("hi") == "gemini ok"


def test_gemini_503_then_success_is_retried(monkeypatch, sleeps):
    _groq_fails(monkeypatch)
    results = [_gemini_error(503), _gemini_error(503), ("recovered", None)]

    def flaky(*a, **k):
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(llm_client, "_call_gemini", flaky)

    assert llm_client.ask_llm("hi") == "recovered"
    assert sleeps == [5, 15]


def test_gemini_persistent_503_gives_up_after_max_attempts(monkeypatch, sleeps):
    _groq_fails(monkeypatch)
    attempts = []

    def always_503(*a, **k):
        attempts.append(1)
        raise _gemini_error(503)
    monkeypatch.setattr(llm_client, "_call_gemini", always_503)

    with pytest.raises(ValueError) as exc:
        llm_client.ask_llm("hi")
    assert len(attempts) == llm_client.GEMINI_MAX_ATTEMPTS
    assert sleeps == [5, 15, 30]
    assert "Both Groq and Gemini failed" in str(exc.value)
    assert "rate limit reached (429)" in str(exc.value)
    assert "after 4 attempts" in str(exc.value)


def test_gemini_permanent_error_is_not_retried(monkeypatch, sleeps):
    _groq_fails(monkeypatch)
    attempts = []

    def bad_key(*a, **k):
        attempts.append(1)
        raise _gemini_error(400)
    monkeypatch.setattr(llm_client, "_call_gemini", bad_key)

    with pytest.raises(ValueError):
        llm_client.ask_llm("hi")
    assert len(attempts) == 1
    assert sleeps == []


def test_gemini_empty_response_is_treated_as_failure(monkeypatch, sleeps):
    _groq_fails(monkeypatch)
    monkeypatch.setattr(llm_client, "_call_gemini", lambda *a, **k: (None, None))
    with pytest.raises(ValueError) as exc:
        llm_client.ask_llm("hi")
    assert "empty response" in str(exc.value)
    assert sleeps == []


def test_gemini_network_error_is_retried(monkeypatch, sleeps):
    _groq_fails(monkeypatch)
    results = [httpx.ConnectTimeout("timed out"), ("ok", None)]

    def flaky(*a, **k):
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(llm_client, "_call_gemini", flaky)
    assert llm_client.ask_llm("hi") == "ok"
    assert sleeps == [5]