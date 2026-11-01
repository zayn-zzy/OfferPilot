"""Private document retrieval, citations, and transparent job match tests."""

from collections.abc import AsyncGenerator, Generator
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, MockTransport, Response
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.main import create_app
from app.models import Base, DocumentChunk, KnowledgeNote
from app.services.knowledge import (
    CitationCandidate,
    GroundedAnswerCandidate,
    KnowledgeServiceError,
    OpenAICompatibleEmbeddingProvider,
    split_into_chunks,
)


class FakeEmbeddingProvider:
    async def embed(self, texts: list[str], settings: Settings):
        vector = [0.0] * 1536
        vector[0] = 1.0
        return [vector.copy() for _ in texts], "test-embedding-model"


class FakeAnswerProvider:
    def __init__(self, *, invalid_citation: bool = False) -> None:
        self.invalid_citation = invalid_citation

    async def answer(self, question, chunks, settings):
        if self.invalid_citation:
            return GroundedAnswerCandidate(
                answer="未核实回答",
                citations=[CitationCandidate(chunk_id=uuid4(), quote="外部编造的引用")],
            )
        chunk = chunks[0]
        quote = chunk.content[: min(80, len(chunk.content))]
        return GroundedAnswerCandidate(
            answer="根据已保存的资料，候选人有相关经历。",
            citations=[CitationCandidate(chunk_id=chunk.id, quote=quote)],
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
        secret_key="knowledge-test-secret-long-enough",
        allowed_origins=["http://localhost:3000"],
        storage_dir=tmp_path / "storage",
    )
    app = create_app(
        settings,
        factory,
        embedding_provider=FakeEmbeddingProvider(),
        knowledge_answer_provider=FakeAnswerProvider(),
    )
    yield app
    engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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


@pytest.mark.anyio
async def test_note_reindex_returns_only_valid_source_quotes(client: AsyncClient) -> None:
    await register(client, "knowledge-owner@example.com")
    note = await client.post(
        "/api/v1/knowledge/notes",
        json={"title": "实习项目", "content": "在星河科技实习期间，我使用 Python 和 PostgreSQL 开发订单服务。"},
    )
    assert note.status_code == 201

    indexed = await client.post("/api/v1/knowledge/reindex")
    assert indexed.status_code == 200
    assert indexed.json()["indexed_documents"] == 1
    assert indexed.json()["indexed_chunks"] == 1

    answer = await client.post(
        "/api/v1/knowledge/ask", json={"question": "我有哪些实习开发经验？"}
    )
    body = answer.json()
    assert answer.status_code == 200
    assert body["no_evidence"] is False
    assert body["citations"][0]["source_name"] == "实习项目"
    assert body["citations"][0]["quote"] in note.json()["content"]


@pytest.mark.anyio
async def test_knowledge_is_owner_scoped_and_unverified_quotes_are_rejected(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "knowledge-private@example.com")
    note = await client.post(
        "/api/v1/knowledge/notes",
        json={"title": "私人经历", "content": "我在校期间参与了校园二手交易平台的后端开发。"},
    )
    await client.post("/api/v1/knowledge/reindex")
    test_app.state.knowledge_answer_provider = FakeAnswerProvider(invalid_citation=True)
    rejected = await client.post("/api/v1/knowledge/ask", json={"question": "我做过什么项目？"})
    assert rejected.status_code == 200
    assert rejected.json()["no_evidence"] is True
    assert rejected.json()["citations"] == []

    await register(client, "knowledge-other@example.com")
    other_answer = await client.post(
        "/api/v1/knowledge/ask", json={"question": "我做过什么项目？"}
    )
    assert other_answer.status_code == 200
    assert other_answer.json()["no_evidence"] is True
    forbidden_delete = await client.delete(f"/api/v1/knowledge/notes/{note.json()['id']}")
    assert forbidden_delete.status_code == 404


@pytest.mark.anyio
async def test_editing_or_deleting_note_invalidates_its_index(client: AsyncClient, test_app: FastAPI) -> None:
    await register(client, "knowledge-reindex@example.com")
    note = await client.post(
        "/api/v1/knowledge/notes",
        json={"title": "旧笔记", "content": "旧内容描述了一个已经过时的实习项目经历。"},
    )
    await client.post("/api/v1/knowledge/reindex")
    owner_id = test_app.state.session_factory
    assert owner_id is not None
    with owner_id() as session:
        assert len(session.scalars(select(DocumentChunk)).all()) == 1

    updated = await client.put(
        f"/api/v1/knowledge/notes/{note.json()['id']}",
        json={"title": "新笔记", "content": "新内容描述了当前正在开发的毕业设计项目。"},
    )
    assert updated.status_code == 200
    with owner_id() as session:
        assert session.scalars(select(DocumentChunk)).all() == []

    await client.post("/api/v1/knowledge/reindex")
    deleted = await client.delete(f"/api/v1/knowledge/notes/{note.json()['id']}")
    assert deleted.status_code == 204
    with owner_id() as session:
        assert session.scalars(select(DocumentChunk)).all() == []


