from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import math
import re
import ssl
import time
from collections.abc import Mapping
from contextlib import asynccontextmanager
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp
import certifi

from config import (
    GITHUB_MODELS_API_VERSION,
    POS_AI_API_KEY,
    POS_AI_API_PROVIDER,
    POS_AI_MAX_CONCURRENT_REQUESTS,
    POS_AI_MAX_TOKENS,
    POS_AI_PROVIDER_KEYS,
    POS_AI_PROVIDER_MODELS,
    POS_AI_PROVIDER_URLS,
    POS_AI_API_URL,
    POS_AI_RATE_LIMIT_FALLBACK_SECONDS,
    POS_AI_MODEL,
    POS_AI_TIMEOUT_SECONDS,
    POS_AI_TOP_P,
    POS_AI_TEMPERATURE,
)


logger = logging.getLogger(__name__)

_AI_REQUEST_SEMAPHORE = asyncio.Semaphore(max(1, POS_AI_MAX_CONCURRENT_REQUESTS))
# #14: защищаем read-modify-write общих _provider_cursor/_provider_backoff_until,
# чтобы при POS_AI_MAX_CONCURRENT_REQUESTS > 1 два запроса не выбрали один индекс
# и курсор не «перескакивал».
_provider_lock = asyncio.Lock()
_ai_backoff_until = 0.0
_ai_backoff_reason = ""
_ai_last_backoff_log_at = 0.0
_provider_cursor = 0
_provider_backoff_until: dict[int, float] = {}
_missing_media_provider_logged = False
_MAX_UPSTREAM_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_INLINE_MEDIA_BYTES = 14 * 1024 * 1024
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_SUPPORTED_TOOL_CHOICES = frozenset({"auto", "required", "none"})


class _AIQueueTimeout(Exception):
    pass


@asynccontextmanager
async def _request_slot(total_timeout: int):
    acquired = False
    queue_timeout = max(3.0, min(float(total_timeout) * 0.25, 15.0))
    try:
        try:
            await asyncio.wait_for(_AI_REQUEST_SEMAPHORE.acquire(), timeout=queue_timeout)
        except asyncio.TimeoutError as exc:
            raise _AIQueueTimeout from exc
        acquired = True
        yield
    finally:
        if acquired:
            _AI_REQUEST_SEMAPHORE.release()


def _is_safe_provider_url(url: str) -> bool:
    """Require HTTPS, except for explicit loopback-only development endpoints."""
    if not isinstance(url, str) or not url or any(char.isspace() for char in url):
        return False
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        _ = parsed.port  # Validate a malformed/non-numeric port eagerly.
    except (TypeError, ValueError):
        return False
    if not host or parsed.username is not None or parsed.password is not None:
        return False
    if parsed.fragment:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and host in _LOOPBACK_HOSTS


