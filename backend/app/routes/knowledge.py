"""Private notes, document indexing, and citation-backed knowledge answers."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import DocumentChunk, KnowledgeNote, ResumeVersion, User
from app.routes.auth import (
    current_user_dependency,
    enforce_same_origin,
    session_dependency,
    settings_dependency,
)
from app.schemas import (
    KnowledgeAnswerRead,
    KnowledgeAsk,
    KnowledgeCitationRead,
    KnowledgeNoteRead,
    KnowledgeNoteWrite,
    KnowledgeReindexRead,
)
from app.services.knowledge import (
    KnowledgeServiceError,
    retrieve_chunks,
    split_into_chunks,
    validate_answer_citations,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)
MAX_INDEXED_CHUNKS = 2000
MIN_RELEVANCE = 0.12


def _owned_note(session: Session, user: User, note_id: UUID) -> KnowledgeNote:
    note = session.scalar(
        select(KnowledgeNote).where(
            KnowledgeNote.id == note_id,
            KnowledgeNote.user_id == user.id,
        )
    )
    if note is None:
        raise HTTPException(status_code=404, detail="求职笔记不存在")
    return note


@router.get("/notes", response_model=list[KnowledgeNoteRead])
def list_notes(
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
) -> list[KnowledgeNote]:
    return list(
        session.scalars(
            select(KnowledgeNote)
            .where(KnowledgeNote.user_id == user.id)
            .order_by(KnowledgeNote.updated_at.desc(), KnowledgeNote.id.desc())
        ).all()
    )


@router.post("/notes", response_model=KnowledgeNoteRead, status_code=status.HTTP_201_CREATED)
def create_note(
    payload: KnowledgeNoteWrite,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> KnowledgeNote:
    enforce_same_origin(request, settings)
    note = KnowledgeNote(user_id=user.id, title=payload.title, content=payload.content)
    session.add(note)
    session.commit()
    session.refresh(note)
    return note


@router.put("/notes/{note_id}", response_model=KnowledgeNoteRead)
def update_note(
    note_id: UUID,
    payload: KnowledgeNoteWrite,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> KnowledgeNote:
    enforce_same_origin(request, settings)
    note = _owned_note(session, user, note_id)
    note.title = payload.title
    note.content = payload.content
    session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.user_id == user.id,
            DocumentChunk.source_type == "note",
            DocumentChunk.source_id == note.id,
        )
    )
    session.commit()
    session.refresh(note)
    return note


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    note_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> None:
    enforce_same_origin(request, settings)
    note = _owned_note(session, user, note_id)
    session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.user_id == user.id,
            DocumentChunk.source_type == "note",
            DocumentChunk.source_id == note.id,
        )
    )
    session.delete(note)
    session.commit()


@router.post("/reindex", response_model=KnowledgeReindexRead)
async def reindex_knowledge(
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> KnowledgeReindexRead:
    """Rebuild the current user's index from confirmed resumes and saved notes."""

    enforce_same_origin(request, settings)
    owner_id = user.id
    sources: list[tuple[str, UUID, str, str]] = []
    resumes = session.scalars(
        select(ResumeVersion).where(
            ResumeVersion.user_id == owner_id,
            ResumeVersion.confirmed_at.is_not(None),
        )
    ).all()
    notes = session.scalars(
        select(KnowledgeNote).where(KnowledgeNote.user_id == owner_id)
    ).all()
    for resume in resumes:
        sources.append(("resume", resume.id, resume.filename, resume.extracted_text))
    for note in notes:
        sources.append(("note", note.id, note.title, note.content))
    # Do not hold a read transaction open while the embedding provider is called.
    session.rollback()

    pending: list[tuple[str, UUID, str, int, str]] = []
    for source_type, source_id, source_name, text in sources:
        for chunk_index, content in enumerate(split_into_chunks(text)):
            pending.append((source_type, source_id, source_name, chunk_index, content))
    if len(pending) > MAX_INDEXED_CHUNKS:
        raise HTTPException(
            status_code=413,
            detail=f"资料拆分后超过 {MAX_INDEXED_CHUNKS} 个片段，请减少资料后重试。",
        )

    vectors: list[list[float]] = []
    model_name = settings.embedding_model.strip()
    if pending:
        try:
            vectors, model_name = await request.app.state.embedding_provider.embed(
                [item[4] for item in pending], settings
            )
        except KnowledgeServiceError as exc:
            logger.warning("Knowledge indexing provider failed (%s)", exc.code)
            raise HTTPException(
                status_code=503,
                detail={"code": exc.code, "message": exc.message},
            ) from None
        if len(vectors) != len(pending):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "embedding_result_incomplete",
                    "message": "向量服务没有返回全部资料片段，请重试。",
                },
            )

    source_snapshot = {
        (source_type, source_id): (source_name, content)
        for source_type, source_id, source_name, content in sources
    }
    current_resumes = session.scalars(
        select(ResumeVersion)
        .where(
            ResumeVersion.user_id == owner_id,
            ResumeVersion.confirmed_at.is_not(None),
        )
        .with_for_update()
    ).all()
    current_notes = session.scalars(
        select(KnowledgeNote)
        .where(KnowledgeNote.user_id == owner_id)
        .with_for_update()
    ).all()
    current_snapshot = {
        **{("resume", item.id): (item.filename, item.extracted_text) for item in current_resumes},
        **{("note", item.id): (item.title, item.content) for item in current_notes},
    }
    if current_snapshot != source_snapshot:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="索引过程中资料发生变化，请重新建立索引。",
        )

    session.execute(delete(DocumentChunk).where(DocumentChunk.user_id == owner_id))
    session.add_all(
        DocumentChunk(
            user_id=owner_id,
            source_type=source_type,
            source_id=source_id,
            source_name=source_name,
            chunk_index=chunk_index,
            content=content,
            embedding=vector,
            embedding_dimensions=len(vector),
            embedding_model=model_name,
        )
        for (source_type, source_id, source_name, chunk_index, content), vector in zip(
            pending, vectors, strict=True
        )
    )
    session.commit()
    return KnowledgeReindexRead(
        indexed_documents=len(sources),
        indexed_chunks=len(pending),
        embedding_model=model_name,
    )


