"""Shared pytest fixtures for API integration tests."""

import pytest


@pytest.fixture(autouse=True)
def isolate_project_dotenv(tmp_path, monkeypatch):
    """Prevent a developer's backend/.env from changing test settings."""

    monkeypatch.chdir(tmp_path)


@pytest.fixture
def anyio_backend() -> tuple[str, dict[str, bool]]:
    """Run async API tests on the same Linux event loop used by Uvicorn in production.

    The default asyncio selector loop in this Python 3.13 environment does not resume
    tasks after AnyIO's worker thread schedules its result, so synchronous FastAPI
    routes hang under ASGITransport. Uvicorn's configured ``auto`` loop selects uvloop
    when installed; using it here exercises the production path and keeps the suite
    deterministic.
    """

    return ("asyncio", {"use_uvloop": True})
