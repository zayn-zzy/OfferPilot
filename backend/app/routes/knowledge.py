"""Private notes, document indexing, and citation-backed knowledge answers."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import AgentRun, DocumentChunk, KnowledgeNote, ResumeVersion, User, utc_now
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
    EmbeddingProvider,
    GroundedAnswerCandidate,
    KnowledgeAnswerProvider,
    KnowledgeServiceError,
    retrieve_chunks,
    split_into_chunks,
    validate_answer_citations,
)
from app.services.user_model_settings import resolve_user_model_settings

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
    provider_settings = resolve_user_model_settings(session, user.id, settings)

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
    model_name = provider_settings.embedding_model.strip()
    if pending:
        try:
            vectors, model_name = await request.app.state.embedding_provider.embed(
                [item[4] for item in pending], provider_settings
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


def _append_knowledge_event(
    run: AgentRun,
    event: str,
    message: str,
    step: str,
) -> None:
    events = list(run.events or [])
    events.append(
        {
            "id": len(events) + 1,
            "event": event,
            "message": message,
            "step": step,
            "created_at": utc_now().isoformat(),
        }
    )
    run.events = events
    run.updated_at = utc_now()


def _fail_knowledge_run(
    session_factory: sessionmaker[Session],
    run_id: UUID,
    code: str,
    message: str,
    step: str,
) -> None:
    with session_factory() as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.status not in {"queued", "running"}:
            return
        run.status = "failed"
        run.error_code = code
        run.error_message = message
        run.finished_at = utc_now()
        _append_knowledge_event(run, "failed", message, step)
        session.commit()


def _complete_knowledge_run(
    session_factory: sessionmaker[Session],
    run_id: UUID,
    answer: KnowledgeAnswerRead,
) -> None:
    with session_factory() as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.status != "running":
            raise HTTPException(status_code=409, detail="资料问答任务状态已变化，请重试。")
        run.result = answer.model_dump(mode="json")
        run.status = "succeeded"
        run.finished_at = utc_now()
        _append_knowledge_event(run, "completed", "资料问答完成并校验了引用。", "completed")
        session.commit()


async def run_knowledge_qa_workflow(
    run_id: UUID,
    session_factory: sessionmaker[Session],
    settings: Settings,
    embedding_provider: EmbeddingProvider,
    answer_provider: KnowledgeAnswerProvider,
) -> None:
    """Retrieve an owner's indexed fragments and persist only verified citations."""

    with session_factory() as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.task_type != "knowledge_qa" or run.status != "queued":
            return
        owner_id = run.user_id
        question = run.input_text
        run_result = run.result or {}
        top_k = min(max(int(run_result.get("top_k", 5)), 1), 10)
        has_index = session.scalar(
            select(DocumentChunk.id)
            .where(DocumentChunk.user_id == owner_id)
            .limit(1)
        )
        run.status = "running"
        run.attempt_count += 1
        run.error_code = None
        run.error_message = None
        run.finished_at = None
        run.result = {"top_k": top_k}
        _append_knowledge_event(run, "progress", "正在检查个人资料索引。", "load_index")
        session.commit()

    if has_index is None:
        _complete_knowledge_run(
            session_factory,
            run_id,
            KnowledgeAnswerRead(
                answer="还没有可检索的资料。请先确认一份简历或保存求职笔记，再建立索引。",
                citations=[],
                no_evidence=True,
            ),
        )
        return

    try:
        vectors, embedding_model = await embedding_provider.embed([question], settings)
    except KnowledgeServiceError as exc:
        _fail_knowledge_run(session_factory, run_id, exc.code, exc.message, "embed_query")
        logger.warning("Knowledge query embedding provider failed (%s)", exc.code)
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "message": exc.message},
        ) from None
    except Exception as exc:
        code = "embedding_provider_error"
        message = "向量服务暂时不可用，请稍后重试。"
        _fail_knowledge_run(session_factory, run_id, code, message, "embed_query")
        logger.error("Knowledge embedding provider raised %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail={"code": code, "message": message},
        ) from None
    if len(vectors) != 1:
        code = "embedding_result_incomplete"
        message = "向量服务没有返回检索结果，请重试。"
        _fail_knowledge_run(session_factory, run_id, code, message, "embed_query")
        raise HTTPException(status_code=503, detail={"code": code, "message": message})

    query_dimensions = len(vectors[0])
    with session_factory() as session:
        indexed_specs = set(
            session.execute(
                select(DocumentChunk.embedding_model, DocumentChunk.embedding_dimensions)
                .where(DocumentChunk.user_id == owner_id)
                .distinct()
            ).all()
        )
        if indexed_specs != {(embedding_model, query_dimensions)}:
            index_matches = False
            retrieved: list[tuple[DocumentChunk, float]] = []
        else:
            index_matches = True
            retrieved = retrieve_chunks(
                session,
                user_id=owner_id,
                query_vector=vectors[0],
                embedding_model=embedding_model,
                embedding_dimensions=query_dimensions,
                limit=top_k,
            )

    if not index_matches:
        code = "knowledge_index_mismatch"
        message = "向量模型或维度与现有索引不一致，请重新建立索引。"
        _fail_knowledge_run(session_factory, run_id, code, message, "validate_index")
        raise HTTPException(status_code=409, detail=message)
    if not retrieved or retrieved[0][1] < MIN_RELEVANCE:
        _complete_knowledge_run(
            session_factory,
            run_id,
            KnowledgeAnswerRead(
                answer="在已建立索引的简历和求职笔记中，没有找到足以支持回答的内容。",
                citations=[],
                no_evidence=True,
            ),
        )
        return

    with session_factory() as session:
        run = session.get(AgentRun, run_id)
        if run is not None and run.status == "running":
            _append_knowledge_event(run, "progress", "已检索到资料片段，正在整理回答。", "answer")
            session.commit()
    try:
        generated: GroundedAnswerCandidate = await answer_provider.answer(
            question,
            [chunk for chunk, _ in retrieved],
            settings,
        )
    except KnowledgeServiceError as exc:
        _fail_knowledge_run(session_factory, run_id, exc.code, exc.message, "answer")
        logger.warning("Knowledge answer provider failed (%s)", exc.code)
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "message": exc.message},
        ) from None
    except Exception as exc:
        code = "knowledge_answer_provider_error"
        message = "资料回答服务暂时不可用，请稍后重试。"
        _fail_knowledge_run(session_factory, run_id, code, message, "answer")
        logger.error("Knowledge answer provider raised %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail={"code": code, "message": message},
        ) from None

    answer_text, valid_citations = validate_answer_citations(generated, retrieved)
    if valid_citations:
        with session_factory() as session:
            current_chunk_ids = set(
                session.scalars(
                    select(DocumentChunk.id).where(
                        DocumentChunk.user_id == owner_id,
                        DocumentChunk.id.in_([chunk.id for chunk, _, _ in valid_citations]),
                    ).with_for_update()
                ).all()
            )
            session.commit()
        valid_citations = [
            citation for citation in valid_citations if citation[0].id in current_chunk_ids
        ]

    if not valid_citations:
        result = KnowledgeAnswerRead(
            answer="在检索到的原文中没有找到可核验的回答依据。",
            citations=[],
            no_evidence=True,
        )
    else:
        result = KnowledgeAnswerRead(
            answer=answer_text,
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
    _complete_knowledge_run(session_factory, run_id, result)


@router.post("/ask", response_model=KnowledgeAnswerRead)
async def ask_knowledge(
    payload: KnowledgeAsk,
    request: Request,
    user: Annotated[User, Depends(current_user_dependency)],
    session: Annotated[Session, Depends(session_dependency)],
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> KnowledgeAnswerRead:
    """Persist the question, run owner-scoped RAG, and return verified citations."""

    enforce_same_origin(request, settings)
    run = AgentRun(
        user_id=user.id,
        task_type="knowledge_qa",
        status="queued",
        input_text=payload.question,
        result={"top_k": payload.top_k},
        events=[],
        attempt_count=0,
    )
    _append_knowledge_event(run, "progress", "已创建个人资料问答任务。", "queued")
    session.add(run)
    session.commit()
    session.refresh(run)

    await request.app.state.agent_workflow_graph.ainvoke(
        {"task_type": "knowledge_qa", "operation": "run", "run_id": run.id},
        version="v2",
    )
    session.expire_all()
    completed_run = session.get(AgentRun, run.id)
    if completed_run is None:
        raise HTTPException(status_code=404, detail="资料问答任务已被删除。")
    if completed_run.status != "succeeded":
        raise HTTPException(
            status_code=503,
            detail={
                "code": completed_run.error_code or "knowledge_workflow_incomplete",
                "message": completed_run.error_message or "资料问答未能完成，请稍后重试。",
            },
        )
    return KnowledgeAnswerRead.model_validate(completed_run.result or {})