def _provider_kind(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if host == "models.github.ai":
        return "github_models"
    if host == "googleapis.com" or host.endswith(".googleapis.com"):
        return "gemini"
    return POS_AI_API_PROVIDER


def _build_provider_pool() -> list[dict[str, str]]:
    if POS_AI_PROVIDER_KEYS:
        if POS_AI_PROVIDER_URLS and len(POS_AI_PROVIDER_URLS) != len(POS_AI_PROVIDER_KEYS):
            logger.error(
                "POS_AI_PROVIDER_URLS must contain exactly one URL per POS_AI_PROVIDER_KEYS entry; AI pool disabled."
            )
            return []
        if POS_AI_PROVIDER_MODELS and len(POS_AI_PROVIDER_MODELS) != len(POS_AI_PROVIDER_KEYS):
            logger.error(
                "POS_AI_PROVIDER_MODELS must contain exactly one model per POS_AI_PROVIDER_KEYS entry; AI pool disabled."
            )
            return []
        pool: list[dict[str, str]] = []
        for index, key in enumerate(POS_AI_PROVIDER_KEYS):
            url = POS_AI_PROVIDER_URLS[index] if index < len(POS_AI_PROVIDER_URLS) else POS_AI_API_URL
            model = POS_AI_PROVIDER_MODELS[index] if index < len(POS_AI_PROVIDER_MODELS) else POS_AI_MODEL
            if not _is_safe_provider_url(url):
                logger.error("AI provider %s has an unsafe or invalid URL and was skipped.", index + 1)
                continue
            if not key.strip() or not model.strip():
                logger.error("AI provider %s is missing a key or model and was skipped.", index + 1)
                continue
            pool.append(
                {
                    "name": f"provider_{index + 1}",
                    "api_key": key.strip(),
                    "api_url": url,
                    "model": model.strip(),
                    "provider": _provider_kind(url),
                }
            )
        if pool:
            return pool

    if not _is_safe_provider_url(POS_AI_API_URL):
        logger.error("Default AI provider has an unsafe or invalid URL; AI is disabled.")
        return []
    if not (POS_AI_MODEL or "").strip():
        logger.error("Default AI provider model is empty; AI is disabled.")
        return []
    return [
        {
            "name": "default",
            "api_key": (POS_AI_API_KEY or "").strip(),
            "api_url": POS_AI_API_URL,
            "model": POS_AI_MODEL.strip(),
            "provider": _provider_kind(POS_AI_API_URL),
        }
    ]


_AI_PROVIDER_POOL = _build_provider_pool()


def ai_has_configured_provider() -> bool:
    """True, если есть хотя бы один реально настроенный AI-провайдер."""
    return bool(_AI_PROVIDER_POOL and any(provider.get("api_key") for provider in _AI_PROVIDER_POOL))


def ai_has_configured_media_provider() -> bool:
    """True when native audio/video analysis has an authenticated Gemini route."""
    return any(
        provider.get("provider") == "gemini" and bool(provider.get("api_key"))
        for provider in _AI_PROVIDER_POOL
    )


def _messages_have_visual_inputs(messages: list[dict[str, Any]]) -> bool:
    """Detect OpenAI-compatible image parts that require a vision model."""
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"image_url", "input_image"}:
                return True
            if "image_url" in part:
                return True
    return False


def ai_cooldown_remaining() -> float:
    remaining = _ai_backoff_until - time.monotonic()
    return remaining if remaining > 0 else 0.0


def ai_is_temporarily_unavailable() -> bool:
    return ai_cooldown_remaining() > 0


def ai_unavailable_reason() -> str:
    return _ai_backoff_reason or "temporarily_unavailable"


def _provider_cooldown_remaining(index: int) -> float:
    until = _provider_backoff_until.get(index, 0.0)
    remaining = until - time.monotonic()
    return remaining if remaining > 0 else 0.0


# 0.8: Gemini — приоритетный провайдер для ВСЕХ запросов (и чат P.OS, и
# модерация). Остальные провайдеры из пула задействуются ТОЛЬКО когда все
# Gemini-провайдеры на cooldown. Если явно запрошен provider_type — он имеет
# наивысший приоритет; иначе предпочитаем "gemini".
PRIMARY_PROVIDER = "gemini"


def ai_provider_runtime_summary() -> str:
    """Return the effective provider order without credentials or endpoints."""
    configured = [
        provider
        for provider in _AI_PROVIDER_POOL
        if provider.get("api_key") and provider.get("model")
    ]
    configured.sort(
        key=lambda provider: provider.get("provider") != PRIMARY_PROVIDER
    )
    if not configured:
        return "not configured"

    routes: list[str] = []
    for provider in configured:
        provider_kind = re.sub(
            r"[^a-z0-9_.-]",
            "_",
            str(provider.get("provider") or "unknown").casefold(),
        )[:40]
        model = re.sub(
            r"[\x00-\x1f\x7f]+",
            " ",
            str(provider.get("model") or "unknown"),
        ).strip()[:120]
        routes.append(f"{provider_kind}:{model}")
    return ", ".join(routes)