@pytest.mark.anyio
async def test_reindex_does_not_restore_source_changed_during_embedding(
    client: AsyncClient, test_app: FastAPI
) -> None:
    await register(client, "knowledge-race@example.com")
    note = await client.post(
        "/api/v1/knowledge/notes",
        json={"title": "并发编辑", "content": "向量服务处理期间会被修改的原始项目说明。"},
    )
    note_id = UUID(note.json()["id"])
    session_factory = test_app.state.session_factory

    class ConcurrentEditProvider:
        async def embed(self, texts: list[str], settings: Settings):
            with session_factory() as session:
                stored_note = session.get(KnowledgeNote, note_id)
                assert stored_note is not None
                stored_note.content = "用户在索引过程中修改后的项目说明内容。"
                session.commit()
            vector = [0.0] * 1536
            vector[0] = 1.0
            return [vector.copy() for _ in texts], "test-embedding-model"

    test_app.state.embedding_provider = ConcurrentEditProvider()
    response = await client.post("/api/v1/knowledge/reindex")
    assert response.status_code == 409
    assert "重新建立索引" in response.json()["detail"]
    with session_factory() as session:
        assert session.scalars(select(DocumentChunk)).all() == []


@pytest.mark.anyio
async def test_job_match_separates_hard_requirements_preferences_and_evidence(
    client: AsyncClient,
) -> None:
    await register(client, "match-candidate@example.com")
    await client.put(
        "/api/v1/profile",
        json={
            "education": "硕士",
            "target_roles": ["后端开发"],
            "target_cities": ["上海"],
            "industries": ["互联网"],
            "skills": ["Go"],
        },
    )
    resume = await client.post(
        "/api/v1/resumes/text",
        json={
            "text": "项目经历：使用 Python 开发校园服务后端，设计 PostgreSQL 数据表并编写接口测试。"
        },
    )
    assert resume.status_code == 201
    await client.post(f"/api/v1/resumes/{resume.json()['id']}/confirm")
    job = await client.post(
        "/api/v1/jobs",
        json={
            "company_name": "星河科技",
            "industry": "互联网",
            "title": "后端开发工程师",
            "city": "上海",
            "education_requirement": "本科及以上",
            "required_skills": ["Python", "SQL"],
        },
    )
    result = await client.get(f"/api/v1/jobs/{job.json()['id']}/match")
    assert result.status_code == 200
    body = result.json()
    assert next(item for item in body["criteria"] if item["key"] == "education")["status"] == "meets"
    assert next(item for item in body["criteria"] if item["key"] == "city")["status"] == "meets"
    assert body["skills"][0]["status"] == "evidenced"
    assert "Python" in body["skills"][0]["evidence"]
    assert body["skills"][1]["status"] == "not_found"
    assert "录用概率" in body["disclaimer"]


@pytest.mark.anyio
async def test_match_requires_confirmed_resume_and_does_not_leak_other_users_jobs(
    client: AsyncClient,
) -> None:
    await register(client, "match-no-resume@example.com")
    job = await client.post(
        "/api/v1/jobs", json={"company_name": "公司", "title": "开发工程师"}
    )
    no_resume = await client.get(f"/api/v1/jobs/{job.json()['id']}/match")
    assert no_resume.status_code == 409

    await register(client, "match-other@example.com")
    not_owned = await client.get(f"/api/v1/jobs/{job.json()['id']}/match")
    assert not_owned.status_code == 404


@pytest.mark.anyio
async def test_openai_compatible_embeddings_validate_endpoint_and_vector_size() -> None:
    settings = Settings(
        _env_file=None,
        embedding_base_url="https://embeddings.example/v1",
        embedding_api_key="test-secret",
        embedding_model="test-embedding",
    )

    async def valid_response(request):
        assert str(request.url) == "https://embeddings.example/v1/embeddings"
        body = json.loads(request.content)
        assert body["model"] == "test-embedding"
        assert body["input"] == ["fragment"]
        return Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.25] * 1536}]},
        )

    provider = OpenAICompatibleEmbeddingProvider(transport=MockTransport(valid_response))
    vectors, model_name = await provider.embed(["fragment"], settings)
    assert model_name == "test-embedding"
    assert len(vectors) == 1 and len(vectors[0]) == 1536

    async def invalid_response(_request):
        return Response(200, json={"data": [{"index": 0, "embedding": [0.25, 0.5]}]})

    invalid_provider = OpenAICompatibleEmbeddingProvider(transport=MockTransport(invalid_response))
    with pytest.raises(KnowledgeServiceError, match="1536"):
        await invalid_provider.embed(["fragment"], settings)


def test_chunking_bounds_fragments_and_preserves_overlap() -> None:
    text = "A" * 850 + "\n" + "B" * 500
    chunks = split_into_chunks(text)
    assert len(chunks) == 2
    assert all(len(chunk) <= 900 for chunk in chunks)
    assert chunks[0][-100:] in chunks[1]


def test_postgresql_vector_column_and_cosine_query_compile() -> None:
    create_table = str(CreateTable(DocumentChunk.__table__).compile(dialect=postgresql_dialect()))
    query = str(
        select(DocumentChunk)
        .order_by(DocumentChunk.embedding.cosine_distance([0.0] * 1536))
        .limit(5)
        .compile(dialect=postgresql_dialect())
    )
    assert "VECTOR(1536)" in create_table
    assert "<=>" in query
