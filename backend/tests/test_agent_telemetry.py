"""Privacy-safe usage and timing telemetry tests for provider calls."""

import json
from uuid import uuid4

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.services.agent_telemetry import (
    AgentRunTelemetry,
    capture_agent_run,
    bind_request_id,
    observed_async_client,
    request_id_middleware,
)


@pytest.mark.anyio
async def test_request_middleware_returns_and_binds_correlation_id() -> None:
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/health",
            "raw_path": b"/health",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 123),
            "server": ("testserver", 80),
        }
    )
    telemetry: AgentRunTelemetry | None = None

    async def call_next(inner_request: Request) -> Response:
        nonlocal telemetry
        assert inner_request.state.request_id
        telemetry = AgentRunTelemetry(run_id=uuid4())
        return Response("ok")

    response = await request_id_middleware(request, call_next)
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request.state.request_id
    assert telemetry is not None
    assert telemetry.summary()["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.anyio
async def test_observed_client_records_usage_cost_and_not_prompt_content() -> None:
    settings = Settings(
        _env_file=None,
        llm_input_usd_per_million_tokens=5,
        llm_output_usd_per_million_tokens=10,
        embedding_input_usd_per_million_tokens=2,
    )

    async def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            body = {"usage": {"prompt_tokens": 8, "total_tokens": 8}, "data": []}
        else:
            body = {
                "model": "model-a",
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                "choices": [],
            }
        return httpx.Response(200, json=body, request=request)

    with bind_request_id("request-123"):
        telemetry = AgentRunTelemetry(run_id=uuid4())
    async with observed_async_client(
        settings,
        timeout=2,
        transport=httpx.MockTransport(provider),
    ) as client:
        with capture_agent_run(telemetry):
            await client.post(
                "https://model.example/v1/chat/completions",
                json={
                    "model": "model-a",
                    "messages": [{"role": "user", "content": "private resume text"}],
                },
            )
            await client.post(
                "https://model.example/v1/embeddings",
                json={"model": "embedding-a", "input": ["private resume text"]},
            )

    summary = telemetry.summary()
    assert summary["request_id"] == "request-123"
    assert summary["provider_call_count"] == 2
    assert summary["prompt_tokens"] == 108
    assert summary["completion_tokens"] == 50
    assert summary["total_tokens"] == 158
    assert summary["token_usage_complete"] is True
    assert summary["estimated_cost_usd"] == pytest.approx(0.001016)
    assert all(call["duration_ms"] >= 0 for call in summary["calls"])
    serialized = json.dumps(summary)
    assert "private resume text" not in serialized
    assert "authorization" not in serialized.lower()


@pytest.mark.anyio
async def test_observed_client_records_transport_failure_without_request_data() -> None:
    settings = Settings(_env_file=None)

    async def provider(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    telemetry = AgentRunTelemetry(run_id=uuid4())
    async with observed_async_client(
        settings,
        timeout=2,
        transport=httpx.MockTransport(provider),
    ) as client:
        with capture_agent_run(telemetry):
            with pytest.raises(httpx.ConnectError):
                await client.post(
                    "https://model.example/v1/chat/completions",
                    json={
                        "model": "model-a",
                        "messages": [{"role": "user", "content": "private request"}],
                    },
                )

    summary = telemetry.summary()
    assert summary["provider_call_count"] == 1
    assert summary["calls"][0]["outcome"] == "transport_error"
    assert summary["calls"][0]["duration_ms"] >= 0
    assert "private request" not in json.dumps(summary)


@pytest.mark.anyio
async def test_observed_client_estimates_configured_search_cost() -> None:
    settings = Settings(_env_file=None, tavily_usd_per_search=0.004)

    async def provider(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []}, request=request)

    telemetry = AgentRunTelemetry(run_id=uuid4())
    async with observed_async_client(
        settings,
        timeout=2,
        transport=httpx.MockTransport(provider),
    ) as client:
        with capture_agent_run(telemetry):
            await client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": "Bearer test-secret"},
                json={"query": "private company query"},
            )

    summary = telemetry.summary()
    assert summary["provider_call_count"] == 1
    assert summary["estimated_cost_usd"] == pytest.approx(0.004)
    assert summary["cost_estimate_complete"] is True
    assert summary["calls"][0]["operation"] == "web_search"
    assert "private company query" not in json.dumps(summary)
    assert "test-secret" not in json.dumps(summary)
