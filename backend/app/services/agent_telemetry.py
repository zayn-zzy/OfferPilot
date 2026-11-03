"""Privacy-safe per-run timing and provider usage capture."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
import json
import time
from typing import Awaitable, Callable, Iterator
from uuid import UUID, uuid4

import httpx
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings

_STARTED_AT = "offerpilot_agent_started_at"
_CURRENT_RUN: ContextVar[AgentRunTelemetry | None] = ContextVar(
    "offerpilot_agent_telemetry", default=None
)
_CURRENT_REQUEST_ID: ContextVar[str | None] = ContextVar(
    "offerpilot_request_id", default=None
)


@dataclass
class AgentRunTelemetry:
    """Collect provider metadata without retaining request or response text."""

    run_id: UUID
    started_at: float = field(default_factory=time.perf_counter)
    calls: list[dict[str, object]] = field(default_factory=list)
    request_id: str | None = field(default_factory=_CURRENT_REQUEST_ID.get)

    def summary(self) -> dict[str, object]:
        no_calls = not self.calls
        prompt_values = [
            call["prompt_tokens"]
            for call in self.calls
            if call["prompt_tokens"] is not None
        ]
        completion_values = [
            call["completion_tokens"]
            for call in self.calls
            if call["completion_tokens"] is not None
        ]
        costs = [call["estimated_cost_usd"] for call in self.calls]
        return {
            "run_id": str(self.run_id),
            "request_id": self.request_id,
            "duration_ms": max(0, round((time.perf_counter() - self.started_at) * 1000)),
            "provider_call_count": len(self.calls),
            "prompt_tokens": sum(prompt_values) if prompt_values else (0 if no_calls else None),
            "completion_tokens": (
                sum(completion_values) if completion_values else (0 if no_calls else None)
            ),
            "total_tokens": (
                0
                if no_calls
                else sum(int(call["total_tokens"]) for call in self.calls)
                if all(call["total_tokens"] is not None for call in self.calls)
                else None
            ),
            "token_usage_complete": no_calls
            or all(call["total_tokens"] is not None for call in self.calls),
            "estimated_cost_usd": (
                round(sum(float(cost) for cost in costs), 10)
                if costs and all(cost is not None for cost in costs)
                else (0.0 if no_calls else None)
            ),
            "cost_estimate_complete": no_calls or all(cost is not None for cost in costs),
            "calls": list(self.calls),
        }


@contextmanager
def capture_agent_run(telemetry: AgentRunTelemetry) -> Iterator[None]:
    """Bind a collector to the current async context for one graph dispatch."""

    token: Token[AgentRunTelemetry | None] = _CURRENT_RUN.set(telemetry)
    try:
        yield
    finally:
        _CURRENT_RUN.reset(token)


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    """Bind a generated request ID so nested workflow calls can record it."""

    token = _CURRENT_REQUEST_ID.set(request_id)
    try:
        yield
    finally:
        _CURRENT_REQUEST_ID.reset(token)


async def request_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Generate a response-visible correlation ID and bind it to this request."""

    request_id = str(uuid4())
    request.state.request_id = request_id
    with bind_request_id(request_id):
        response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _request_metadata(request: httpx.Request) -> tuple[str, str, str | None]:
    path = request.url.path.lower()
    host = request.url.host.lower()
    try:
        payload = json.loads(request.content)
    except (ValueError, TypeError):
        payload = {}
    model = payload.get("model") if isinstance(payload, dict) else None
    if "embeddings" in path:
        return "openai_compatible", "embeddings", model if isinstance(model, str) else None
    if "chat/completions" in path:
        return "openai_compatible", "chat_completions", model if isinstance(model, str) else None
    if "tavily" in host or path.endswith("/search"):
        return "tavily", "web_search", None
    return "external_http", path.rsplit("/", 1)[-1] or "request", None


def _estimate_cost(
    settings: Settings,
    operation: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> float | None:
    if operation == "embeddings":
        rate = settings.embedding_input_usd_per_million_tokens
        if rate is None or prompt_tokens is None:
            return None
        return prompt_tokens * rate / 1_000_000
    if operation == "chat_completions":
        input_rate = settings.llm_input_usd_per_million_tokens
        output_rate = settings.llm_output_usd_per_million_tokens
        if input_rate is None or output_rate is None:
            return None
        if prompt_tokens is None or completion_tokens is None:
            return None
        return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
    if operation == "web_search":
        return settings.tavily_usd_per_search
    return None


def _record_call(
    request: httpx.Request,
    settings: Settings,
    *,
    duration_ms: int,
    outcome: str,
    usage: dict[str, object] | None = None,
) -> None:
    collector = _CURRENT_RUN.get()
    if collector is None:
        return
    provider, operation, request_model = _request_metadata(request)
    usage = usage or {}
    prompt_tokens = _nonnegative_integer(
        usage.get("prompt_tokens", usage.get("input_tokens"))
    )
    completion_tokens = _nonnegative_integer(
        usage.get("completion_tokens", usage.get("output_tokens"))
    )
    total_tokens = _nonnegative_integer(usage.get("total_tokens"))
    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
    collector.calls.append(
        {
            "provider": provider,
            "operation": operation,
            "model": request_model,
            "duration_ms": duration_ms,
            "outcome": outcome,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": (
                round(
                    cost,
                    10,
                )
                if (cost := _estimate_cost(settings, operation, prompt_tokens, completion_tokens))
                is not None
                else None
            ),
        }
    )


class _ObservedTransport(httpx.AsyncBaseTransport):
    """Record failed transport calls; successful responses are observed by a hook."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        self._settings = settings
        self._transport = transport or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started_at = time.perf_counter()
        request.extensions[_STARTED_AT] = started_at
        try:
            return await self._transport.handle_async_request(request)
        except Exception:
            try:
                _record_call(
                    request,
                    self._settings,
                    duration_ms=max(0, round((time.perf_counter() - started_at) * 1000)),
                    outcome="transport_error",
                )
            except Exception:
                pass
            raise

    async def aclose(self) -> None:
        await self._transport.aclose()


def observed_async_client(
    settings: Settings,
    *,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Build an HTTPX client that records only timings, token usage, and estimates."""

    observed_transport = _ObservedTransport(settings, transport)

    async def record_response(response: httpx.Response) -> None:
        if _CURRENT_RUN.get() is None:
            return
        usage = None
        try:
            await response.aread()
            body = response.json()
            response_usage = body.get("usage") if isinstance(body, dict) else None
            usage = response_usage if isinstance(response_usage, dict) else None
        except Exception:
            # Keep the call timing even when a provider returned non-JSON content.
            pass
        try:
            start = response.request.extensions.get(
                _STARTED_AT, time.perf_counter()
            )
            _record_call(
                response.request,
                settings,
                duration_ms=max(0, round((time.perf_counter() - float(start)) * 1000)),
                outcome="success" if response.status_code < 400 else "http_error",
                usage=usage,
            )
        except Exception:
            # Telemetry is best-effort and must never change provider behavior.
            return

    return httpx.AsyncClient(
        timeout=timeout,
        transport=observed_transport,
        event_hooks={"response": [record_response]},
    )
