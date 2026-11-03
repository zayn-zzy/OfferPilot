"""Profile and resume workflow tests with private SQLite and file storage."""

from collections.abc import AsyncGenerator, Generator
from io import BytesIO
from pathlib import Path
import stat

import pytest
from docx import Document
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.main import create_app
from app.models import Base


@pytest.fixture
def test_app(tmp_path: Path) -> Generator[FastAPI, None, None]:
    """Create an isolated API database and file storage directory."""

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
        storage_dir=tmp_path / "private-storage",
    )
    yield create_app(settings, factory)
    engine.dispose()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create a cookie-preserving in-process API client."""

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver") as test_client:
        yield test_client


async def register(client: AsyncClient, email: str) -> str:
    """Create an account and return its UUID."""

    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def make_text_pdf(text: str) -> bytes:
    """Build a tiny valid PDF containing one line of extractable text."""

    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def make_docx(text: str) -> bytes:
    """Build a minimal DOCX document for parser and upload tests."""

    document = Document()
    document.add_paragraph(text)
    file_buffer = BytesIO()
    document.save(file_buffer)
    return file_buffer.getvalue()


@pytest.mark.anyio
async def test_profile_is_private_and_normalizes_user_input(client: AsyncClient, test_app: FastAPI) -> None:
    await register(client, "first@example.com")

    empty = await client.get("/api/v1/profile")
    saved = await client.put(
        "/api/v1/profile",
        json={
            "graduation_year": 2027,
            "education": " 硕士 ",
            "major": "计算机科学",
            "target_roles": ["后端开发", " 后端开发 ", "算法工程师"],
            "target_cities": ["上海", "杭州"],
            "industries": ["互联网"],
            "skills": ["Python", "python", "SQL"],
        },
    )
    second_client = AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver")
    await register(second_client, "second@example.com")
    other_profile = await second_client.get("/api/v1/profile")
    await second_client.aclose()

    assert empty.status_code == 200
    assert empty.json()["id"] is None
    assert saved.status_code == 200
    assert saved.json()["education"] == "硕士"
    assert saved.json()["target_roles"] == ["后端开发", "算法工程师"]
    assert saved.json()["skills"] == ["Python", "SQL"]
    assert other_profile.status_code == 200
    assert other_profile.json()["graduation_year"] is None
    assert other_profile.json()["skills"] == []


@pytest.mark.anyio
async def test_profile_rejects_invalid_graduation_year(client: AsyncClient) -> None:
    await register(client, "student@example.com")

    response = await client.put(
        "/api/v1/profile",
        json={"graduation_year": 1700},
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_pasted_resume_requires_confirmation_and_can_be_deleted(client: AsyncClient) -> None:
    await register(client, "student@example.com")
    created = await client.post(
        "/api/v1/resumes/text",
        json={"text": "姓名：张同学\n技能：Python、SQL"},
    )

    assert created.status_code == 201
    assert created.json()["source_type"] == "paste"
    assert created.json()["confirmed_at"] is None
    assert "张同学" in created.json()["extracted_text"]

    resume_id = created.json()["id"]
    confirmed = await client.post(f"/api/v1/resumes/{resume_id}/confirm")
    listed = await client.get("/api/v1/resumes")
    deleted = await client.delete(f"/api/v1/resumes/{resume_id}")
    missing = await client.get(f"/api/v1/resumes/{resume_id}")

    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed_at"] is not None
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "extracted_text" not in listed.json()[0]
    assert deleted.status_code == 204
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_docx_upload_is_owner_scoped_and_deletes_private_file(
    client: AsyncClient,
    test_app: FastAPI,
) -> None:
    user_id = await register(client, "student@example.com")
    document_bytes = make_docx("张同学\n项目经历：开发招聘信息管理工具")
    uploaded = await client.post(
        "/api/v1/resumes/upload",
        files={"file": ("../../resume.docx", document_bytes, "application/octet-stream")},
    )

    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["filename"] == "resume.docx"
    assert body["source_type"] == "upload"
    assert "项目经历" in body["extracted_text"]
    assert body["confirmed_at"] is None

    storage_file = test_app.state.settings.storage_dir / user_id / f"{body['id']}.docx"
    assert storage_file.exists()
    assert stat.S_IMODE(storage_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(storage_file.parent.stat().st_mode) == 0o700
    second_client = AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver")
    await register(second_client, "other@example.com")
    forbidden = await second_client.get(f"/api/v1/resumes/{body['id']}")
    other_versions = await second_client.get("/api/v1/resumes")
    await second_client.aclose()

    deleted = await client.delete(f"/api/v1/resumes/{body['id']}")
    assert forbidden.status_code == 404
    assert other_versions.status_code == 200
    assert other_versions.json() == []
    assert deleted.status_code == 204
    assert not storage_file.exists()


@pytest.mark.anyio
async def test_pdf_upload_extracts_preview_without_auto_confirmation(client: AsyncClient) -> None:
    await register(client, "student@example.com")
    uploaded = await client.post(
        "/api/v1/resumes/upload",
        files={"file": ("resume.pdf", make_text_pdf("OfferPilot Resume"), "application/pdf")},
    )

    assert uploaded.status_code == 201
    assert "OfferPilot Resume" in uploaded.json()["extracted_text"]
    assert uploaded.json()["content_type"] == "application/pdf"
    assert uploaded.json()["confirmed_at"] is None


@pytest.mark.anyio
async def test_unsupported_or_invalid_files_are_rejected(client: AsyncClient) -> None:
    await register(client, "student@example.com")
    unsupported = await client.post(
        "/api/v1/resumes/upload",
        files={"file": ("resume.txt", b"some text", "text/plain")},
    )
    invalid_pdf = await client.post(
        "/api/v1/resumes/upload",
        files={"file": ("resume.pdf", b"%PDF- this is not a document", "application/pdf")},
    )
    too_large = await client.post(
        "/api/v1/resumes/upload",
        files={"file": ("large.pdf", b"x" * (10 * 1024 * 1024 + 1), "application/pdf")},
    )

    assert unsupported.status_code == 415
    assert invalid_pdf.status_code == 422
    assert too_large.status_code == 413