def _pick_provider_index(provider_type: str | None = None) -> int | None:
    if not _AI_PROVIDER_POOL:
        return None
    total = len(_AI_PROVIDER_POOL)
    start = _provider_cursor % total

    # Порядок предпочтений по типу провайдера:
    # 1) явно запрошенный provider_type (если задан),
    # 2) Gemini как первичный провайдер,
    # 3) любой доступный — как запасной.
    preferred: list[str] = []
    if provider_type:
        preferred.append(provider_type)
    if PRIMARY_PROVIDER not in preferred:
        preferred.append(PRIMARY_PROVIDER)

    # Проходим тиры предпочтений: внутри каждого тира — round-robin от курсора.
    for wanted in preferred:
        for offset in range(total):
            idx = (start + offset) % total
            if _provider_cooldown_remaining(idx) <= 0 and _AI_PROVIDER_POOL[idx]["provider"] == wanted:
                return idx

    # Запасной тир: любой доступный (uncool) провайдер.
    for offset in range(total):
        idx = (start + offset) % total
        if _provider_cooldown_remaining(idx) <= 0:
            return idx

    return None


async def _reserve_provider_index(provider_type: str | None = None) -> int | None:
    """#14: Атомарно выбрать провайдера и сдвинуть курсор под локом."""
    global _provider_cursor
    async with _provider_lock:
        idx = _pick_provider_index(provider_type)
        if idx is not None:
            _provider_cursor = (idx + 1) % len(_AI_PROVIDER_POOL)
        return idx


async def _reserve_exact_provider_index(provider_type: str) -> int | None:
    """Reserve only the requested provider kind.

    Native provider APIs are not wire-compatible with the OpenAI-compatible
    fallback pool, so they must never silently spill over to another provider.
    """
    global _provider_cursor
    async with _provider_lock:
        if not _AI_PROVIDER_POOL:
            return None
        total = len(_AI_PROVIDER_POOL)
        start = _provider_cursor % total
        for offset in range(total):
            idx = (start + offset) % total
            provider = _AI_PROVIDER_POOL[idx]
            if (
                provider.get("provider") == provider_type
                and provider.get("api_key")
                and _provider_cooldown_remaining(idx) <= 0
            ):
                _provider_cursor = (idx + 1) % total
                return idx
        return None


async def _mark_provider_backoff(index: int, seconds: float) -> None:
    """#14: Атомарно продлить кулдаун провайдера под локом."""
    async with _provider_lock:
        _provider_backoff_until[index] = max(
            _provider_backoff_until.get(index, 0.0), time.monotonic() + seconds
        )


def _set_ai_backoff(seconds: float, reason: str) -> None:
    global _ai_backoff_until, _ai_backoff_reason
    cooldown = _bounded_float(seconds, 1.0, 1.0, 3600.0)
    _ai_backoff_until = max(_ai_backoff_until, time.monotonic() + cooldown)
    _ai_backoff_reason = reason


def _parse_retry_after(headers: Mapping[str, str]) -> float | None:
    if not headers:
        return None

    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            parsed_seconds = float(retry_after)
            if math.isfinite(parsed_seconds):
                return max(1.0, min(parsed_seconds, 3600.0))
        except ValueError:
            try:
                retry_dt = parsedate_to_datetime(retry_after)
                return max(1.0, min(retry_dt.timestamp() - time.time(), 3600.0))
            except Exception:
                pass

    reset_header = headers.get("x-ratelimit-reset")
    if reset_header:
        try:
            reset_at = float(reset_header)
            if math.isfinite(reset_at):
                return max(1.0, min(reset_at - time.time(), 3600.0))
        except ValueError:
            pass
    return None


def _looks_like_rate_limit(status: int, body_text: str, headers: Mapping[str, str]) -> bool:
    if status == 429:
        return True
    if status != 403:
        return False
    lowered = (body_text or "").lower()
    if "rate limit" in lowered or "too many requests" in lowered:
        return True
    remaining = headers.get("x-ratelimit-remaining")
    return remaining == "0"


def _log_ai_backoff_once(message: str) -> None:
    global _ai_last_backoff_log_at
    now = time.monotonic()
    if now - _ai_last_backoff_log_at < 15:
        return
    _ai_last_backoff_log_at = now
    logger.warning("%s", message)


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return max(minimum, min(parsed, maximum))


