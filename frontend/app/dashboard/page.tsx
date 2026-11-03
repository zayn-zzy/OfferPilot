"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  apiRequest,
  APPLICATION_STAGE_LABELS,
  type DashboardSummary,
} from "@/lib/api";

function formatPlainDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return `${year}年${month}月${day}日`;
}

function formatDateTime(value: string, timezone: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(value));
}

function agentTaskLabel(taskType: string) {
  const labels: Record<string, string> = {
    job_extraction: "岗位信息提取",
    company_research: "公司研究",
    task_plan: "自然语言任务计划",
    skill_workflow: "求职 Skill",
  };
  return labels[taskType] || "Agent 任务";
}

function agentStatusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: "排队中",
    running: "运行中",
    succeeded: "已完成",
    awaiting_confirmation: "待确认",
    needs_clarification: "待补充信息",
    confirmed: "已确认",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[status] || status;
}

function agentHref(taskType: string) {
  if (taskType === "task_plan") return "/agent";
  if (taskType === "skill_workflow") return "/skills";
  if (taskType === "company_research") return "/companies";
  return "/jobs";
}

export default function DashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 15000);

    apiRequest<DashboardSummary>("/api/v1/dashboard", { signal: controller.signal })
      .then((summary) => {
        if (active) setDashboard(summary);
      })
      .catch((cause) => {
        if (!active) return;
        setError(
          cause instanceof DOMException && cause.name === "AbortError"
            ? "工作台请求超时。请确认 API 服务可用后重试。"
            : cause instanceof Error ? cause.message : "无法载入求职工作台。",
        );
        setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      })
      .finally(() => window.clearTimeout(timeout));

    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, []);

  async function logout() {
    setLoggingOut(true);
    try {
      await apiRequest("/api/v1/auth/logout", { method: "POST" });
      window.location.assign("/login");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "退出登录失败，请重试。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      setLoggingOut(false);
    }
  }

  return (
    <main className="dashboard-shell dashboard-page">
      <header className="dashboard-topbar dashboard-page-topbar">
        <Link className="brand" href="/dashboard"><span className="brand-mark">O</span> OfferPilot</Link>
        <nav className="dashboard-actions" aria-label="主导航">
          <Link className="text-link" href="/profile">个人档案</Link>
          <Link className="text-link" href="/jobs">岗位管理</Link>
          <Link className="text-link" href="/companies">公司档案</Link>
          <Link className="text-link" href="/knowledge">资料问答</Link>
          <Link className="text-link" href="/agent">任务计划</Link>
          <Link className="text-link" href="/skills">Skills</Link>
          <Link className="text-link" href="/actions">外部动作</Link>
          <Link className="text-link" href="/reminders">提醒</Link>
          <Link className="text-link" href="/settings">设置</Link>
          <button className="text-button" disabled={loggingOut} onClick={() => void logout()} type="button">
            {loggingOut ? "正在退出…" : "退出登录"}
          </button>
        </nav>
      </header>

      {dashboard ? (
        <>
          <section className="dashboard-welcome dashboard-page-welcome">
            <p className="eyebrow">求职工作台 · {formatPlainDate(dashboard.today)}</p>
            <h1>你好，{dashboard.email}</h1>
            <p>按 {dashboard.timezone} 汇总你的投递进展、近期任务和招聘截止时间。</p>
          </section>

          {error && <div className="dashboard-error" role="alert">{error}</div>}

          <section className="dashboard-top-grid">
            <article className="dashboard-panel dashboard-stage-panel">
              <div className="dashboard-section-heading">
                <div><p className="eyebrow">投递进展</p><h2>当前阶段</h2></div>
                <Link className="text-link" href="/jobs">岗位列表</Link>
              </div>
              {dashboard.current_stage ? (
                <div className="dashboard-current-stage">
                  <span>{APPLICATION_STAGE_LABELS[dashboard.current_stage.status]}</span>
                  <strong>{dashboard.current_stage.job_label}</strong>
                  <small>最近更新于 {formatDateTime(dashboard.current_stage.updated_at, dashboard.timezone)}</small>
                </div>
              ) : (
                <div className="dashboard-empty-inline">
                  <p>还没有进行中的投递记录。</p>
                  <Link href="/jobs">从岗位卡片记录进度</Link>
                </div>
              )}
              <div className="dashboard-stage-counts" aria-label="各投递阶段数量">
                {dashboard.stage_counts.length ? dashboard.stage_counts.map((item) => (
                  <span key={item.status}>{APPLICATION_STAGE_LABELS[item.status]} <strong>{item.count}</strong></span>
                )) : <small>保存岗位并更新投递阶段后，这里会显示阶段数量。</small>}
              </div>
            </article>

            <article className="dashboard-panel dashboard-quick-panel">
              <p className="eyebrow">快捷入口</p>
              <h2>继续求职准备</h2>
              <div className="dashboard-quick-links">
                <Link className="button button-primary" href="/jobs">查看岗位</Link>
                <Link className="button button-secondary" href="/profile">完善档案与简历</Link>
                <Link className="dashboard-subtle-link" href="/agent">整理一个近期任务 →</Link>
              </div>
            </article>
          </section>

          <section className="dashboard-content-grid">
            <article className="dashboard-panel">
              <div className="dashboard-section-heading">
                <div><p className="eyebrow">未来 7 天</p><h2>近期待办</h2></div>
                <Link className="text-link" href="/reminders">提醒中心</Link>
              </div>
              {dashboard.upcoming_tasks.length ? (
                <ul className="dashboard-list">
                  {dashboard.upcoming_tasks.map((task) => (
                    <li key={`${task.kind}-${task.id}`}>
                      <span className="dashboard-list-marker">{task.kind === "reminder" ? task.status === "failed" ? "提醒失败" : "提醒" : "跟进"}</span>
                      <div className="dashboard-list-main">
                        <strong>{task.title}</strong>
                        <small>{task.job_label || "未关联岗位"} · {task.due_at ? formatDateTime(task.due_at, task.timezone) : task.due_date ? formatPlainDate(task.due_date) : "时间未设置"}</small>
                      </div>
                      <Link className="dashboard-list-link" href={task.kind === "reminder" ? "/reminders" : "/jobs"} aria-label={`打开${task.kind === "reminder" ? "提醒中心" : "岗位管理"}`}>打开</Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="dashboard-empty-state"><p>未来 7 天没有待办提醒或投递跟进。</p><Link href="/reminders">创建提醒</Link></div>
              )}
            </article>

            <article className="dashboard-panel">
              <div className="dashboard-section-heading">
                <div><p className="eyebrow">未来 14 天</p><h2>临近截止岗位</h2></div>
                <Link className="text-link" href="/jobs">全部岗位</Link>
              </div>
              {dashboard.approaching_deadlines.length ? (
                <ul className="dashboard-list dashboard-deadline-list">
                  {dashboard.approaching_deadlines.map((job) => (
                    <li key={job.job_id}>
                      <span className="dashboard-deadline-days">{job.days_remaining === 0 ? "今天" : `${job.days_remaining}天`}</span>
                      <div className="dashboard-list-main">
                        <strong>{job.job_label}</strong>
                        <small>{formatPlainDate(job.deadline)} 截止{job.application_status ? ` · ${APPLICATION_STAGE_LABELS[job.application_status]}` : " · 尚未记录投递进度"}</small>
                      </div>
                      <Link className="dashboard-list-link" href="/jobs">查看</Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="dashboard-empty-state"><p>未来 14 天没有已记录的岗位截止日期。</p><Link href="/jobs">添加或完善岗位</Link></div>
              )}
            </article>
          </section>

          <section className="dashboard-panel dashboard-agent-panel">
            <div className="dashboard-section-heading">
              <div><p className="eyebrow">任务记录</p><h2>最近 Agent 运行</h2></div>
              <Link className="text-link" href="/agent">任务计划</Link>
            </div>
            {dashboard.recent_agent_runs.length ? (
              <ul className="dashboard-list dashboard-agent-list">
                {dashboard.recent_agent_runs.map((run) => (
                  <li key={run.id}>
                    <span className={`dashboard-run-status dashboard-run-${run.status}`}>{agentStatusLabel(run.status)}</span>
                    <div className="dashboard-list-main">
                      <strong>{agentTaskLabel(run.task_type)}</strong>
                      <small>{run.job_label || "未关联岗位"} · {formatDateTime(run.created_at, dashboard.timezone)}</small>
                    </div>
                    <Link className="dashboard-list-link" href={agentHref(run.task_type)}>打开</Link>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="dashboard-empty-state"><p>还没有 Agent 任务记录。</p><Link href="/agent">规划近期任务</Link></div>
            )}
          </section>
          {error && requiresLogin && <p className="dashboard-login-hint"><Link href="/login">登录状态已失效，去登录</Link></p>}
        </>
      ) : error ? (
        <section className="dashboard-load-error" role="alert">
          <p>{error}</p>
          {requiresLogin ? <Link className="button button-primary" href="/login">去登录</Link> : <button className="button button-secondary" onClick={() => window.location.reload()} type="button">重新加载</button>}
        </section>
      ) : (
        <section className="dashboard-load-error"><p>正在载入你的求职工作台…</p></section>
      )}
    </main>
  );
}
