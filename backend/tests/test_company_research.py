"""MCP company research tests with deterministic providers and no network calls."""

from collections.abc import AsyncGenerator, Generator
import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, MockTransport, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

from app.core.config import Settings
from app.main import create_app
from app.models import AgentRun, Base
from app.services.company_research import (
    CompanyResearchDraft,
    CompanyResearchError,
    CompanyResearchFindingCandidate,
    OpenAICompatibleCompanyResearchSummarizer,
    PublicSearchSource,
    TavilySearchProvider,
    call_company_search_tool,
    create_company_research_mcp_server,
    validate_research_findings,
)


def make_sources() -> list[PublicSearchSource]:
    return [
        PublicSearchSource(
            source_id="web-1",
            title="星河科技校园招聘",
            url="https://careers.example.com/campus",
            excerpt="星河科技 2027 届校园招聘已启动，招聘方向包含后端开发工程师。",
            age="2 days ago",
        ),
        PublicSearchSource(
            source_id="web-2",
            title="星河科技官网",
            url="https://www.example.com/about",
            excerpt="星河科技专注于云服务与企业软件。",
        ),
    ]


class FakePublicSearchProvider:
    def __init__(self, *, fail: bool = False, empty: bool = False) -> None:
        self.fail = fail
        self.empty = empty
        self.queries: list[str] = []

    async def search(self, query: str, count: int, settings: Settings):
        self.queries.append(query)
        assert count <= 10
        if self.fail:
            raise CompanyResearchError("research_rate_limited", "公开搜索服务请求过于频繁。")
        return [] if self.empty else make_sources()


class FakeResearchSummarizer:
    def __init__(self, *, invalid_quote: bool = False, fail: bool = False) -> None:
        self.invalid_quote = invalid_quote
        self.fail = fail

    async def summarize(self, company_name, job_title, query, sources, settings):
        if self.fail:
            raise CompanyResearchError(
                "research_summary_timeout", "公司研究摘要模型响应超时。"
            )
        quote = "星河科技 2027 届校园招聘已启动"
        if self.invalid_quote:
            quote = "原文中没有的招聘结论"
        return (
            CompanyResearchDraft(
                findings=[
                    CompanyResearchFindingCandidate(
                        claim="搜索结果提到星河科技已启动 2027 届校园招聘。",
                        source_id="web-1",
                        quote=quote,
                    ),
                    CompanyResearchFindingCandidate(
                        claim="模型尝试引用不存在的来源。",
                        source_id="not-in-results",
                        quote="虚构内容",
                    ),
                ]
            ),
            "test-chat-model",
        )


@pytest.fixture
def test_app(tmp_path: Path) -> Generator[FastAPI, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite://",
        secret_key="company-research-test-secret-long-enough",
        allowed_origins=["http://localhost:3000"],
        storage_dir=tmp_path / "storage",
        tavily_api_key="test-search-key",
    )
    search_provider = FakePublicSearchProvider()
    summarizer = FakeResearchSummarizer()
    app = create_app(
        settings,
        factory,
        company_research_search_provider=search_provider,
        company_research_summarizer=summarizer,
    )
    app.state.fake_search_provider = search_provider
    app.state.fake_research_summarizer = summarizer
    yield app
    engine.dispose()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://testserver"
    ) as test_client:
        yield test_client