async def _read_bounded_response(response: aiohttp.ClientResponse) -> str:
    raw = await response.content.read(_MAX_UPSTREAM_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_UPSTREAM_RESPONSE_BYTES:
        raise ValueError("upstream response exceeds the configured size limit")
    encoding = response.charset or "utf-8"
    try:
        return raw.decode(encoding, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _message_from_choices(container: Mapping[str, Any]) -> dict[str, Any] | None:
    choices = container.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice0 = choices[0]
    if not isinstance(choice0, Mapping):
        return None
    for key in ("message", "delta"):
        message = choice0.get(key)
        if isinstance(message, Mapping) and message:
            return dict(message)
    text = choice0.get("text")
    if isinstance(text, str) and text.strip():
        return {"role": "assistant", "content": text.strip()}
    return None


def _message_from_gemini_candidates(data: Mapping[str, Any]) -> dict[str, Any] | None:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    candidate = candidates[0]
    if not isinstance(candidate, Mapping):
        return None
    content = candidate.get("content")
    if not isinstance(content, Mapping):
        return None
    parts = content.get("parts")
    if not isinstance(parts, list):
        return None

    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for index, part in enumerate(parts, start=1):
        if not isinstance(part, Mapping):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            text_parts.append(text.strip())
        function_call = part.get("functionCall") or part.get("function_call")
        if not isinstance(function_call, Mapping):
            continue
        name = str(function_call.get("name") or "").strip()
        if not name:
            continue
        arguments = function_call.get("args", function_call.get("arguments", {}))
        tool_calls.append(
            {
                "id": f"gemini-call-{index}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": (
                        arguments
                        if isinstance(arguments, str)
                        else json.dumps(arguments, ensure_ascii=False)
                    ),
                },
            }
        )
    if not text_parts and not tool_calls:
        return None
    message: dict[str, Any] = {
        "role": str(content.get("role") or "assistant"),
        "content": "\n".join(text_parts),
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _message_from_responses_output(data: Mapping[str, Any]) -> dict[str, Any] | None:
    output = data.get("output")
    if not isinstance(output, list):
        return None
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for index, item in enumerate(output, start=1):
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if item_type in {"function_call", "tool_call"}:
            name = str(item.get("name") or "").strip()
            if name:
                tool_calls.append(
                    {
                        "id": str(item.get("call_id") or item.get("id") or f"response-call-{index}"),
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": item.get("arguments", "{}"),
                        },
                    }
                )
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())
    if not text_parts and not tool_calls:
        return None
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(text_parts),
    }
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def _extract_message_from_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    direct_message = data.get("message")
    if isinstance(direct_message, Mapping) and direct_message:
        return dict(direct_message)

    message = _message_from_choices(data)
    if message:
        return message

    result = data.get("result")
    if isinstance(result, Mapping):
        message = _message_from_choices(result)
        if message:
            return message

    message = _message_from_gemini_candidates(data)
    if message:
        return message

    message = _message_from_responses_output(data)
    if message:
        return message

    text = data.get("output_text") or data.get("generated_text")
    if isinstance(text, list):
        parts = []
        for item in text:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        text = "\n".join(part for part in parts if part).strip()

    if isinstance(text, str):
        return {"role": "assistant", "content": text.strip()}

    return None


def _response_shape_summary(data: Mapping[str, Any]) -> str:
    root_keys = sorted(str(key) for key in data.keys())[:12]
    details = ["keys=" + ",".join(root_keys)]
    choices = data.get("choices")
    if isinstance(choices, list):
        details.append(f"choices={len(choices)}")
        if choices and isinstance(choices[0], Mapping):
            finish_reason = choices[0].get("finish_reason")
            if finish_reason is not None:
                details.append(f"finish={str(finish_reason)[:40]}")
    candidates = data.get("candidates")
    if isinstance(candidates, list):
        details.append(f"candidates={len(candidates)}")
        if candidates and isinstance(candidates[0], Mapping):
            finish_reason = candidates[0].get("finishReason")
            if finish_reason is not None:
                details.append(f"finish={str(finish_reason)[:40]}")
    return ";".join(details)[:300]


def _upstream_body_fingerprint(body: str) -> str:
    return hashlib.sha256((body or "").encode("utf-8", errors="replace")).hexdigest()[:16]