@router.post("/ask", response_model=KnowledgeAnswerRead)
async def ask_knowledge(
    payload: KnowledgeAsk,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> KnowledgeAnswerRead:
    """Answer from this user's nearest indexed fragments and verify each quote."""

    enforce_same_origin(request, settings)
    owner_id = user.id
    has_index = session.scalar(
        select(DocumentChunk.id)
        .where(DocumentChunk.user_id == owner_id)
        .limit(1)
    )
    if has_index is None:
        return KnowledgeAnswerRead(
            answer="还没有可检索的资料。请先确认一份简历或保存求职笔记，再建立索引。",
            citations=[],
            no_evidence=True,
        )
    session.commit()
    try:
        vectors, embedding_model = await request.app.state.embedding_provider.embed(
            [payload.question], settings
        )
    except KnowledgeServiceError as exc:
        logger.warning("Knowledge query embedding provider failed (%s)", exc.code)
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "message": exc.message},
        ) from None
    if len(vectors) != 1:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "embedding_result_incomplete",
                "message": "向量服务没有返回检索结果，请重试。",
            },
        )

    query_dimensions = len(vectors[0])
    indexed_specs = set(
        session.execute(
            select(DocumentChunk.embedding_model, DocumentChunk.embedding_dimensions)
            .where(DocumentChunk.user_id == owner_id)
            .distinct()
        ).all()
    )
    if indexed_specs != {(embedding_model, query_dimensions)}:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="向量模型或维度与现有索引不一致，请重新建立索引。",
        )
    session.commit()

    retrieved = retrieve_chunks(
        session,
        user_id=owner_id,
        query_vector=vectors[0],
        embedding_model=embedding_model,
        embedding_dimensions=query_dimensions,
        limit=payload.top_k,
    )
    session.commit()
    if not retrieved or retrieved[0][1] < MIN_RELEVANCE:
        return KnowledgeAnswerRead(
            answer="在已建立索引的简历和求职笔记中，没有找到足以支持回答的内容。",
            citations=[],
            no_evidence=True,
        )

    try:
        generated = await request.app.state.knowledge_answer_provider.answer(
            payload.question, [chunk for chunk, _ in retrieved], settings
        )
    except KnowledgeServiceError as exc:
        logger.warning("Knowledge answer provider failed (%s)", exc.code)
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "message": exc.message},
        ) from None
    answer, valid_citations = validate_answer_citations(generated, retrieved)
    if valid_citations:
        current_chunk_ids = set(
            session.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.user_id == owner_id,
                    DocumentChunk.id.in_([chunk.id for chunk, _, _ in valid_citations]),
                ).with_for_update()
            ).all()
        )
        valid_citations = [
            citation for citation in valid_citations if citation[0].id in current_chunk_ids
        ]
    session.commit()
    if not valid_citations:
        return KnowledgeAnswerRead(
            answer="在检索到的原文中没有找到可核验的回答依据。",
            citations=[],
            no_evidence=True,
        )
    return KnowledgeAnswerRead(
        answer=answer,
        citations=[
            KnowledgeCitationRead(
                chunk_id=chunk.id,
                source_type=chunk.source_type,
                source_id=chunk.source_id,
                source_name=chunk.source_name,
                quote=quote,
                relevance=max(-1.0, min(1.0, score)),
            )
            for chunk, quote, score in valid_citations
        ],
        no_evidence=False,
    )
