"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest, type AgentTaskPlan, type AgentWorkspace } from "@/lib/api";

const STATUS_LABELS: Record<AgentTaskPlan["status"], string> = {
  queued: "排队中",
  running: "整理计划中",
  cancelling: "取消中",
  awaiting_confirmation: "等待确认",
  needs_clarification: "需要补充信息",
  confirmed: "提醒已创建",
  cancelled: "已取消",
  failed: "处理失败",
};

const KIND_LABELS: Record<string, string> = {
  opening: "开放日",
  deadline: "截止日期",
  assessment: "测评",
  interview: "面试",
  follow_up: "跟进",
  other: "其他",
};

function formatEventTime(value: string | null, timezone: string) {
  if (!value) return "日期待补充";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone,
    }).format(new Date(value));
  } catch {
    return new Date(value).toLocaleString("zh-CN");
  }
}

export default function AgentTaskPlannerPage() {
  const [plans, setPlans] = useState<AgentTaskPlan[]>([]);
  const [workspace, setWorkspace] = useState<AgentWorkspace | null>(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [workspaceError, setWorkspaceError] = useState("");
  const idempotencyKey = useRef<string | null>(null);

  const loadPlans = useCallback(async () => {
    try {
      setPlans(await apiRequest<AgentTaskPlan[]>("/api/v1/agent/task-plans?limit=20"));
      setError("");
      setRequiresLogin(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法载入任务计划。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadWorkspace = useCallback(async () => {
    try {
      setWorkspace(await apiRequest<AgentWorkspace>("/api/v1/agent/workspace"));
      setWorkspaceError("");
    } catch (cause) {
      setWorkspaceError(cause instanceof Error ? cause.message : "无法载入 Agent 工作区。");
    } finally {
      setWorkspaceLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    if (!plans.some((plan) => ["queued", "running", "cancelling"].includes(plan.status))) return;
    const timer = window.setInterval(() => {
      void loadPlans();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [plans, loadPlans]);

  async function createPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setNotice("");
    idempotencyKey.current ??= window.crypto.randomUUID();
    try {
      const plan = await apiRequest<AgentTaskPlan>("/api/v1/agent/task-plans", {
        method: "POST",
        body: JSON.stringify({ text, idempotency_key: idempotencyKey.current }),
      });
      idempotencyKey.current = null;
      setText("");
      setPlans((current) => [plan, ...current.filter((item) => item.id !== plan.id)]);
      setNotice("已收到请求。提醒草稿生成后会先展示给你确认。");
      setRequiresLogin(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法创建任务计划。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setSubmitting(false);
    }
  }

  async function runAction(plan: AgentTaskPlan, action: "confirm" | "cancel" | "retry") {
    setWorkingId(plan.id);
    setError("");
    setNotice("");
    try {
      const updated = await apiRequest<AgentTaskPlan>(`/api/v1/agent/task-plans/${plan.id}/${action}`, {
        method: "POST",
      });
      setPlans((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
      setNotice(action === "confirm"
        ? "提醒已保存，可在提醒中心查看。"
        : action === "cancel"
          ? updated.status === "cancelling"
            ? "已请求取消；模型响应完成后会丢弃结果。"
            : "任务计划已取消。"
          : "已安排重试。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "任务操作失败。");
      if (cause instanceof ApiError && cause.status === 401) setRequiresLogin(true);
      await loadPlans();
    } finally {
      setWorkingId(null);
    }
  }

  return (
    <main className="agent-planner-shell">
      <header className="dashboard-topbar skills-topbar">
        <Link className="brand" href="/dashboard"><span className="brand-mark">O</span> OfferPilot</Link>
        <nav className="dashboard-actions" aria-label="主导航">
          <Link className="text-link" href="/dashboard">工作台</Link>
          <Link className="text-link" href="/jobs">岗位管理</Link>
          <Link className="text-link" href="/reminders">提醒中心</Link>
          <Link className="text-link" href="/skills">Agent Skills</Link>
        </nav>
      </header>

      <section className="agent-planner-heading agent-workspace-heading">
        <p className="eyebrow">求职 Agent 工作区</p>
        <h1>选择一项求职任务</h1>
        <p>从统一入口进入岗位提取、匹配、公司研究、个人资料问答或材料准备。各项工作流会在确认前展示草稿和证据。</p>
      </section>

      {error && <div className="profile-message profile-error" role="alert">{error}{requiresLogin && <> <Link href="/login">去登录</Link></>}</div>}
      {notice && <div className="profile-message profile-success" role="status">{notice}</div>}

      <section className="profile-panel agent-workspace-panel" aria-labelledby="agent-capabilities-title">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">任务类型</p><h2 id="agent-capabilities-title">可用的求职工作流</h2></div>
        </div>
        {workspaceError && <div className="profile-message profile-error" role="alert">{workspaceError}</div>}
        {workspaceLoading ? <p className="empty-state">正在载入任务类型…</p> : workspace && (
          <div className="agent-capability-grid">
            {workspace.capabilities.map((capability) => (
              <article className="agent-capability-card" key={capability.id}>
                <div className="agent-capability-heading">
                  <h3>{capability.title}</h3>
                  <span className={capability.action_level === "read_only" ? "agent-capability-readonly" : "agent-capability-draft"}>
                    {capability.action_level === "read_only" ? "只读" : "生成草稿"}
                  </span>
                </div>
                <p>{capability.description}</p>
                <small>{capability.confirmation_required ? "涉及写入时需你确认" : "不会修改求职数据"}</small>
                <Link href={capability.href}>{capability.action_label} →</Link>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="profile-panel agent-planner-panel" id="task-planner">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">提醒计划</p><h2>用自然语言整理待办</h2></div>
        </div>
        <form className="agent-planner-form" onSubmit={createPlan}>
          <label htmlFor="task-request">任务描述</label>
          <textarea
            id="task-request"
            value={text}
            onChange={(event) => { idempotencyKey.current = null; setText(event.target.value); }}
            placeholder="例如：下周三前跟进星河科技的测评，提醒我检查邮件通知。"
            rows={4}
            minLength={3}
            maxLength={4000}
            required
          />
          <div className="agent-planner-form-footer">
            <span>请写明日期和要做的动作；没有具体时间时默认当天 09:00（账户时区）。</span>
            <button className="button button-primary" type="submit" disabled={submitting || text.trim().length < 3}>
              {submitting ? "正在提交…" : "生成提醒草稿"}
            </button>
          </div>
        </form>
      </section>

      <section className="profile-panel agent-planner-panel">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">任务记录</p><h2>计划与确认</h2></div>
        </div>
        {loading ? <p className="empty-state">正在载入任务计划…</p> : plans.length === 0 ? <p className="empty-state">还没有任务计划。</p> : (
          <div className="agent-plan-list">
            {plans.map((plan) => {
              const preview = plan.preview;
              const busy = workingId === plan.id;
              return (
                <article className="agent-plan-card" key={plan.id}>
                  <div className="agent-plan-heading">
                    <div><p className="eyebrow">{new Date(plan.created_at).toLocaleString("zh-CN")}</p><h3>{preview?.title || "求职任务计划"}</h3></div>
                    <span className={`skill-run-status ${plan.status === "failed" ? "skill-run-failed" : plan.status === "awaiting_confirmation" || plan.status === "queued" || plan.status === "running" || plan.status === "cancelling" ? "skill-run-running" : plan.status === "confirmed" ? "skill-run-succeeded" : ""}`}>
                      {STATUS_LABELS[plan.status]}
                    </span>
                  </div>
                  {preview?.event_at && <p><strong>计划时间：</strong>{formatEventTime(preview.event_at, preview.timezone)}（{preview.timezone}）</p>}
                  {preview?.job_label && <p><strong>关联岗位：</strong>{preview.job_label}</p>}
                  {preview?.details && <p><strong>补充说明：</strong>{preview.details}</p>}
                  {preview?.kind && preview.title && <p><strong>提醒类型：</strong>{KIND_LABELS[preview.kind] || preview.kind}</p>}
                  {plan.status === "needs_clarification" && <div className="agent-plan-notice">{preview?.clarification_question || "请补充具体日期和任务动作后重新创建。"}</div>}
                  {plan.status === "cancelling" && <p className="agent-plan-notice" role="status">正在等待当前模型请求结束；返回内容不会保存，也不会创建提醒。</p>}
                  {plan.status === "failed" && <div className="agent-task-error"><p>{plan.error_message || "任务规划失败。"}</p>
                    <button className="button button-secondary" type="button" disabled={busy || plan.attempt_count >= 3} onClick={() => void runAction(plan, "retry")}>重试</button>
                  </div>}
                  {plan.status === "confirmed" && <p className="agent-plan-confirmed">提醒已保存。<Link href="/reminders">打开提醒中心</Link></p>}
                  {plan.status === "awaiting_confirmation" && <div className="agent-plan-actions">
                    <button className="button button-primary" type="button" disabled={busy} onClick={() => void runAction(plan, "confirm")}>{busy ? "处理中…" : "确认并创建提醒"}</button>
                    <button className="button button-secondary" type="button" disabled={busy} onClick={() => void runAction(plan, "cancel")}>取消计划</button>
                  </div>}
                  {(plan.status === "queued" || plan.status === "running") && <div className="agent-plan-actions">
                    <button className="button button-secondary" type="button" disabled={busy} onClick={() => void runAction(plan, "cancel")}>{busy ? "处理中…" : "取消任务"}</button>
                  </div>}
                  {plan.status === "needs_clarification" && <div className="agent-plan-actions"><button className="button button-secondary" type="button" disabled={busy} onClick={() => void runAction(plan, "cancel")}>关闭</button></div>}
                </article>
              );
            })}
          </div>
        )}
      </section>
      <section className="profile-panel agent-planner-panel">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">跨工作流记录</p><h2>最近 Agent 运行</h2></div>
          <button className="button button-secondary" disabled={workspaceLoading} onClick={() => void loadWorkspace()} type="button">刷新</button>
        </div>
        {workspaceLoading ? <p className="empty-state">正在载入运行记录…</p> : !workspace?.recent_runs.some((run) => run.task_type !== "task_plan") ? (
          <p className="empty-state">岗位提取、岗位匹配、公司研究、个人资料问答和 Skills 等工作流的最近运行记录会显示在这里；提醒计划详见上方记录。</p>
        ) : (
          <ul className="agent-workspace-runs">
            {workspace.recent_runs.filter((run) => run.task_type !== "task_plan").map((run) => {
              const taskLabels: Record<string, string> = {
                job_extraction: "岗位信息提取",
                job_match: "岗位匹配分析",
                company_research: "公司研究",
                knowledge_qa: "个人资料问答",
                skill_workflow: run.skill_id ? `Skill · ${run.skill_id}` : "求职 Skill",
              };
              const statusLabels: Record<string, string> = {
                queued: "排队中", running: "运行中", succeeded: "已完成",
                failed: "失败", cancelled: "已取消", confirmed: "已确认",
              };
              const href = run.task_type === "skill_workflow"
                ? "/skills"
                : run.task_type === "company_research"
                  ? "/companies"
                  : run.task_type === "knowledge_qa"
                    ? "/knowledge"
                    : "/jobs";
              const telemetry = [
                run.duration_ms !== null ? `${run.duration_ms} ms` : null,
                run.total_tokens !== null ? `${run.total_tokens} tokens` : null,
                run.estimated_cost_usd !== null ? `$${run.estimated_cost_usd.toFixed(6)}` : null,
              ].filter(Boolean).join(" · ");
              return (
                <li key={run.id}>
                  <div><strong>{taskLabels[run.task_type] || "Agent 任务"}</strong><small>{run.job_label || "未关联岗位"} · {formatEventTime(run.created_at, workspace.timezone)}{telemetry ? ` · ${telemetry}` : ""}</small></div>
                  <span>{statusLabels[run.status] || run.status}</span>
                  <Link href={href}>打开</Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <p className="agent-planner-footnote">各工作流只在授权范围内读取资料。生成草稿不会自动改动投递状态；本地保存与外部邮件发送分别需要审批。MVP 不会登录或提交招聘网站，也不会代替用户完成测评。</p>
    </main>
  );
}
