"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  apiRequest,
  type ApplicationPrepPack,
  type JobPosting,
  type SkillApproval,
  type SkillAuditEvent,
  type SkillCatalogItem,
  type SkillId,
  type SkillRun,
} from "@/lib/api";

const STATUS_LABELS: Record<SkillRun["status"], string> = {
  queued: "排队中",
  running: "运行中",
  cancelling: "取消中",
  succeeded: "待检查",
  failed: "失败",
  cancelled: "已取消",
};

const APPROVAL_LABELS: Record<SkillApproval["status"], string> = {
  pending: "等待确认",
  approved: "已批准，等待保存",
  rejected: "已拒绝",
  expired: "已过期",
  executed: "已保存",
  invalidated: "内容变化，审批失效",
};

function jobLabel(job: JobPosting | undefined) {
  if (!job) return "岗位已删除或不可用";
  return [job.company_name, job.title].filter(Boolean).join(" · ") || "未命名岗位";
}

export default function SkillsPage() {
  const [skills, setSkills] = useState<SkillCatalogItem[]>([]);
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [runs, setRuns] = useState<SkillRun[]>([]);
  const [approvals, setApprovals] = useState<SkillApproval[]>([]);
  const [packs, setPacks] = useState<ApplicationPrepPack[]>([]);
  const [auditEvents, setAuditEvents] = useState<SkillAuditEvent[]>([]);
  const [skillId, setSkillId] = useState<SkillId>("application_prep_pack");
  const [jobId, setJobId] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  const jobsById = useMemo(() => new Map(jobs.map((job) => [job.id, job])), [jobs]);
  const activeSkill = skills.find((skill) => skill.id === skillId);
  const activeRun = runs.find((run) => run.id === activeRunId) ?? runs[0];
  const latestRunApproval = approvals.find((approval) => approval.agent_run_id === activeRun?.id);
  const activeApproval = approvals.find(
    (approval) => approval.agent_run_id === activeRun?.id
      && ["pending", "approved"].includes(approval.status)
      && new Date(approval.expires_at).getTime() > Date.now(),
  );
  const canRequestApproval = activeRun?.skill_id === "application_prep_pack"
    && activeRun.status === "succeeded"
    && !activeApproval
    && (!latestRunApproval || latestRunApproval.status === "expired");
  const hasQuestionInput = skillId === "application_answers" || skillId === "application_prep_pack";
  const usesResume = ["resume_targeting", "application_answers", "interview_prep", "application_prep_pack"].includes(skillId);

  const loadWorkspace = useCallback(async () => {
    const results = await Promise.allSettled([
      apiRequest<SkillCatalogItem[]>("/api/v1/skills"),
      apiRequest<JobPosting[]>("/api/v1/jobs"),
      apiRequest<SkillRun[]>("/api/v1/skills/runs?limit=20"),
      apiRequest<SkillApproval[]>("/api/v1/skills/approvals"),
      apiRequest<ApplicationPrepPack[]>("/api/v1/skills/packs?limit=50"),
      apiRequest<SkillAuditEvent[]>("/api/v1/skills/audit?limit=50"),
    ]);
    const [skillResult, jobResult, runResult, approvalResult, packResult, auditResult] = results;
    if (skillResult.status === "fulfilled") setSkills(skillResult.value);
    if (jobResult.status === "fulfilled") setJobs(jobResult.value);
    if (runResult.status === "fulfilled") setRuns(runResult.value);
    if (approvalResult.status === "fulfilled") setApprovals(approvalResult.value);
    if (packResult.status === "fulfilled") setPacks(packResult.value);
    if (auditResult.status === "fulfilled") setAuditEvents(auditResult.value);
    const failure = results.find((result) => result.status === "rejected");
    if (failure?.status === "rejected") {
      setError(failure.reason instanceof Error ? failure.reason.message : "无法载入求职工作流。");
      setRequiresLogin(failure.reason instanceof ApiError && failure.reason.status === 401);
    } else {
      setError("");
      setRequiresLogin(false);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    const hasActiveRun = runs.some((run) => ["queued", "running", "cancelling"].includes(run.status));
    if (!hasActiveRun) return;
    const timer = window.setInterval(() => {
      void apiRequest<SkillRun[]>("/api/v1/skills/runs?limit=20")
        .then(setRuns)
        .catch((cause) => setError(cause instanceof Error ? cause.message : "无法刷新任务状态。"));
    }, 1600);
    return () => window.clearInterval(timer);
  }, [runs]);

  function updateInput(callback: () => void) {
    idempotencyKey.current = null;
    callback();
  }

  async function createRun(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!jobId) {
      setError("请先选择一个岗位。");
      return;
    }
    const questions = questionText.split("\n").map((value) => value.trim()).filter(Boolean);
    if (skillId === "application_answers" && questions.length === 0) {
      setError("申请问答技能需要至少一个真实的申请问题，每行一题。");
      return;
    }
    setWorking(true);
    setError("");
    setNotice("");
    idempotencyKey.current ??= window.crypto.randomUUID();
    try {
      const run = await apiRequest<SkillRun>("/api/v1/skills/runs", {
        method: "POST",
        body: JSON.stringify({
          skill_id: skillId,
          job_id: jobId,
          questions,
          idempotency_key: idempotencyKey.current,
        }),
      });
      idempotencyKey.current = null;
      setActiveRunId(run.id);
      setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      setNotice("任务已创建。结果会先作为草稿展示，不会自动修改投递状态或提交到招聘网站。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法创建求职任务。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setWorking(false);
    }
  }

  async function runAction(run: SkillRun, action: "retry" | "cancel") {
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const updated = await apiRequest<SkillRun>(`/api/v1/skills/runs/${run.id}/${action}`, {
        method: "POST",
      });
      setActiveRunId(updated.id);
      setRuns((current) => [updated, ...current.filter((item) => item.id !== updated.id)]);
      setNotice(action === "retry"
        ? "已安排任务重试。"
        : updated.status === "cancelling"
          ? "已请求取消；模型响应完成后会丢弃结果。"
          : "任务已取消。模型结果不会保存。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "任务操作失败。");
    } finally {
      setWorking(false);
    }
  }

  async function requestApproval(run: SkillRun) {
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const approval = await apiRequest<SkillApproval>(`/api/v1/skills/runs/${run.id}/approval`, {
        method: "POST",
      });
      setApprovals((current) => [approval, ...current.filter((item) => item.id !== approval.id)]);
      setNotice("审批已创建。请核对具体操作后，再批准并保存到本地工作台。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法创建审批请求。");
    } finally {
      setWorking(false);
    }
  }

  async function approveAndSave(approval: SkillApproval) {
    if (!window.confirm(`${approval.summary}\n\n确认后只保存到 OfferPilot，不会提交招聘网站。`)) return;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      if (approval.status === "pending") {
        const approved = await apiRequest<SkillApproval>(`/api/v1/skills/approvals/${approval.id}/approve`, {
          method: "POST",
        });
        setApprovals((current) => current.map((item) => item.id === approved.id ? approved : item));
      }
      const pack = await apiRequest<ApplicationPrepPack>(`/api/v1/skills/approvals/${approval.id}/execute`, {
        method: "POST",
      });
      setPacks((current) => [pack, ...current.filter((item) => item.id !== pack.id)]);
      setNotice("申请准备包已保存。你仍需自行核对内容并复制到招聘网站。");
      await loadWorkspace();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存申请准备包失败。");
      await loadWorkspace();
    } finally {
      setWorking(false);
    }
  }

  async function rejectApproval(approval: SkillApproval) {
    setWorking(true);
    setError("");
    try {
      const rejected = await apiRequest<SkillApproval>(`/api/v1/skills/approvals/${approval.id}/reject`, {
        method: "POST",
      });
      setApprovals((current) => current.map((item) => item.id === rejected.id ? rejected : item));
      setNotice("审批已拒绝，没有保存准备包。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法拒绝审批。");
    } finally {
      setWorking(false);
    }
  }

  async function logout() {
    await apiRequest("/api/v1/auth/logout", { method: "POST" });
    window.location.assign("/login");
  }

  return (
    <main className="skills-shell">
      <header className="dashboard-topbar skills-topbar">
        <Link className="brand" href="/"><span className="brand-mark">O</span> OfferPilot</Link>
        <nav className="dashboard-actions" aria-label="主导航">
          <Link className="text-link" href="/dashboard">工作台</Link>
          <Link className="text-link" href="/profile">个人档案</Link>
          <Link className="text-link" href="/knowledge">资料问答</Link>
          <Link className="text-link" href="/jobs">岗位管理</Link>
          <Link className="text-link" href="/reminders">提醒中心</Link>
          <Link className="text-link" href="/actions">外部动作</Link>
          <button className="text-button" onClick={() => void logout()} type="button">退出登录</button>
        </nav>
      </header>

      <section className="profile-heading skills-heading">
        <p className="eyebrow">Agent 工作区 · 版本化 Skills</p>
        <h1>把重复的求职准备变成可检查的草稿。</h1>
        <p>每个工作流都会记录模板版本、运行阶段和引用。Agent 只生成草稿；保存前需要你检查并审批。</p>
      </section>

      {error && <div className="profile-message profile-error" role="alert">{error}{requiresLogin && <> <Link href="/login">去登录</Link></>}</div>}
      {notice && <div className="profile-message profile-success" role="status">{notice}</div>}
      {loading && <p className="profile-loading">正在载入 Skills 与岗位…</p>}

      <section className="profile-panel skills-panel">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">任务计划</p><h2>选择求职 Skill</h2></div>
          <span className="skill-version-pill">{activeSkill ? `模板 v${activeSkill.version}` : "加载模板中"}</span>
        </div>
        <div className="skill-template-grid" role="list" aria-label="求职 Skill 模板">
          {skills.map((skill) => (
            <button
              aria-pressed={skillId === skill.id}
              className={`skill-template ${skillId === skill.id ? "skill-template-selected" : ""}`}
              key={skill.id}
              onClick={() => updateInput(() => setSkillId(skill.id))}
              type="button"
            >
              <strong>{skill.name}</strong>
              <span>{skill.description}</span>
              <small>v{skill.version}</small>
            </button>
          ))}
        </div>
        {activeSkill && <div className="skill-boundaries"><strong>运行边界</strong><ul>{activeSkill.boundaries.map((boundary) => <li key={boundary}>{boundary}</li>)}</ul></div>}
        {activeSkill && <details className="skill-contract-details">
          <summary>查看输入 / 输出结构与模板示例</summary>
          <div className="skill-contract-grid">
            <section><strong>输入</strong><pre>{JSON.stringify(activeSkill.inputs, null, 2)}</pre></section>
            <section><strong>输出</strong><pre>{JSON.stringify(activeSkill.outputs, null, 2)}</pre></section>
            <section><strong>输入示例</strong><pre>{JSON.stringify(activeSkill.example_input, null, 2)}</pre></section>
            <section><strong>输出示例</strong><pre>{JSON.stringify(activeSkill.example_output, null, 2)}</pre></section>
          </div>
        </details>}

        <form className="skill-run-form" onSubmit={createRun}>
          <label>目标岗位
            <select required value={jobId} onChange={(event) => updateInput(() => setJobId(event.target.value))}>
              <option value="">选择一个已保存岗位</option>
              {jobs.map((job) => <option key={job.id} value={job.id}>{jobLabel(job)}</option>)}
            </select>
          </label>
          {hasQuestionInput && <label className="skill-questions-field">申请问题（每行一个；申请问答 Skill 必填，申请准备包可留空）
            <textarea maxLength={8000} rows={4} value={questionText} onChange={(event) => updateInput(() => setQuestionText(event.target.value))} placeholder="例如：请介绍一次你用数据解决问题的经历。" />
          </label>}
          {usesResume && <p className="skill-privacy-note">此 Skill 可能读取你最新的已确认简历和个人档案，并发送给服务端配置的模型服务以生成草稿。岗位描述和公开研究片段也会作为不可信资料；请检查服务提供方的隐私政策。</p>}
          {jobs.length === 0 && <p className="empty-state">还没有可用岗位。先到岗位管理添加岗位。</p>}
          <div className="skill-run-actions">
            <button className="button button-primary" disabled={working || loading || jobs.length === 0} type="submit">{working ? "处理中…" : "生成可检查草稿"}</button>
            <span>当前运行最多 3 次；失败可重试，模型输出不会自动改动业务记录。</span>
          </div>
        </form>
      </section>

      <section className="profile-panel skills-panel">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">运行记录</p><h2>最近的 Agent 任务</h2></div>
        </div>
        {runs.length === 0 ? <p className="empty-state">尚无 Skill 运行记录。</p> : <div className="skill-run-list">
          {runs.map((run) => {
            const skill = skills.find((item) => item.id === run.skill_id);
            return <button className={`skill-run-row ${activeRunId === run.id ? "skill-run-row-selected" : ""}`} key={run.id} onClick={() => setActiveRunId(run.id)} type="button">
              <span><strong>{skill?.name ?? run.skill_id}</strong><small>{jobLabel(jobsById.get(run.job_id))} · v{run.skill_version}</small></span>
              <em className={`skill-run-status skill-run-${run.status}`}>{STATUS_LABELS[run.status]}</em>
            </button>;
          })}
        </div>}

        {activeRun && <article className="skill-result">
          <div className="skill-result-heading">
            <div><p className="eyebrow">{skills.find((item) => item.id === activeRun.skill_id)?.name ?? activeRun.skill_id} · v{activeRun.skill_version}</p><h3>{jobLabel(jobsById.get(activeRun.job_id))}</h3></div>
            <span className={`skill-run-status skill-run-${activeRun.status}`}>{STATUS_LABELS[activeRun.status]}</span>
          </div>
          {activeRun.events.length > 0 && <ol className="agent-task-events">{activeRun.events.map((event) => <li key={`${activeRun.id}-${event.id}`}><span>{event.message}</span><time>{new Date(event.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time></li>)}</ol>}
          {activeRun.error_message && <div className="agent-task-error"><p>{activeRun.error_message}</p>{activeRun.status === "failed" && activeRun.attempt_count < 3 && <button className="button button-secondary" disabled={working} onClick={() => void runAction(activeRun, "retry")} type="button">重试任务</button>}</div>}
          {activeRun.status === "cancelling" && <p className="agent-plan-notice" role="status">正在等待当前模型请求结束；返回内容不会保存。</p>}
          {(activeRun.status === "queued" || activeRun.status === "running") && <button className="button button-secondary" disabled={working} onClick={() => void runAction(activeRun, "cancel")} type="button">取消任务</button>}

          {activeRun.result && <div className="skill-draft-result">
            <p className="skill-draft-summary">{activeRun.result.summary}</p>
            {activeRun.result.warnings.map((warning) => <p className="skill-warning" key={warning}>{warning}</p>)}
            {activeRun.result.checklist.length > 0 && <section><h4>材料与准备清单</h4><ul className="skill-checklist">{activeRun.result.checklist.map((item, index) => <li key={`${item.title}-${index}`}><strong>{item.title}</strong><span>{item.reason}</span><small>需要你确认</small></li>)}</ul></section>}
            {activeRun.result.sections.map((section, index) => <section className="skill-draft-section" key={`${section.title}-${index}`}>
              <div className="skill-section-heading"><h4>{section.title}</h4>{section.needs_user_input && <span>需要补充 / 核对</span>}</div>
              <p>{section.content}</p>
              {section.citations.length > 0 && <div className="skill-citations"><strong>原文依据</strong>{section.citations.map((citation, citationIndex) => <blockquote key={`${citation.source_id}-${citationIndex}`}>
                <span>{citation.source_label}{citation.source_url && <> · <a href={citation.source_url} rel="noreferrer" target="_blank">打开来源</a></>}</span><q>{citation.quote}</q>
              </blockquote>)}</div>}
            </section>)}
            {activeRun.result.open_questions.length > 0 && <section><h4>需要你补充的问题</h4><ul className="skill-open-questions">{activeRun.result.open_questions.map((question, index) => <li key={`${question}-${index}`}>{question}</li>)}</ul></section>}
            {activeRun.skill_id === "application_answers" && <Link className="text-link external-action-draft-link" href={`/actions?skill_run_id=${activeRun.id}`}>把申请问答草稿载入外部邮件审批</Link>}
            {activeRun.skill_id === "application_prep_pack" && <div className="skill-approval-area">
              {canRequestApproval && <button className="button button-secondary" disabled={working} onClick={() => void requestApproval(activeRun)} type="button">{latestRunApproval ? "重新申请保存审批" : "申请保存到工作台"}</button>}
              {activeApproval?.status === "pending" && <div className="skill-approval-card"><strong>待确认操作</strong><p>{activeApproval.summary}</p><small>审批有效期至 {new Date(activeApproval.expires_at).toLocaleString("zh-CN")}</small><div><button className="button button-primary" disabled={working} onClick={() => void approveAndSave(activeApproval)} type="button">核对后批准并保存</button><button className="button button-secondary" disabled={working} onClick={() => void rejectApproval(activeApproval)} type="button">拒绝</button></div></div>}
              {activeApproval?.status === "approved" && <div className="skill-approval-card"><strong>已批准，尚未写入</strong><p>{activeApproval.summary}</p><button className="button button-primary" disabled={working} onClick={() => void approveAndSave(activeApproval)} type="button">确认执行本地保存</button></div>}
              {latestRunApproval && !activeApproval && latestRunApproval.status !== "executed" && <p className="skill-approval-status">{latestRunApproval.status === "expired" ? "审批已过期，可重新申请。" : latestRunApproval.status === "rejected" ? "审批已拒绝；如仍需保存，请重新运行申请准备包。" : latestRunApproval.status === "invalidated" ? "草稿或目标变化导致审批失效；请重新运行 Skill 生成新草稿。" : APPROVAL_LABELS[latestRunApproval.status]}</p>}
              {latestRunApproval?.status === "executed" && <p className="skill-approval-status">{APPROVAL_LABELS.executed}</p>}
            </div>}
          </div>}
        </article>}
      </section>

      <section className="profile-panel skills-panel">
        <div className="profile-panel-heading"><div><p className="eyebrow">已确认写入</p><h2>已保存的申请准备包</h2></div></div>
        {packs.length === 0 ? <p className="empty-state">用户批准并执行保存后，准备包会出现在这里。</p> : <div className="skill-saved-packs">{packs.map((pack) => <details key={pack.id}>
          <summary><strong>{jobLabel(jobsById.get(pack.job_id))}</strong><span>v{pack.skill_version} · {new Date(pack.created_at).toLocaleString("zh-CN")}</span></summary>
          <p>{pack.content.summary}</p>
          {pack.content.sections.map((section, index) => <div className="skill-saved-section" key={`${section.title}-${index}`}><h4>{section.title}</h4><p>{section.content}</p></div>)}
        </details>)}</div>}
      </section>

      <section className="profile-panel skills-panel">
        <div className="profile-panel-heading"><div><p className="eyebrow">操作审计</p><h2>审批与保存记录</h2></div></div>
        {auditEvents.length === 0 ? <p className="empty-state">确认、拒绝和保存操作会记录在这里。</p> : <ul className="skill-audit-list">{auditEvents.map((event) => <li key={event.id}><span><strong>{event.action}</strong><small>{event.entity_type} · {event.entity_id}</small></span><time>{new Date(event.created_at).toLocaleString("zh-CN")}</time></li>)}</ul>}
      </section>
    </main>
  );
}