async def register(client: AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201


async def create_job(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/jobs",
        json={
            "company_name": "星河科技",
            "title": "后端开发工程师",
            "recruitment_url": "https://careers.example.com/campus",
            "source_type": "manual",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.anyio
async def test_company_research_calls_mcp_and_persists_verified_findings(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "research-owner@example.com")
    job = await create_job(client)

    response = await client.post(f"/api/v1/jobs/{job['id']}/research")
    assert response.status_code == 200
    body = response.json()
    assert body["company_name"] == "星河科技"
    assert body["findings"] == [
        {
            "claim": "搜索结果提到星河科技已启动 2027 届校园招聘。",
            "source_id": "web-1",
            "quote": "星河科技 2027 届校园招聘已启动",
        }
    ]
    assert len(body["sources"]) == 2
    assert '"星河科技"' in test_app.state.fake_search_provider.queries[0]
    assert "后端开发工程师" in test_app.state.fake_search_provider.queries[0]

    with test_app.state.session_factory() as session:
        run = session.scalar(
            select(AgentRun).where(
                AgentRun.user_id.is_not(None), AgentRun.task_type == "company_research"
            )
        )
        assert run is not None
        assert run.status == "succeeded"
        assert run.model_name == "test-chat-model"
        assert run.result["search_provider"] == "tavily_search"

    restored = await client.get(f"/api/v1/jobs/{job['id']}/research")
    assert restored.status_code == 200
    assert restored.json()["run_id"] == body["run_id"]


@pytest.mark.anyio
async def test_research_cache_avoids_repeat_search_until_forced_refresh(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "research-cache@example.com")
    job = await create_job(client)
    first = await client.post(f"/api/v1/jobs/{job['id']}/research")
    cached = await client.post(f"/api/v1/jobs/{job['id']}/research")
    refreshed = await client.post(f"/api/v1/jobs/{job['id']}/research?refresh=true")

    assert first.status_code == cached.status_code == refreshed.status_code == 200
    assert first.json()["run_id"] == cached.json()["run_id"]
    assert refreshed.json()["run_id"] != first.json()["run_id"]
    assert len(test_app.state.fake_search_provider.queries) == 2


@pytest.mark.anyio
async def test_company_research_drops_unverifiable_findings_and_exposes_warning(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "research-evidence@example.com")
    job = await create_job(client)
    test_app.state.company_research_summarizer = FakeResearchSummarizer(invalid_quote=True)

    response = await client.post(f"/api/v1/jobs/{job['id']}/research")
    assert response.status_code == 200
    body = response.json()
    assert body["no_evidence"] is True
    assert body["findings"] == []
    assert len(body["sources"]) == 2
    assert "可核验" in body["summary"]


@pytest.mark.anyio
async def test_research_provider_failure_is_visible_and_persisted(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "research-failure@example.com")
    job = await create_job(client)
    test_app.state.company_research_search_provider = FakePublicSearchProvider(fail=True)
    from app.services.company_research import create_company_research_mcp_server

    test_app.state.company_research_mcp_server = create_company_research_mcp_server(
        test_app.state.settings, test_app.state.company_research_search_provider
    )

    response = await client.post(f"/api/v1/jobs/{job['id']}/research")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "research_rate_limited"
    with test_app.state.session_factory() as session:
        run = session.scalar(
            select(AgentRun).where(AgentRun.task_type == "company_research")
        )
        assert run is not None and run.status == "failed"
        assert run.error_code == "research_rate_limited"


@pytest.mark.anyio
async def test_company_research_limits_provider_calls_per_user(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "research-throttle@example.com")
    job = await create_job(client)
    with test_app.state.session_factory() as session:
        runs = session.scalars(select(AgentRun).where(AgentRun.task_type == "company_research")).all()
        user_id = runs[0].user_id if runs else None
        if user_id is None:
            from app.models import User

            user_id = session.scalar(select(User.id))
        assert user_id is not None
        session.add_all(
            AgentRun(
                user_id=user_id,
                job_id=UUID(job["id"]),
                task_type="company_research",
                status="failed",
                input_text="previous search",
                events=[],
                attempt_count=1,
            )
            for _ in range(10)
        )
        session.commit()

    response = await client.post(f"/api/v1/jobs/{job['id']}/research?refresh=true")
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "research_rate_limited"
    assert test_app.state.fake_search_provider.queries == []


@pytest.mark.anyio
async def test_empty_search_is_not_reported_as_provider_failure(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "research-empty@example.com")
    job = await create_job(client)
    test_app.state.company_research_search_provider = FakePublicSearchProvider(empty=True)
    from app.services.company_research import create_company_research_mcp_server

    test_app.state.company_research_mcp_server = create_company_research_mcp_server(
        test_app.state.settings, test_app.state.company_research_search_provider
    )
    response = await client.post(f"/api/v1/jobs/{job['id']}/research")
    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert response.json()["no_evidence"] is True
    assert "暂未返回结果" in response.json()["summary"]


@pytest.mark.anyio
async def test_tavily_search_provider_normalizes_public_results_without_fetching_urls() -> None:
    settings = Settings(
        _env_file=None,
        tavily_api_key="test-tavily-secret",
        research_timeout_seconds=5,
    )

    async def search_response(request):
        assert request.url.host == "api.tavily.com"
        assert request.url.path == "/search"
        assert request.headers["Authorization"] == "Bearer test-tavily-secret"
        body = json.loads(request.content)
        assert body == {
            "query": "星河科技 招聘",
            "max_results": 2,
            "search_depth": "basic",
            "topic": "general",
            "include_answer": False,
        }
        return Response(
            200,
            json={
                "results": [
                    {
                        "title": "校园招聘",
                        "url": "https://careers.example.com/campus#roles",
                        "content": "公司 2027 校园招聘启动。",
                        "published_date": "2026-10-31",
                    },
                    {
                        "title": "重复网址",
                        "url": "https://careers.example.com/campus/",
                        "content": "重复结果。",
                    },
                    {
                        "title": "不允许协议",
                        "url": "javascript:alert(1)",
                        "content": "不安全网址应丢弃。",
                    },
                ]
            },
        )

    provider = TavilySearchProvider(transport=MockTransport(search_response))
    sources = await provider.search("星河科技 招聘", 2, settings)
    assert len(sources) == 1
    assert sources[0].url == "https://careers.example.com/campus"
    assert sources[0].source_id == "web-1"
    assert sources[0].age == "2026-10-31"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "research_invalid_api_key"),
        (429, "research_rate_limited"),
        (432, "research_rate_limited"),
    ],
)
async def test_tavily_search_provider_maps_auth_and_quota_errors_safely(
    status_code: int, expected_code: str
) -> None:
    settings = Settings(_env_file=None, tavily_api_key="test-tavily-secret")

    async def error_response(request):
        assert request.headers["Authorization"] == "Bearer test-tavily-secret"
        return Response(status_code, json={"error": "private provider response"})

    provider = TavilySearchProvider(transport=MockTransport(error_response))
    with pytest.raises(CompanyResearchError) as exc_info:
        await provider.search("星河科技 校招", 5, settings)

    assert exc_info.value.code == expected_code
    assert "private provider response" not in exc_info.value.message


