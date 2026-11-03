"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  apiRequest,
  type ExternalAction,
  type ExternalActionCapabilities,
  type JobPosting,
  type SkillRun,
} from "@/lib/api";

const STATUS_LABELS: Record<ExternalAction["status"], string> = {
  pending: "等待审批",
  approved: "已批准，等待发送",
  executing: "发送中",
  executed: "已发送",
  rejected: "已拒绝",
  expired: "已过期",
  invalidated: "审批失效",
  outcome_unknown: "发送结果待核对",
};

function labelJob(job: JobPosting | undefined) {
  if (!job) return "岗位已删除或不可用";
  return [job.company_name, job.title].filter(Boolean).join(" · ") || "未命名岗位";
}

export default function ExternalActionsPage() {
  const [actions, setActions] = useState<ExternalAction[]>([]);
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [capabilities, setCapabilities] = useState<ExternalActionCapabilities | null>(null);
  const [recipient, setRecipient] = useState("");
  const [jobId, setJobId] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  const loadActions = useCallback(async () => {
    const results = await Promise.allSettled([
      apiRequest<ExternalAction[]>("/api/v1/external-actions"),
      apiRequest<ExternalActionCapabilities>("/api/v1/external-actions/capabilities"),
      apiRequest<JobPosting[]>("/api/v1/jobs"),
    ]);
    const [actionResult, capabilityResult, jobResult] = results;
    if (actionResult.status === "fulfilled") setActions(actionResult.value);
    if (capabilityResult.status === "fulfilled") setCapabilities(capabilityResult.value);
    if (jobResult.status === "fulfilled") setJobs(jobResult.value);
    const failure = results.find((result) => result.status === "rejected");
    if (failure?.status === "rejected") {
      setError(failure.reason instanceof Error ? failure.reason.message : "无法载入外部动作。");
      setRequiresLogin(failure.reason instanceof ApiError && failure.reason.status === 401);
    } else {
      setError("");
      setRequiresLogin(false);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadActions();
  }, [loadActions]);

  const hasExecutingAction = actions.some((action) => action.status === "executing");
  useEffect(() => {
    if (!hasExecutingAction) return;
    const timer = window.setInterval(() => void loadActions(), 1500);
    return () => window.clearInterval(timer);
  }, [hasExecutingAction, loadActions]);

  useEffect(() => {
    const runId = new URLSearchParams(window.location.search).get("skill_run_id");
    if (!runId) return;
    apiRequest<SkillRun[]>("/api/v1/skills/runs?limit=20")
      .then((runs) => {
        const run = runs.find((item) => item.id === runId && item.status === "succeeded");
        if (!run?.result || run.skill_id !== "application_answers") {
          setError("找不到可用的申请问答草稿，请回 Skills 页面检查任务状态。");
          return;
        }
        const sections = run.result.sections.map((section) => section.title + "\n" + section.content);
        const draft = [run.result.summary, ...sections].filter(Boolean).join("\n\n");
        setJobId(run.job_id);
        setBody(draft.slice(0, 20_000));
        setSubject("求职申请问题回复草稿");
        setNotice("已载入 Agent 生成的申请问答草稿。请逐句核对并补充真实信息，再创建审批；尚未发送。");
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "无法载入 Agent 草稿。"));
  }, []);

  function markDraftChanged() {
    idempotencyKey.current = null;
  }

  async function createAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!capabilities?.email_send_enabled) {
      setError("邮件执行器未配置，请先设置服务端 SMTP 环境变量。");
      return;
    }
    setWorking(true);
    setError("");
    setNotice("");
    idempotencyKey.current ??= window.crypto.randomUUID();
    try {
      const action = await apiRequest<ExternalAction>("/api/v1/external-actions", {
        method: "POST",
        body: JSON.stringify({
          recipient,
          job_id: jobId || null,
          subject,
          body,
          idempotency_key: idempotencyKey.current,
        }),
      });
      setActions((current) => [action, ...current.filter((item) => item.id !== action.id)]);
      setNotice("邮件已保存为待审批动作，尚未发送。请核对完整收件人、主题和正文。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法创建邮件审批。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setWorking(false);
    }
  }

  async function runAction(action: ExternalAction, operation: "approve" | "reject" | "execute") {
    if (operation === "execute") {
      const confirmed = window.confirm(
        "即将通过已配置的 SMTP 服务发送邮件。\n\n收件人：" + action.target
          + "\n主题：" + action.payload.subject
          + "\n\n发送后无法由 OfferPilot 撤回。确认发送？",
      );
      if (!confirmed) return;
    }
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const updated = await apiRequest<ExternalAction>(
        "/api/v1/external-actions/" + action.id + "/" + operation,
        { method: "POST" },
      );
      setActions((current) => current.map((item) => item.id === updated.id ? updated : item));
      setNotice(operation === "approve"
        ? "动作已批准。邮件仍未发送，需要再次点击发送并确认。"
        : operation === "reject"
          ? "动作已拒绝，没有发送邮件。"
          : "邮件服务已接受发送请求。请检查邮件账户中的已发送记录。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "外部动作执行失败。");
      await loadActions();
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="skills-shell">
      <header className="dashboard-topbar skills-topbar">
        <Link className="brand" href="/"><span className="brand-mark">O</span> OfferPilot</Link>
        <nav className="dashboard-actions" aria-label="主导航">
          <Link className="text-link" href="/dashboard">工作台</Link>
          <Link className="text-link" href="/agent">任务计划</Link>
          <Link className="text-link" href="/skills">Skills</Link>
          <Link className="text-link" href="/jobs">岗位管理</Link>
        </nav>
      </header>

      <section className="profile-heading skills-heading">
        <p className="eyebrow">F-17 · 外部动作审批</p>
        <h1>先核对，再发送。</h1>
        <p>邮件正文和收件人由你最终确认。创建、审批和发送是分开的步骤；招聘网站提交与测评动作未开放。</p>
      </section>

      {error && <div className="profile-message profile-error" role="alert">{error}{requiresLogin && <> <Link href="/login">去登录</Link></>}</div>}
      {notice && <div className="profile-message profile-success" role="status">{notice}</div>}
      {loading && <p className="profile-loading">正在载入动作审批记录…</p>}

      <section className="profile-panel skills-panel">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">允许的执行器</p><h2>发送一封纯文本邮件</h2></div>
          <span className={"skill-run-status " + (capabilities?.email_send_enabled ? "skill-run-succeeded" : "skill-run-failed")}>
            {capabilities?.email_send_enabled ? "SMTP 已配置" : "SMTP 未配置"}
          </span>
        </div>
        {!capabilities?.email_send_enabled && <p className="external-action-warning">
          在后端环境配置 OFFERPILOT_SMTP_HOST、OFFERPILOT_SMTP_USERNAME、OFFERPILOT_SMTP_PASSWORD 和 OFFERPILOT_SMTP_SENDER 后，重启 API 才能创建和执行邮件动作。端口 587 使用 STARTTLS；465 使用隐式 TLS。
        </p>}
        <p className="external-action-warning">邮件正文和收件人会发送到服务端配置的 SMTP 邮件服务。执行前请确认事实、附件说明和收件地址；邮件发送后可能无法撤回。</p>
        <form className="external-action-form" onSubmit={createAction}>
          <label>关联岗位（选填）
            <select value={jobId} onChange={(event) => { markDraftChanged(); setJobId(event.target.value); }}>
              <option value="">不关联岗位</option>
              {jobs.map((job) => <option key={job.id} value={job.id}>{labelJob(job)}</option>)}
            </select>
          </label>
          <label>收件人邮箱
            <input autoComplete="email" required type="email" maxLength={320} value={recipient} onChange={(event) => { markDraftChanged(); setRecipient(event.target.value); }} placeholder="recruiter@example.com" />
          </label>
          <label>邮件主题
            <input required maxLength={200} value={subject} onChange={(event) => { markDraftChanged(); setSubject(event.target.value); }} placeholder="应聘后端开发工程师 - 张同学" />
          </label>
          <label>邮件正文
            <textarea required maxLength={20000} rows={9} value={body} onChange={(event) => { markDraftChanged(); setBody(event.target.value); }} placeholder="粘贴你已核对的邮件正文。Agent 草稿也必须由你检查后再使用。" />
          </label>
          <div className="external-action-controls">
            <button className="button button-primary" disabled={working || loading || !capabilities?.email_send_enabled} type="submit">
              {working ? "处理中…" : "创建待审批邮件"}
            </button>
            <span>创建只保存待审批记录，不会发送邮件；审批 15 分钟后过期。</span>
          </div>
        </form>
      </section>

      <section className="profile-panel skills-panel">
        <div className="profile-panel-heading"><div><p className="eyebrow">逐项审批与审计</p><h2>外部动作记录</h2></div></div>
        {actions.length === 0 ? <p className="empty-state">目前没有外部动作记录。</p> : <div className="external-action-list">
          {actions.map((action) => <article className="external-action-card" key={action.id}>
            <div className="external-action-card-heading">
              <div><p className="eyebrow">{action.action_type} · {action.job_id ? labelJob(jobs.find((job) => job.id === action.job_id)) : "未关联岗位"}</p><h3>{action.payload.subject}</h3></div>
              <span className={"skill-run-status skill-run-" + action.status}>{STATUS_LABELS[action.status]}</span>
            </div>
            <p><strong>收件人：</strong>{action.target}</p>
            <p className="external-action-summary">{action.summary}</p>
            <pre className="external-action-body">{action.payload.body}</pre>
            <small>创建于 {new Date(action.created_at).toLocaleString("zh-CN")} · 审批有效期至 {new Date(action.expires_at).toLocaleString("zh-CN")}</small>
            {action.status === "pending" && <div className="external-action-buttons">
              <button className="button button-primary" disabled={working} onClick={() => void runAction(action, "approve")} type="button">核对后批准</button>
              <button className="button button-secondary" disabled={working} onClick={() => void runAction(action, "reject")} type="button">拒绝</button>
            </div>}
            {action.status === "approved" && <div className="external-action-buttons">
              <button className="button button-primary" disabled={working} onClick={() => void runAction(action, "execute")} type="button">最终确认并发送</button>
            </div>}
            {action.status === "executed" && <p className="skill-approval-status">SMTP 接受发送请求。Message-ID：{String(action.result?.message_id ?? "未返回")}</p>}
            {action.status === "outcome_unknown" && <p className="external-action-warning" role="status">服务未能确认邮件是否送达。先检查邮箱“已发送”和收件人邮箱；系统不会自动重试，避免重复发送。</p>}
          </article>)}
        </div>}
      </section>
    </main>
  );
}
