"""Top-level LangGraph router for persisted Agent workflows."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Literal, TypedDict
from uuid import UUID

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session, sessionmaker

from app.models import AgentRun, ApprovalRequest, utc_now

AgentWorkflowType = Literal[
    "company_research", "job_extraction", "task_plan", "skill_workflow"
]
AgentWorkflowOperation = Literal["run", "resume"]
AgentWorkflowRoute = AgentWorkflowType | Literal["skip"]
SUPPORTED_AGENT_WORKFLOWS = frozenset(
    {"company_research", "job_extraction", "task_plan", "skill_workflow"}
)


class AgentWorkflowState(TypedDict, total=False):
    """Small routing state; prompt and generated content stay in specialist runs."""

    task_type: AgentWorkflowType
    run_id: UUID
    operation: AgentWorkflowOperation
    approval_id: UUID
    decision: Literal["approved", "rejected"]


WorkflowHandler = Callable[
    [AgentWorkflowState], Awaitable[dict[str, object] | None]
]


def build_agent_workflow_graph(
    session_factory: sessionmaker[Session],
    handlers: Mapping[AgentWorkflowType, WorkflowHandler],
):
    """Compile a bounded router that validates run state before dispatch."""

    if set(handlers) != SUPPORTED_AGENT_WORKFLOWS:
        raise ValueError("Agent workflow handlers must match the supported task types")

    def validate_and_route(state: AgentWorkflowState) -> AgentWorkflowRoute:
        task_type = state.get("task_type")
        operation = state.get("operation", "run")
        run_id = state.get("run_id")
        if task_type not in SUPPORTED_AGENT_WORKFLOWS:
            raise ValueError("Unsupported Agent workflow task type")
        if operation not in {"run", "resume"}:
            raise ValueError("Unsupported Agent workflow operation")
        if not isinstance(run_id, UUID):
            raise ValueError("Agent workflow run ID must be a UUID")

        with session_factory() as session:
            run = session.get(AgentRun, run_id)
            if run is None or run.task_type != task_type:
                return "skip"

            if operation == "run":
                if run.status != "queued":
                    return "skip"
                message = "已按任务类型进入对应 Agent 工作流。"
                step = "workflow_routed"
            else:
                if task_type != "skill_workflow":
                    raise HTTPException(
                        status_code=409,
                        detail="只有求职 Skill 工作流支持审批后恢复。",
                    )
                if run.status != "succeeded":
                    raise HTTPException(
                        status_code=409,
                        detail="当前求职草稿状态不支持恢复。",
                    )
                approval_id = state.get("approval_id")
                decision = state.get("decision")
                if not isinstance(approval_id, UUID) or decision not in {
                    "approved",
                    "rejected",
                }:
                    raise HTTPException(status_code=422, detail="审批恢复参数无效。")
                approval = session.get(ApprovalRequest, approval_id)
                if (
                    approval is None
                    or approval.agent_run_id != run.id
                    or approval.user_id != run.user_id
                    or approval.status != decision
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="审批与求职任务不匹配，工作流未恢复。",
                    )
                message = "已校验审批结果，正在恢复求职工作流。"
                step = "workflow_resumed"

            events = list(run.events or [])
            events.append(
                {
                    "id": len(events) + 1,
                    "event": "progress",
                    "message": message,
                    "step": step,
                    "created_at": utc_now().isoformat(),
                }
            )
            run.events = events
            run.updated_at = utc_now()
            session.commit()

        return task_type

    async def dispatch_registered_workflow(
        state: AgentWorkflowState,
    ) -> dict[str, object] | None:
        route = validate_and_route(state)
        if route == "skip":
            return {}
        return await handlers[route](state)

    graph = StateGraph(AgentWorkflowState)
    graph.add_node("dispatch_registered_workflow", dispatch_registered_workflow)
    graph.add_edge(START, "dispatch_registered_workflow")
    graph.add_edge("dispatch_registered_workflow", END)
    return graph.compile()
