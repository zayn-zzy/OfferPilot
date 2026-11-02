"""LangGraph orchestration and persistent checkpointers for job-search skills."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
import os
from pathlib import Path
import sqlite3
from typing import Any, Protocol, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy.engine import make_url


class SkillWorkflowState(TypedDict, total=False):
    """Small, non-PII state persisted between skill graph nodes."""

    run_id: str
    outcome: str
    requires_approval: bool
    approval_id: str
    decision: str


class SkillGraphNodes(Protocol):
    """Business operations invoked by the graph's named nodes."""

    def validate_context(self, state: SkillWorkflowState) -> dict[str, object]: ...

    async def generate_draft(self, state: SkillWorkflowState) -> dict[str, object]: ...

    def validate_evidence(self, state: SkillWorkflowState) -> dict[str, object]: ...

    def execute_local_save(self, state: SkillWorkflowState) -> dict[str, object]: ...


def build_skill_graph(
    checkpointer: BaseCheckpointSaver,
    nodes: SkillGraphNodes,
):
    """Build the explicit task graph, including an interrupt before local writes."""

    async def validate_context(state: SkillWorkflowState) -> dict[str, object]:
        return nodes.validate_context(state)

    async def generate_draft(state: SkillWorkflowState) -> dict[str, object]:
        if state.get("outcome") != "ready":
            return {"outcome": state.get("outcome", "cancelled")}
        return await nodes.generate_draft(state)

    async def validate_evidence(state: SkillWorkflowState) -> dict[str, object]:
        if state.get("outcome") != "generated":
            return {"outcome": state.get("outcome", "cancelled")}
        return nodes.validate_evidence(state)

    async def execute_local_save(state: SkillWorkflowState) -> dict[str, object]:
        if state.get("decision") != "approved" or not state.get("approval_id"):
            return {"outcome": "skipped"}
        return nodes.execute_local_save(state)

    async def approval_gate(state: SkillWorkflowState) -> dict[str, object]:
        if not state.get("requires_approval"):
            return {"decision": "skipped"}
        # Keep this node side-effect free before interrupt: LangGraph replays the
        # node from its beginning when it resumes after a human decision.
        decision = interrupt(
            {
                "run_id": state["run_id"],
                "action": "请检查申请准备包，并决定是否保存到 OfferPilot 本地工作台。",
            }
        )
        if not isinstance(decision, dict):
            return {"decision": "invalid"}
        return {
            "decision": str(decision.get("decision", "invalid")),
            "approval_id": str(decision.get("approval_id", "")),
        }

    graph = StateGraph(SkillWorkflowState)
    graph.add_node("validate_context", validate_context)
    graph.add_node("generate_draft", generate_draft)
    graph.add_node("validate_evidence", validate_evidence)
    graph.add_node("human_approval", approval_gate)
    graph.add_node("execute_local_save", execute_local_save)
    graph.add_edge(START, "validate_context")
    graph.add_edge("validate_context", "generate_draft")
    graph.add_edge("generate_draft", "validate_evidence")
    graph.add_edge("validate_evidence", "human_approval")
    graph.add_edge("human_approval", "execute_local_save")
    graph.add_edge("execute_local_save", END)
    return graph.compile(checkpointer=checkpointer)


def in_memory_checkpointer_for(database_url: str) -> InMemorySaver | None:
    """Return an in-memory saver only for ephemeral SQLite databases (mainly tests)."""

    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:"):
        return InMemorySaver()
    return None


class AsyncSqliteSaverAdapter(SqliteSaver):
    """Expose the local SQLite saver through LangGraph's async checkpointer API."""

    async def aget_tuple(self, config: RunnableConfig):
        return self.get_tuple(config)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: dict[str, Any],
        metadata: dict[str, Any],
        new_versions: dict[str, Any],
    ):
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self.put_writes(config, writes, task_id, task_path)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[Any]:
        entries = list(self.list(config, filter=filter, before=before, limit=limit))
        for entry in entries:
            yield entry

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)


@asynccontextmanager
async def open_skill_checkpointer(
    database_url: str,
    storage_dir: Path,
    shared: BaseCheckpointSaver | None = None,
) -> AsyncIterator[BaseCheckpointSaver]:
    """Open a SQLite/PostgreSQL saver, or reuse the app's in-memory test saver."""

    if shared is not None:
        yield shared
        return

    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        database = url.database
        if database in (None, "", ":memory:"):
            raise RuntimeError("内存 SQLite 必须在应用实例中共享 LangGraph checkpointer。")
        path = storage_dir / "langgraph-checkpoints.sqlite3"
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
        path.chmod(0o600)
        connection = sqlite3.connect(str(path), check_same_thread=False)
        try:
            checkpointer = AsyncSqliteSaverAdapter(connection)
            checkpointer.setup()
            yield checkpointer
        finally:
            connection.close()
        return

    if url.get_backend_name() == "postgresql":
        connection_string = url.set(drivername="postgresql").render_as_string(
            hide_password=False
        )
        async with AsyncPostgresSaver.from_conn_string(connection_string) as checkpointer:
            await checkpointer.setup()
            yield checkpointer
        return

    raise RuntimeError("LangGraph checkpointer 仅支持 SQLite 或 PostgreSQL。")
