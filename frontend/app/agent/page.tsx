"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, apiRequest, type AgentTaskPlan, type AgentWorkspace } from "@/lib/api";
import styles from "./agent.module.css";

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

const RUN_TASK_LABELS: Record<string, string> = {
  job_extraction: "岗位信息提取",
  job_match: "岗位匹配分析",
  company_research: "公司研究",
  knowledge_qa: "个人资料问答",
  skill_workflow: "求职材料准备",
};

const RUN_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "处理失败",
  cancelled: "已取消",
  confirmed: "已确认",
};

type AgentActivity =
  | { type: "plan"; updatedAt: string; plan: AgentTaskPlan }
  | { type: "run"; updatedAt: string; run: NonNullable<AgentWorkspace>["recent_runs"][number] };

function isActionRequired(activity: AgentActivity) {
  return activity.type === "plan"
    && ["awaiting_confirmation", "needs_clarification", "failed"].includes(activity.plan.status);
}

function activityTitle(activity: AgentActivity) {
  if (activity.type === "plan") return activity.plan.preview?.title || "求职提醒计划";
  if (activity.run.task_type === "skill_workflow" && activity.run.skill_id) {
    return `求职材料准备：${activity.run.skill_id}`;
  }
  return RUN_TASK_LABELS[activity.run.task_type] || "Agent 任务";
}

function activityHref(activity: AgentActivity) {
  if (activity.type === "plan") return "/agent#task-planner";
  if (activity.run.task_type === "skill_workflow") return "/skills";
  if (activity.run.task_type === "company_research") return "/companies";
  if (activity.run.task_type === "knowledge_qa") return "/knowledge";
  return "/jobs";
}

function activityStatus(activity: AgentActivity) {
  if (activity.type === "plan") return STATUS_LABELS[activity.plan.status];
  return RUN_STATUS_LABELS[activity.run.status] || activity.run.status;
}

function activityTone(activity: AgentActivity) {
  const status = activity.type === "plan" ? activity.plan.status : activity.run.status;
  if (status === "failed") return "error";
  if (status === "confirmed" || status === "succeeded") return "success";
  if (["queued", "running", "cancelling", "awaiting_confirmation", "needs_clarification"].includes(status)) {
    return "pending";
  }
  return "neutral";
}

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

function apiErrorMessage(cause: unknown, fallback: string, loginMessage: string) {
  if (cause instanceof ApiError && cause.status === 401) return loginMessage;
  return cause instanceof Error ? cause.message : fallback;
}

