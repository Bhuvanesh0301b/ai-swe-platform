import time

import httpx
from groq import Groq, APIStatusError, APIConnectionError
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from core.config import settings
from core.agent_logger import log_llm_call

groq_client = Groq(api_key=settings.GROQ_API_KEY)
gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else None

# Gemini's free tier regularly returns short-lived "503 UNAVAILABLE / high demand"
# spikes. These usually clear within seconds, so instead of failing the whole
# pipeline step on the first 503, the fallback retries with increasing waits.
# 4 attempts total; worst-case added wait is 5 + 15 + 30 = 50 seconds.
GEMINI_MAX_ATTEMPTS = 4
GEMINI_RETRY_DELAYS = (5, 15, 30)  # seconds to wait after attempt 1, 2, 3
GEMINI_TRANSIENT_CODES = {429, 500, 502, 503, 504}


class _EmptyGroqResponse(Exception):
    """Groq answered but returned no text (e.g. a reasoning model spent its
    whole token budget thinking). Treated like any other Groq failure so the
    Gemini fallback takes over instead of passing None downstream."""


def _call_groq(prompt: str, system_prompt: str, max_tokens: int,
               frequency_penalty: float, temperature: float):
    kwargs = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # Only sent when actually used (retry attempts), so first attempts never
    # depend on the model supporting this parameter.
    if frequency_penalty:
        kwargs["frequency_penalty"] = frequency_penalty
    # gpt-oss models are reasoning models: their "thinking" counts against
    # max_tokens. A low effort keeps enough budget left for the actual answer
    # (e.g. a full-file JSON rewrite). Non-reasoning models reject this
    # parameter, so it is only sent for gpt-oss.
    if "gpt-oss" in settings.LLM_MODEL and settings.GROQ_REASONING_EFFORT:
        kwargs["reasoning_effort"] = settings.GROQ_REASONING_EFFORT

    response = groq_client.chat.completions.create(**kwargs)
    text = response.choices[0].message.content
    if not text:
        raise _EmptyGroqResponse("Groq returned an empty response.")
    return text, getattr(response, "usage", None)


def _call_gemini(prompt: str, system_prompt: str, max_tokens: int, temperature: float):
    if gemini_client is None:
        raise ValueError("GEMINI_API_KEY not set - cannot use fallback provider.")

    response = gemini_client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            temperature=temperature,
        ),
    )
    return response.text, getattr(response, "usage_metadata", None)


def _is_transient_gemini_error(error: Exception) -> bool:
    """
    True for errors worth retrying: temporary overload (503), other 5xx,
    per-minute quota (429), and network-level failures (timeouts, dropped
    connections). False for permanent problems such as a bad API key,
    an invalid model name, or a missing key - retrying those is pointless.
    """
    if isinstance(error, genai_errors.APIError):
        return getattr(error, "code", None) in GEMINI_TRANSIENT_CODES
    return isinstance(error, httpx.TransportError)


def _describe_groq_error(error: Exception) -> str:
    if isinstance(error, _EmptyGroqResponse):
        return "empty response (reasoning may have used the whole token budget)"
    code = getattr(error, "status_code", None)
    if code == 404:
        return "model not found (404) - check LLM_MODEL in .env, the model may have been retired"
    if code == 401:
        return "authentication failed (401) - check GROQ_API_KEY"
    if code == 429:
        return "rate limit reached (429)"
    if code == 413:
        return "request too large for per-minute token limit (413)"
    if code:
        return f"HTTP {code}"
    return type(error).__name__


def _ask_gemini_with_retry(prompt: str, system_prompt: str, max_tokens: int,
                           temperature: float, agent_name: str, task_id: int | None) -> str:
    """
    Calls Gemini, retrying transient failures with backoff. Each attempt is
    logged separately. Raises the last error (annotated with the attempt
    count) if every attempt fails or a non-transient error occurs.
    """
    last_error = None
    attempt = 0
    for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
        label = (f"{agent_name}[gemini_fallback]" if attempt == 1
                 else f"{agent_name}[gemini_fallback_retry{attempt - 1}]")
        try:
            with log_llm_call(label, task_id) as log_ctx:
                text, usage = _call_gemini(prompt, system_prompt, max_tokens, temperature)
                if not text:
                    raise ValueError("Gemini returned an empty response.")
                log_ctx["usage"] = usage
                return text
        except Exception as e:
            last_error = e
            if attempt >= GEMINI_MAX_ATTEMPTS or not _is_transient_gemini_error(e):
                break
            # Sleep is outside log_llm_call so logged durations stay accurate.
            time.sleep(GEMINI_RETRY_DELAYS[attempt - 1])

    suffix = f" (after {attempt} attempts)" if attempt > 1 else ""
    raise RuntimeError(f"{last_error}{suffix}") from last_error


def ask_llm(prompt: str, system_prompt: str = "You are a helpful AI software engineering assistant.",
            max_tokens: int = 4096, frequency_penalty: float = 0.0, temperature: float = 0.2,
            agent_name: str = "unknown_agent", task_id: int | None = None) -> str:
    """
    Sends a prompt to Groq's cloud LLM (primary) and returns the text response.
    If Groq fails (rate limit, request too large, or connection problem), it
    automatically falls back to Gemini's free tier. Temporary Gemini failures
    (e.g. 503 high demand) are retried with backoff before giving up.
    Raises ValueError only if both providers ultimately fail.
    """
    with log_llm_call(f"{agent_name}[groq]", task_id) as log_ctx:
        try:
            text, usage = _call_groq(prompt, system_prompt, max_tokens, frequency_penalty, temperature)
            log_ctx["usage"] = usage
            return text
        except (APIStatusError, APIConnectionError, _EmptyGroqResponse) as e:
            # Catches BOTH the 429 daily rate limit AND the 413 "request too
            # large" per-minute token cap (Groq's free tier has separate daily
            # and per-minute limits), plus connection/timeout errors - any of
            # them (and an empty answer) should trigger the Gemini fallback
            # rather than crashing.
            log_ctx["usage"] = None
            groq_error = e

    try:
        return _ask_gemini_with_retry(prompt, system_prompt, max_tokens, temperature,
                                      agent_name, task_id)
    except Exception as gemini_error:
        raise ValueError(
            "Both Groq and Gemini failed. "
            f"Groq: {_describe_groq_error(groq_error)}. Gemini: {str(gemini_error)}"
        ) from gemini_error