def _gemini_generate_content_url(provider: Mapping[str, str]) -> str | None:
    """Build a native Gemini generateContent URL from a configured pool entry."""
    api_url = provider.get("api_url", "")
    model = provider.get("model", "").strip()
    try:
        parsed = urlsplit(api_url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if not (host == "googleapis.com" or host.endswith(".googleapis.com")):
        return None
    if parsed.scheme != "https" or not model:
        return None

    if model.startswith("models/"):
        model = model[len("models/"):]
    if model.startswith("google/"):
        model = model[len("google/"):]
    if not model or len(model) > 160:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    api_version = next(
        (part for part in path_parts if re.fullmatch(r"v\d+(?:alpha|beta)?", part)),
        "v1beta",
    )
    netloc = parsed.netloc
    return (
        f"https://{netloc}/{api_version}/models/"
        f"{quote(model, safe='._-')}:generateContent"
    )


def _gemini_interactions_url(provider: Mapping[str, str]) -> str | None:
    """Build the current Gemini Interactions endpoint for a Gemini provider."""
    api_url = provider.get("api_url", "")
    try:
        parsed = urlsplit(api_url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not (
        host == "googleapis.com" or host.endswith(".googleapis.com")
    ):
        return None
    path_parts = [part for part in parsed.path.split("/") if part]
    api_version = next(
        (part for part in path_parts if re.fullmatch(r"v\d+(?:alpha|beta)?", part)),
        "v1beta",
    )
    return f"https://{parsed.netloc}/{api_version}/interactions"


def _extract_gemini_text(data: Mapping[str, Any]) -> str | None:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return None
    parts: list[str] = []
    for candidate in candidates[:1]:
        if not isinstance(candidate, Mapping):
            continue
        content = candidate.get("content")
        if not isinstance(content, Mapping):
            continue
        raw_parts = content.get("parts")
        if not isinstance(raw_parts, list):
            continue
        for part in raw_parts:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                text = str(part["text"]).strip()
                if text:
                    parts.append(text)
    combined = "\n".join(parts).strip()
    return combined or None


def _extract_interaction_text(data: Mapping[str, Any]) -> str | None:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    steps = data.get("steps")
    if not isinstance(steps, list):
        return None
    parts: list[str] = []
    for step in steps:
        if not isinstance(step, Mapping) or step.get("type") != "model_output":
            continue
        content = step.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if (
                isinstance(item, Mapping)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                text = str(item["text"]).strip()
                if text:
                    parts.append(text)
    combined = "\n".join(parts).strip()
    return combined or None


async def pos_gemini_media_analysis(
    media_bytes: bytes,
    mime_type: str,
    *,
    prompt: str,
    max_tokens: int = 1800,
    timeout: int = 90,
) -> str | None:
    """Analyze one bounded audio/video payload through Gemini's native API.

    The OpenAI-compatible endpoint used by regular chat cannot reliably carry
    audio and video across providers. This path intentionally selects Gemini
    entries only and never falls back to an incompatible provider.
    """
    if (
        not isinstance(media_bytes, bytes)
        or not media_bytes
        or len(media_bytes) > _MAX_INLINE_MEDIA_BYTES
    ):
        return None
    normalized_mime = (mime_type or "").strip().lower().split(";", 1)[0]
    if not normalized_mime.startswith(("audio/", "video/")):
        return None
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        return None

    encoded = await asyncio.to_thread(base64.b64encode, media_bytes)
    encoded_text = encoded.decode("ascii")
    request_timeout = _bounded_int(timeout, 90, 10, 180)
    request_max_tokens = _bounded_int(max_tokens, 1800, 64, 8192)
    global _missing_media_provider_logged
    gemini_count = sum(
        1
        for provider in _AI_PROVIDER_POOL
        if provider.get("provider") == "gemini" and provider.get("api_key")
    )
    if gemini_count == 0:
        if not _missing_media_provider_logged:
            logger.warning(
                "Native audio/video analysis is unavailable: no authenticated Gemini provider."
            )
            _missing_media_provider_logged = True
        return None

    attempted: set[int] = set()
    for _attempt in range(gemini_count):
        provider_index: int | None = None
        provider: dict[str, str] | None = None
        try:
            async with _request_slot(request_timeout):
                provider_index = await _reserve_exact_provider_index("gemini")
                if provider_index is None or provider_index in attempted:
                    return None
                attempted.add(provider_index)
                provider = _AI_PROVIDER_POOL[provider_index]
                generate_endpoint = _gemini_generate_content_url(provider)
                if generate_endpoint is None:
                    await _mark_provider_backoff(provider_index, 300.0)
                    continue

                generate_payload = {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "inline_data": {
                                        "mime_type": normalized_mime,
                                        "data": encoded_text,
                                    }
                                },
                                {"text": clean_prompt},
                            ],
                        }
                    ],
                    "generation_config": {
                        "temperature": 0.1,
                        "max_output_tokens": request_max_tokens,
                    },
                }
                request_variants: list[tuple[str, str, dict[str, Any]]] = []
                interactions_endpoint = _gemini_interactions_url(provider)
                if interactions_endpoint is not None:
                    model = provider["model"].strip()
                    if model.startswith("models/"):
                        model = model[len("models/"):]
                    if model.startswith("google/"):
                        model = model[len("google/"):]
                    media_type = (
                        "audio"
                        if normalized_mime.startswith("audio/")
                        else "video"
                    )
                    request_variants.append(
                        (
                            "interactions",
                            interactions_endpoint,
                            {
                                "model": model,
                                "input": [
                                    {
                                        "type": media_type,
                                        "data": encoded_text,
                                        "mime_type": normalized_mime,
                                    },
                                    {
                                        "type": "text",
                                        "text": clean_prompt,
                                    },
                                ],
                                "store": False,
                                "generation_config": {
                                    "max_output_tokens": request_max_tokens,
                                    "thinking_level": "low",
                                },
                            },
                        )
                    )
                request_variants.append(
                    ("generateContent", generate_endpoint, generate_payload)
                )
                headers = {
                    "x-goog-api-key": provider["api_key"],
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                timeout_config = aiohttp.ClientTimeout(total=request_timeout)
                connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
                async with aiohttp.ClientSession(
                    timeout=timeout_config,
                    connector=connector,
                    trust_env=False,
                ) as session:
                    for api_kind, endpoint, payload in request_variants:
                        async with session.post(
                            endpoint,
                            headers=headers,
                            json=payload,
                            allow_redirects=False,
                        ) as resp:
                            response_text = await _read_bounded_response(resp)
                            if 200 <= resp.status < 300:
                                try:
                                    data = json.loads(response_text)
                                except (TypeError, json.JSONDecodeError):
                                    continue
                                result = (
                                    _extract_interaction_text(data)
                                    if api_kind == "interactions"
                                    else _extract_gemini_text(data)
                                )
                                if result:
                                    return result
                                continue

                            # Interactions is the preferred modern audio path,
                            # but older models/accounts may not expose it yet.
                            # A compatibility rejection falls through to the
                            # existing generateContent request on the same key.
                            if (
                                api_kind == "interactions"
                                and resp.status in {400, 404, 405, 422}
                            ):
                                continue
                            if _looks_like_rate_limit(
                                resp.status,
                                response_text,
                                resp.headers,
                            ):
                                retry_after = (
                                    _parse_retry_after(resp.headers)
                                    or POS_AI_RATE_LIMIT_FALLBACK_SECONDS
                                )
                                await _mark_provider_backoff(
                                    provider_index,
                                    retry_after,
                                )
                                break
                            if resp.status >= 500:
                                await _mark_provider_backoff(
                                    provider_index,
                                    15.0,
                                )
                                break
                            if 300 <= resp.status < 400:
                                await _mark_provider_backoff(
                                    provider_index,
                                    300.0,
                                )
                                break
                            if resp.status in {401, 403}:
                                await _mark_provider_backoff(
                                    provider_index,
                                    3600.0,
                                )
                            logger.warning(
                                "P.OS Gemini media API error %s/%s (%s), body_sha256=%s",
                                api_kind,
                                resp.status,
                                provider["name"],
                                _upstream_body_fingerprint(response_text),
                            )
                            break
        except _AIQueueTimeout:
            return None
        except (asyncio.TimeoutError, TimeoutError):
            if provider_index is not None:
                await _mark_provider_backoff(provider_index, 15.0)
            continue
        except Exception as exc:
            if provider_index is not None:
                await _mark_provider_backoff(provider_index, 60.0)
            logger.warning(
                "P.OS Gemini media request failed (%s): %s",
                provider["name"] if provider else "unknown",
                type(exc).__name__,
            )
            continue

    return None


async def pos_chat_completion(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
    max_tokens: int = POS_AI_MAX_TOKENS,
    temperature: float = POS_AI_TEMPERATURE,
    top_p: float = POS_AI_TOP_P,
    timeout: int = POS_AI_TIMEOUT_SECONDS,
    provider_type: str | None = None,
) -> dict[str, Any] | None:
    if not ai_has_configured_provider():
        return None

    request_max_tokens = _bounded_int(max_tokens, POS_AI_MAX_TOKENS, 1, 32_768)
    request_temperature = _bounded_float(temperature, POS_AI_TEMPERATURE, 0.0, 2.0)
    request_top_p = _bounded_float(top_p, POS_AI_TOP_P, 0.0, 1.0)
    request_timeout = _bounded_int(timeout, POS_AI_TIMEOUT_SECONDS, 5, 300)
    request_tool_choice = (
        tool_choice
        if isinstance(tool_choice, str) and tool_choice in _SUPPORTED_TOOL_CHOICES
        else None
    )
    requires_vision = _messages_have_visual_inputs(messages)
    if requires_vision:
        max_attempts = sum(
            1
            for provider in _AI_PROVIDER_POOL
            if provider.get("provider") == "gemini" and provider.get("api_key")
        )
        if max_attempts == 0:
            logger.warning(
                "P.OS vision request skipped: no authenticated Gemini provider."
            )
            return None
    else:
        max_attempts = len(_AI_PROVIDER_POOL)

    for attempt in range(max_attempts):
        response_text = ""
        provider_index: int | None = None
        provider: dict[str, str] | None = None
        try:
            async with _request_slot(request_timeout):
                if ai_is_temporarily_unavailable():
                    _log_ai_backoff_once(
                        f"P.OS AI cooldown active: {ai_unavailable_reason()} ({ai_cooldown_remaining():.0f}s remaining)."
                    )
                    return None

                provider_index = (
                    await _reserve_exact_provider_index("gemini")
                    if requires_vision
                    else await _reserve_provider_index(provider_type)
                )
                if provider_index is None:
                    eligible_indices = [
                        index
                        for index, candidate in enumerate(_AI_PROVIDER_POOL)
                        if not requires_vision
                        or candidate.get("provider") == "gemini"
                    ]
                    shortest = min(
                        (
                            _provider_cooldown_remaining(index)
                            for index in eligible_indices
                        ),
                        default=5.0,
                    )
                    _set_ai_backoff(shortest, "all_providers_rate_limited")
                    _log_ai_backoff_once(
                        f"P.OS AI provider pool cooldown: all providers limited, retry in {shortest:.0f}s."
                    )
                    return None

                provider = _AI_PROVIDER_POOL[provider_index]

                accept_header = "application/vnd.github+json" if provider["provider"] == "github_models" else "application/json"
                payload = {
                    "messages": messages,
                    "model": provider["model"],
                    "max_tokens": request_max_tokens,
                    "temperature": request_temperature,
                    "top_p": request_top_p,
                    "stream": False,
                }
                if "googleapis.com" not in provider["api_url"] and provider["provider"] != "gemini":
                    payload["frequency_penalty"] = 0.35
                    payload["presence_penalty"] = 0.2
                if tools:
                    payload["tools"] = tools
                    if request_tool_choice:
                        payload["tool_choice"] = request_tool_choice
                headers = {
                    "Authorization": f"Bearer {provider['api_key']}",
                    "Content-Type": "application/json",
                    "Accept": accept_header,
                }
                if provider["provider"] == "github_models":
                    headers["X-GitHub-Api-Version"] = GITHUB_MODELS_API_VERSION

                timeout_config = aiohttp.ClientTimeout(total=request_timeout)
                connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
                async with aiohttp.ClientSession(
                    timeout=timeout_config,
                    connector=connector,
                    trust_env=False,
                ) as session:
                    async with session.post(
                        provider["api_url"],
                        headers=headers,
                        json=payload,
                        allow_redirects=False,
                    ) as resp:
                        response_text = await _read_bounded_response(resp)
                        if _looks_like_rate_limit(resp.status, response_text, resp.headers):
                            retry_after = _parse_retry_after(resp.headers) or POS_AI_RATE_LIMIT_FALLBACK_SECONDS
                            await _mark_provider_backoff(provider_index, retry_after)
                            _log_ai_backoff_once(
                                f"P.OS API rate limited ({provider['name']}): pause for {retry_after:.0f}s."
                            )
                            # Только проверяем наличие свободного провайдера — резерв
                            # выполнит следующая итерация цикла (иначе курсор
                            # сдвигался дважды и провайдеры пропускались).
                            if attempt < max_attempts - 1:
                                continue  # retry next provider
                            _set_ai_backoff(min(retry_after, 30.0), "rate_limited")
                            return None

                        if resp.status >= 500:
                            await _mark_provider_backoff(provider_index, 8.0)
                            logger.warning(
                                "P.OS upstream error %s (%s), body_sha256=%s",
                                resp.status,
                                provider["name"],
                                _upstream_body_fingerprint(response_text),
                            )
                            if attempt < max_attempts - 1:
                                continue  # retry next provider
                            _set_ai_backoff(5.0, "upstream_error")
                            return None

                        if 300 <= resp.status < 400:
                            await _mark_provider_backoff(provider_index, 300.0)
                            logger.warning(
                                "P.OS AI endpoint returned an unexpected redirect (%s, %s).",
                                resp.status,
                                provider["name"],
                            )
                            if attempt < max_attempts - 1:
                                continue
                            return None

                        if resp.status >= 400:
                            if provider["provider"] == "github_models" and resp.status in {401, 403}:
                                logger.error("P.OS GitHub Models authentication failed.")
                            logger.warning(
                                "P.OS API error %s (%s), body_sha256=%s",
                                resp.status,
                                provider["name"],
                                _upstream_body_fingerprint(response_text),
                            )
                            # 400/413/422 are request-specific and must not take a
                            # healthy provider out of rotation. Auth and endpoint
                            # failures are provider-specific and do get cooldowns.
                            if resp.status in {401, 403}:
                                await _mark_provider_backoff(provider_index, 3600.0)
                            elif resp.status == 404:
                                await _mark_provider_backoff(provider_index, 300.0)
                            elif resp.status in {408, 409, 425}:
                                await _mark_provider_backoff(provider_index, 10.0)
                            if attempt < max_attempts - 1:
                                continue
                            return None
        except _AIQueueTimeout:
            _log_ai_backoff_once("P.OS AI queue is full; request rejected before provider call.")
            return None
        except asyncio.TimeoutError:
            name = provider["name"] if provider else "unknown"
            logger.warning("P.OS API timeout for %s; attempting fallback.", name)
            if attempt < max_attempts - 1:
                continue
            return None
        except Exception as exc:
            # provider_index может быть не присвоен, если исключение случилось до
            # выбора провайдера — иначе тут вылетал NameError вместо возврата None.
            if provider_index is not None:
                exc_str = str(exc).lower()
                if "rate" in exc_str or "limit" in exc_str or "quota" in exc_str:
                    await _mark_provider_backoff(provider_index, 20.0)
                else:
                    await _mark_provider_backoff(provider_index, 60.0)
            name = provider["name"] if provider else "unknown"
            logger.warning(
                "P.OS API request failed (%s, %s); attempting fallback.",
                name,
                type(exc).__name__,
            )
            if attempt < max_attempts - 1:
                continue
            return None

        # Success
        try:
            data = json.loads(response_text)
        except Exception:
            logger.warning(
                "P.OS API returned non-JSON: body_sha256=%s",
                _upstream_body_fingerprint(response_text),
            )
            return None

        msg = _extract_message_from_payload(data)
        if not msg:
            logger.warning(
                "P.OS API response had no message: body_sha256=%s shape=%s",
                _upstream_body_fingerprint(response_text),
                _response_shape_summary(data),
            )
            return None
        return msg

    return None


def extract_json_block(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    candidates = [raw]
    if "```" in raw:
        parts = raw.split("```")
        candidates.extend(part.strip() for part in parts if part.strip())

    for candidate in candidates:
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", candidate):
            try:
                parsed, _end = decoder.raw_decode(candidate[match.start():])
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return None