export default function AgentTaskPlannerPage() {
  const [plans, setPlans] = useState<AgentTaskPlan[]>([]);
  const [workspace, setWorkspace] = useState<AgentWorkspace | null>(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [planListError, setPlanListError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceRequiresLogin, setWorkspaceRequiresLogin] = useState(false);
  const [showAllActivities, setShowAllActivities] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  const loadPlans = useCallback(async () => {
    try {
      setPlans(await apiRequest<AgentTaskPlan[]>("/api/v1/agent/task-plans?limit=20"));
      setPlanListError("");
      setRequiresLogin(false);
    } catch (cause) {
      setPlanListError(apiErrorMessage(cause, "无法载入提醒计划。", "登录后可查看提醒计划。"));
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadWorkspace = useCallback(async () => {
    try {
      setWorkspace(await apiRequest<AgentWorkspace>("/api/v1/agent/workspace"));
      setWorkspaceError("");
      setWorkspaceRequiresLogin(false);
    } catch (cause) {
      setWorkspaceError(apiErrorMessage(cause, "无法载入求职工作流。", "登录后可查看求职工作流和运行记录。"));
      setWorkspaceRequiresLogin(cause instanceof ApiError && cause.status === 401);
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

  const activities = useMemo<AgentActivity[]>(() => {
    const planItems: AgentActivity[] = plans.map((plan) => ({
      type: "plan",
      updatedAt: plan.updated_at,
      plan,
    }));
    const runItems: AgentActivity[] = (workspace?.recent_runs || []).map((run) => ({
      type: "run",
      updatedAt: run.updated_at,
      run,
    }));
    return [...planItems, ...runItems].sort((left, right) => {
      const priority = Number(isActionRequired(right)) - Number(isActionRequired(left));
      return priority || Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
    });
  }, [plans, workspace]);

  const visibleActivities = showAllActivities ? activities : activities.slice(0, 6);
  const moreActivityCount = activities.length - visibleActivities.length;

  async function refreshActivity() {
    setError("");
    await Promise.all([loadPlans(), loadWorkspace()]);
  }

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
      setPlanListError("");
      setPlans((current) => [plan, ...current.filter((item) => item.id !== plan.id)]);
      setNotice("已收到请求。提醒草稿生成后会先展示给你确认。");
      setRequiresLogin(false);
    } catch (cause) {
      setError(apiErrorMessage(cause, "无法创建提醒计划。", "登录状态已失效，请重新登录后再创建提醒。"));
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
      setError(apiErrorMessage(cause, "任务操作失败。", "登录状态已失效，请重新登录后再操作。"));
      if (cause instanceof ApiError && cause.status === 401) setRequiresLogin(true);
      await loadPlans();
    } finally {
      setWorkingId(null);
    }
  }

  const capabilities = (workspace?.capabilities || []).filter((item) => item.id !== "reminder_plan");
  const actionableCount = activities.filter(isActionRequired).length;
  const loadingActivities = loading || workspaceLoading;
  const loginRequired = (requiresLogin || workspaceRequiresLogin) && !loadingActivities;

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <Link className={styles.brand} href="/dashboard" aria-label="OfferPilot 工作台">
            <span className={styles.brandMark} aria-hidden="true">O</span>
            <span>OfferPilot</span>
          </Link>
          <nav className={styles.desktopNav} aria-label="主导航">
            <Link href="/dashboard">工作台</Link>
            <Link href="/agent" aria-current="page">Agent 工作区</Link>
            <Link href="/jobs">岗位管理</Link>
            <Link href="/reminders">提醒中心</Link>
            <Link href="/skills">Agent Skills</Link>
          </nav>
          <details className={styles.mobileNav}>
            <summary aria-label="展开主导航">菜单</summary>
            <nav aria-label="移动端主导航">
              <Link href="/dashboard">工作台</Link>
              <Link href="/agent" aria-current="page">Agent 工作区</Link>
              <Link href="/jobs">岗位管理</Link>
              <Link href="/reminders">提醒中心</Link>
              <Link href="/skills">Agent Skills</Link>
            </nav>
          </details>
        </div>
      </header>

      <main className={styles.container}>
        <div className={styles.pageHeading}>
          <div>
            <h1>Agent 工作区</h1>
            <p>选择求职工作流，查看待处理任务，或规划一条提醒。</p>
          </div>
        </div>

        {loginRequired ? (
          <div className={styles.alertError} role="alert">
            <p>登录后才能查看和使用 Agent 工作区。</p>
            <Link href="/login">去登录</Link>
          </div>
        ) : error && (
          <div className={styles.alertError} role="alert">
            <p>{error}</p>
            <button type="button" className={styles.textButton} onClick={() => void refreshActivity()}>
              刷新任务状态
            </button>
          </div>
        )}
        {notice && <p className={styles.noticeSuccess} role="status">{notice}</p>}

        <section className={styles.composer} id="task-planner" aria-labelledby="task-planner-title">
          <div className={styles.sectionHeading}>
            <div>
              <h2 id="task-planner-title">创建求职提醒</h2>
              <p>描述要做的事和日期。生成草稿后，你确认才会保存。</p>
            </div>
          </div>
          <form className={styles.plannerForm} onSubmit={createPlan}>
            <label htmlFor="task-request">提醒内容</label>
            <textarea
              id="task-request"
              value={text}
              onChange={(event) => { idempotencyKey.current = null; setText(event.target.value); }}
              placeholder="例如：周三前完成目标岗位的在线测评。"
              aria-describedby="task-request-help"
              rows={3}
              minLength={3}
              maxLength={4000}
              required
            />
            <div className={styles.formFooter}>
              <p id="task-request-help">未写具体时间时，按账户时区当天 09:00 安排。</p>
              <button className={styles.primaryButton} type="submit" disabled={submitting} aria-busy={submitting}>
                {submitting ? "正在生成草稿…" : "生成提醒草稿"}
              </button>
            </div>
          </form>
        </section>

        <div className={styles.workspaceGrid}>
          <section className={styles.workflowSection} aria-labelledby="agent-capabilities-title" aria-busy={workspaceLoading}>
            <div className={styles.sectionHeading}>
              <div>
                <h2 id="agent-capabilities-title">求职工作流</h2>
                <p>每项任务都会进入对应的工作区。</p>
              </div>
            </div>
            {workspaceError && !loginRequired && (
              <div className={styles.alertError} role="alert">
                <p>{workspaceError}</p>
                <button type="button" className={styles.textButton} onClick={() => void loadWorkspace()}>
                  重新载入
                </button>
              </div>
            )}
            {loginRequired ? (
              <div className={styles.emptyState}>
                <p>登录后将载入可用的求职工作流。</p>
              </div>
            ) : workspaceLoading ? (
              <div className={styles.skeletonList} role="status" aria-label="正在载入求职工作流">
                {Array.from({ length: 5 }, (_, index) => <div className={styles.skeletonRow} key={index} />)}
              </div>
            ) : workspaceError ? null : capabilities.length === 0 ? (
              <div className={styles.emptyState}>
                <p>当前没有可用的求职工作流。</p>
                <button type="button" className={styles.secondaryButton} onClick={() => void loadWorkspace()}>重新载入工作流</button>
              </div>
            ) : (
              <ul className={styles.workflowList}>
                {capabilities.map((capability) => (
                  <li className={styles.workflowRow} key={capability.id}>
                    <div className={styles.workflowCopy}>
                      <h3>{capability.title}</h3>
                      <p>{capability.description}</p>
                    </div>
                    <span className={capability.action_level === "read_only" ? styles.modeReadOnly : styles.modeDraft}>
                      {capability.action_level === "read_only"
                        ? "只读"
                        : capability.confirmation_required ? "草稿，需确认" : "生成草稿"}
                    </span>
                    <Link className={styles.workflowAction} href={capability.href}>
                      {capability.action_label}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className={styles.activitySection} aria-labelledby="activity-title" aria-busy={loadingActivities}>
            <div className={styles.sectionHeading}>
              <div>
                <h2 id="activity-title">任务记录</h2>
                {actionableCount > 0 && <p className={styles.actionableHint}>{actionableCount} 项需要你处理</p>}
              </div>
              <button
                type="button"
                className={styles.secondaryButton}
                onClick={() => void refreshActivity()}
                disabled={loadingActivities}
              >
                {loadingActivities ? "正在更新…" : "刷新"}
              </button>
            </div>

            {planListError && !requiresLogin && (
              <div className={styles.inlineError} role="alert">
                <p>{planListError}</p>
                <button className={styles.secondaryButton} type="button" onClick={() => void loadPlans()}>重新载入提醒计划</button>
              </div>
            )}
            {workspaceError && !workspaceRequiresLogin && (
              <div className={styles.inlineError} role="alert">
                <p>Agent 运行记录暂时不可用，提醒计划会单独显示。</p>
                <button className={styles.secondaryButton} type="button" onClick={() => void loadWorkspace()}>重新载入运行记录</button>
              </div>
            )}
            {loadingActivities && activities.length === 0 ? (
              <div className={styles.skeletonList} role="status" aria-label="正在载入任务记录">
                {Array.from({ length: 3 }, (_, index) => <div className={styles.skeletonRow} key={index} />)}
              </div>
            ) : activities.length === 0 && !planListError && !workspaceError && !loginRequired ? (
              <div className={styles.emptyState}>
                <p>还没有 Agent 任务记录。创建提醒或选择一个求职工作流后，记录会显示在这里。</p>
                <a href="#task-request">规划一条提醒</a>
              </div>
            ) : activities.length > 0 ? (
              <>
                <ul className={styles.activityList}>
                  {visibleActivities.map((activity) => {
                    const isPlan = activity.type === "plan";
                    const plan = activity.type === "plan" ? activity.plan : null;
                    const run = activity.type === "run" ? activity.run : null;
                    const preview = plan?.preview;
                    const busy = plan !== null && workingId === plan.id;
                    const href = activityHref(activity);
                    const tone = activityTone(activity);
                    const toneClass = tone === "error"
                      ? styles.statusError
                      : tone === "success"
                        ? styles.statusSuccess
                        : tone === "pending"
                          ? styles.statusPending
                          : styles.statusNeutral;

                    return (
                      <li className={styles.activityRow} key={`${activity.type}-${isPlan ? plan?.id : run?.id}`}>
                        <div className={styles.activityHeading}>
                          <div className={styles.activityTitleBlock}>
                            <span className={styles.activityType}>{isPlan ? "提醒计划" : "Agent 运行"}</span>
                            <h3>{activityTitle(activity)}</h3>
                            <p className={styles.activityMeta}>
                              {isPlan
                                ? formatEventTime(plan!.updated_at, workspace?.timezone || "Asia/Shanghai")
                                : formatEventTime(run!.created_at, workspace?.timezone || "Asia/Shanghai")}
                              {(preview?.job_label || run?.job_label) && <> · {preview?.job_label || run?.job_label}</>}
                            </p>
                          </div>
                          <span className={`${styles.status} ${toneClass}`}>
                            {activityStatus(activity)}
                          </span>
                        </div>

                        {plan && (
                          <>
                            {(plan.status === "awaiting_confirmation" || preview?.event_at || preview?.details || preview?.kind) && (
                              <details className={styles.activityDetails} open={plan.status === "awaiting_confirmation"}>
                                <summary>{plan.status === "awaiting_confirmation" ? "核对提醒内容" : "查看提醒内容"}</summary>
                                <dl>
                                  {preview?.event_at && <><dt>提醒时间</dt><dd>{formatEventTime(preview.event_at, preview.timezone)}（{preview.timezone}）</dd></>}
                                  {preview?.job_label && <><dt>关联岗位</dt><dd>{preview.job_label}</dd></>}
                                  {preview?.kind && <><dt>提醒类型</dt><dd>{KIND_LABELS[preview.kind] || preview.kind}</dd></>}
                                  {preview?.details && <><dt>补充说明</dt><dd>{preview.details}</dd></>}
                                  {!preview && <><dt>提醒内容</dt><dd>暂时没有可展示的预览。</dd></>}
                                </dl>
                              </details>
                            )}
                            {plan.status === "needs_clarification" && (
                              <p className={styles.inlineNotice}>{preview?.clarification_question || "请补充具体日期和任务动作后重新创建。"}</p>
                            )}
                            {plan.status === "cancelling" && (
                              <p className={styles.inlineNotice} role="status">正在等待当前模型请求结束；返回内容不会保存，也不会创建提醒。</p>
                            )}
                            {plan.status === "failed" && (
                              <div className={styles.inlineError}>
                                <p>{plan.error_message || "任务规划失败。"}</p>
                                <button
                                  className={styles.secondaryButton}
                                  type="button"
                                  disabled={busy || plan.attempt_count >= 3}
                                  onClick={() => void runAction(plan, "retry")}
                                >
                                  {plan.attempt_count >= 3 ? "已达到重试上限" : busy ? "正在重试…" : "重试任务"}
                                </button>
                              </div>
                            )}
                            {plan.status === "confirmed" && (
                              <p className={styles.inlineSuccess}>提醒已保存。<Link href="/reminders">打开提醒中心</Link></p>
                            )}
                            {plan.status === "awaiting_confirmation" && (
                              <div className={styles.rowActions}>
                                <button className={styles.primaryButton} type="button" disabled={busy} onClick={() => void runAction(plan, "confirm")}>
                                  {busy ? "处理中…" : "确认并创建提醒"}
                                </button>
                                <button className={styles.secondaryButton} type="button" disabled={busy} onClick={() => void runAction(plan, "cancel")}>
                                  取消计划
                                </button>
                              </div>
                            )}
                            {(plan.status === "queued" || plan.status === "running") && (
                              <div className={styles.rowActions}>
                                <button className={styles.secondaryButton} type="button" disabled={busy} onClick={() => void runAction(plan, "cancel")}>
                                  {busy ? "处理中…" : "取消任务"}
                                </button>
                              </div>
                            )}
                            {plan.status === "needs_clarification" && (
                              <div className={styles.rowActions}>
                                <button className={styles.secondaryButton} type="button" disabled={busy} onClick={() => void runAction(plan, "cancel")}>关闭计划</button>
                              </div>
                            )}
                          </>
                        )}

                        {run && (
                          <>
                            <div className={styles.rowActions}>
                              <Link className={styles.workflowAction} href={href}>打开相关工作区</Link>
                            </div>
                            {(run.duration_ms !== null || run.total_tokens !== null || run.estimated_cost_usd !== null) && (
                              <details className={styles.activityDetails}>
                                <summary>查看运行信息</summary>
                                <dl>
                                  <dt>更新时间</dt><dd>{formatEventTime(run.updated_at, workspace?.timezone || "Asia/Shanghai")}</dd>
                                  {run.duration_ms !== null && <><dt>耗时</dt><dd>{run.duration_ms} ms</dd></>}
                                  {run.total_tokens !== null && <><dt>Token</dt><dd>{run.total_tokens}</dd></>}
                                  {run.estimated_cost_usd !== null && <><dt>估算费用</dt><dd>${run.estimated_cost_usd.toFixed(6)}</dd></>}
                                </dl>
                              </details>
                            )}
                          </>
                        )}
                      </li>
                    );
                  })}
                </ul>
                {moreActivityCount > 0 && (
                  <button className={styles.showMoreButton} type="button" onClick={() => setShowAllActivities(true)}>
                    显示另外 {moreActivityCount} 项记录
                  </button>
                )}
                {loadingActivities && <p className={styles.loadingHint} role="status">正在同步最新任务状态…</p>}
              </>
            ) : (
              <div className={styles.emptyState}>
                <p>{loginRequired ? "登录后会显示你的任务记录。" : "载入成功后，任务记录会显示在这里。"}</p>
              </div>
            )}
          </section>
        </div>

        <p className={styles.privacyNote}>各工作流只在授权范围内读取资料。生成草稿不会自动改动投递状态；本地保存与外部邮件发送分别需要审批。MVP 不会登录或提交招聘网站，也不会代替用户完成测评。</p>
      </main>
    </div>
  );
}
