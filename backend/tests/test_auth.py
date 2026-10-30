"""Authentication API tests against an isolated SQLite database."""

from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.main import create_app
from app.models import Base


@pytest.fixture
def test_app() -> Generator[FastAPI, None, None]:
    """Create a fresh API and in-memory database for each test."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        environment="test",
        database_url="sqlite://",
        secret_key="test-secret-key-that-is-long-enough-for-testing",
        allowed_origins=["http://localhost:3000"],
    )
    app = create_app(settings, factory)
    yield app
    engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    """Run async API tests with the backend included in the project environment."""

    return "asyncio"


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create an in-process HTTP client without starting a server process."""

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver") as test_client:
        yield test_client


@pytest.mark.anyio
async def test_health_endpoint_checks_database(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.anyio
async def test_register_sets_http_only_cookie_and_returns_public_user(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "student@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "student@example.com"
    assert "password" not in response.json()
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "offerpilot_session=" in cookie


@pytest.mark.anyio
async def test_session_can_read_current_user_and_logout(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "student@example.com", "password": "correct-horse-battery"},
    )

    current_user = await client.get("/api/v1/auth/me")
    logged_out = await client.post("/api/v1/auth/logout")
    after_logout = await client.get("/api/v1/auth/me")

    assert current_user.status_code == 200
    assert current_user.json()["email"] == "student@example.com"
    assert logged_out.status_code == 204
    assert after_logout.status_code == 401


@pytest.mark.anyio
async def test_duplicate_registration_is_rejected_case_insensitively(client: AsyncClient) -> None:
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "student@example.com", "password": "correct-horse-battery"},
    )
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "STUDENT@example.com", "password": "another-long-password"},
    )

    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.anyio
async def test_login_rejects_invalid_password(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "student@example.com", "password": "correct-horse-battery"},
    )

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "student@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


@pytest.mark.anyio
async def test_login_accepts_valid_credentials(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "student@example.com", "password": "correct-horse-battery"},
    )
    await client.post("/api/v1/auth/logout")

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "student@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "student@example.com"
    assert "offerpilot_session=" in response.headers["set-cookie"]


@pytest.mark.anyio
async def test_untrusted_origin_cannot_register(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        headers={"Origin": "https://attacker.example"},
        json={"email": "student@example.com", "password": "correct-horse-battery"},
    )

    assert response.status_code == 403
