"""API and at-rest protection tests for per-user model settings."""

from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.main import create_app
from app.models import Base, User, UserModelConfiguration
from app.services.job_extraction import (
    ExtractedDateField,
    ExtractedSkillsField,
    ExtractedTextField,
    JobExtractionCandidate,
)
from app.services.model_credentials import decrypt_model_credential
from app.services.user_model_settings import resolve_user_model_settings


@pytest.fixture
def test_app(tmp_path) -> Generator[FastAPI, None, None]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'model-settings.db'}",
        secret_key="model-settings-test-secret-key-long-enough",
        storage_dir=tmp_path / "storage",
        llm_base_url="https://user:password@chat.example.test/v1?token=url-secret",
        llm_model="deployment-chat-model",
        llm_api_key=SecretStr("deployment-chat-key"),
        embedding_base_url="https://embedding.example.test/v1",
        embedding_model="deployment-embedding-model",
        embedding_api_key=SecretStr("deployment-embedding-key"),
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.session_factory.kw["bind"])
    yield app
    app.state.session_factory.kw["bind"].dispose()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://testserver",
    ) as test_client:
        yield test_client


async def register(client: AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201


@pytest.mark.anyio
async def test_user_can_save_encrypted_model_keys_without_api_echo(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    await register(client, "settings-owner@example.com")
    response = await client.put(
        "/api/v1/settings/models",
        json={
            "llm_api_key": "account-chat-secret",
            "llm_model": "account-chat-model",
            "embedding_api_key": "account-embedding-secret",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "account-chat-secret" not in response.text
    assert "account-embedding-secret" not in response.text
    assert "url-secret" not in response.text
    assert "chat.example.test" not in response.text
    assert body["chat_completions"]["credential_source"] == "account"
    assert body["chat_completions"]["effective_model"] == "account-chat-model"
    assert body["chat_completions"]["endpoint_configured"] is True
    assert body["embeddings"]["credential_source"] == "account"
    assert body["embeddings"]["effective_model"] == "deployment-embedding-model"

    with test_app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.email == "settings-owner@example.com"))
        assert user is not None
        configuration = session.get(UserModelConfiguration, user.id)
        assert configuration is not None
        assert "account-chat-secret" not in configuration.llm_api_key_ciphertext
        assert "account-embedding-secret" not in configuration.embedding_api_key_ciphertext
        assert (
            decrypt_model_credential(
                test_app.state.settings,
                user.id,
                "chat_completions",
                configuration.llm_api_key_ciphertext,
            )
            == "account-chat-secret"
        )
        resolved = resolve_user_model_settings(session, user.id, test_app.state.settings)

    assert resolved.llm_api_key.get_secret_value() == "account-chat-secret"
    assert resolved.embedding_api_key.get_secret_value() == "account-embedding-secret"
    assert resolved.llm_model == "account-chat-model"


@pytest.mark.anyio
async def test_model_settings_are_isolated_and_can_fall_back_to_deployment_key(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    await register(client, "first-settings-owner@example.com")
    saved = await client.put(
        "/api/v1/settings/models",
        json={"llm_api_key": "first-users-secret"},
    )
    assert saved.status_code == 200

    await client.post("/api/v1/auth/logout")
    await register(client, "second-settings-owner@example.com")
    second_settings = await client.get("/api/v1/settings/models")
    assert second_settings.status_code == 200
    assert second_settings.json()["chat_completions"]["credential_source"] == "deployment"

    with test_app.state.session_factory() as session:
        second_user = session.scalar(
            select(User).where(User.email == "second-settings-owner@example.com")
        )
        assert second_user is not None
        resolved = resolve_user_model_settings(
            session,
            second_user.id,
            test_app.state.settings,
        )
    assert resolved.llm_api_key.get_secret_value() == "deployment-chat-key"

    await client.post("/api/v1/auth/logout")
    await client.post(
        "/api/v1/auth/login",
        json={"email": "first-settings-owner@example.com", "password": "correct-horse-battery"},
    )
    cleared = await client.put(
        "/api/v1/settings/models",
        json={"clear_llm_api_key": True, "clear_llm_model": True},
    )
    assert cleared.status_code == 200
    assert cleared.json()["chat_completions"]["credential_source"] == "deployment"
    assert cleared.json()["chat_completions"]["effective_model"] == "deployment-chat-model"


@pytest.mark.anyio
async def test_model_settings_api_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/settings/models")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_agent_run_receives_the_owners_model_credentials_and_override(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    await register(client, "model-run-owner@example.com")
    await client.put(
        "/api/v1/settings/models",
        json={
            "llm_api_key": "owner-only-model-key",
            "llm_model": "owner-selected-model",
        },
    )

    class CapturingProvider:
        def __init__(self) -> None:
            self.api_key = ""
            self.model = ""

        async def extract(self, source_text: str, settings: Settings):
            self.api_key = settings.llm_api_key.get_secret_value()
            self.model = settings.llm_model
            candidate = JobExtractionCandidate(
                company_name=ExtractedTextField(value="样例公司", confidence=0.95, evidence="样例公司"),
                title=ExtractedTextField(value="后端工程师", confidence=0.95, evidence="后端工程师"),
                city=ExtractedTextField(value="上海", confidence=0.9, evidence="上海"),
                job_type=ExtractedTextField(value=None, confidence=0, evidence=None),
                batch=ExtractedTextField(value=None, confidence=0, evidence=None),
                deadline=ExtractedDateField(value=None, confidence=0, evidence=None),
                education_requirement=ExtractedTextField(value=None, confidence=0, evidence=None),
                required_skills=ExtractedSkillsField(value=[], confidence=0, evidence=None),
            )
            return candidate, settings.llm_model

    provider = CapturingProvider()
    test_app.state.job_extraction_provider = provider
    run = await client.post(
        "/api/v1/agent/job-extractions",
        json={"text": "样例公司正在招聘后端工程师，工作地点位于上海市浦东新区。"},
    )

    assert run.status_code == 202
    assert provider.api_key == "owner-only-model-key"
    assert provider.model == "owner-selected-model"