@pytest.mark.anyio
async def test_chat_summarizer_requests_cited_json_and_drops_unsupported_claims() -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url="https://chat.example/v1",
        llm_api_key="test-chat-key",
        llm_model="test-chat-model",
    )
    sources = make_sources()

    async def summary_response(request):
        assert str(request.url) == "https://chat.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-chat-key"
        body = json.loads(request.content)
        prompt = body["messages"][1]["content"]
        assert "careers.example.com/campus" in prompt
        return Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "findings": [
                                        {
                                            "claim": "招聘方向包含后端开发工程师。",
                                            "source_id": "web-1",
                                            "quote": "招聘方向包含后端开发工程师",
                                        },
                                        {
                                            "claim": "模型生成的无依据截止日期。",
                                            "source_id": "web-1",
                                            "quote": "网申截止日期为 12 月 1 日",
                                        },
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAICompatibleCompanyResearchSummarizer(
        transport=MockTransport(summary_response)
    )
    candidate, model_name = await provider.summarize(
        "星河科技", "后端开发工程师", "星河科技 校招", sources, settings
    )
    verified = validate_research_findings(candidate, sources)
    assert model_name == "test-chat-model"
    assert len(verified) == 1
    assert verified[0].claim == "招聘方向包含后端开发工程师。"


@pytest.mark.anyio
async def test_mcp_search_tool_has_a_per_process_rate_limit() -> None:
    settings = Settings(
        _env_file=None,
        tavily_api_key="test-search-key",
    )
    provider = FakePublicSearchProvider()
    server = create_company_research_mcp_server(settings, provider)
    for _ in range(30):
        await call_company_search_tool(server, "星河科技 校招", count=1)

    with pytest.raises(CompanyResearchError, match="每分钟最多执行 30 次"):
        await call_company_search_tool(server, "星河科技 校招", count=1)
    assert len(provider.queries) == 30


@pytest.mark.anyio
async def test_research_results_are_owner_scoped(client: AsyncClient) -> None:
    await register(client, "research-private@example.com")
    job = await create_job(client)
    created = await client.post(f"/api/v1/jobs/{job['id']}/research")
    assert created.status_code == 200

    await register(client, "research-other@example.com")
    assert (await client.get(f"/api/v1/jobs/{job['id']}/research")).status_code == 404
    assert (await client.post(f"/api/v1/jobs/{job['id']}/research")).status_code == 404
