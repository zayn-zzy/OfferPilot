"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  APPLICATION_STAGES,
  APPLICATION_STAGE_LABELS,
  ApiError,
  apiRequest,
  type ApplicationStatusEvent,
  type ApplicationStage,
  type JobPosting,
  type ResumeVersionSummary,
} from "@/lib/api";

type JobForm = {
  company_name: string;
  company_website_url: string;
  recruitment_url: string;
  industry: string;
  company_notes: string;
  title: string;
  city: string;
  job_type: string;
  batch: string;
  deadline: string;
  education_requirement: string;
  required_skills: string;
  description: string;
  source_url: string;
  source_type: "manual" | "paste" | "link";
  tags: string;
};

type Filters = { search: string; city: string; status: string; deadline_before: string; tag: string };
type View = "jobs" | "board";

const EMPTY_FORM: JobForm = {
  company_name: "",
  company_website_url: "",
  recruitment_url: "",
  industry: "",
  company_notes: "",
  title: "",
  city: "",
  job_type: "",
  batch: "",
  deadline: "",
  education_requirement: "",
  required_skills: "",
  description: "",
  source_url: "",
  source_type: "manual",
  tags: "",
};

function splitList(value: string): string[] {
  return value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
}

function formFromJob(job: JobPosting): JobForm {
  return {
    company_name: job.company_name ?? "",
    company_website_url: job.company_website_url ?? "",
    recruitment_url: job.recruitment_url ?? "",
    industry: job.industry ?? "",
    company_notes: job.company_notes ?? "",
    title: job.title ?? "",
    city: job.city ?? "",
    job_type: job.job_type ?? "",
    batch: job.batch ?? "",
    deadline: job.deadline ?? "",
    education_requirement: job.education_requirement ?? "",
    required_skills: job.required_skills.join("，"),
    description: job.description ?? "",
    source_url: job.source_url ?? "",
    source_type: job.source_type,
    tags: job.tags.join("，"),
  };
}

function payloadFromForm(form: JobForm) {
  return {
    company_name: form.company_name.trim() || null,
    company_website_url: form.company_website_url.trim() || null,
    recruitment_url: form.recruitment_url.trim() || null,
    industry: form.industry.trim() || null,
    company_notes: form.company_notes.trim() || null,
    title: form.title.trim() || null,
    city: form.city.trim() || null,
    job_type: form.job_type.trim() || null,
    batch: form.batch.trim() || null,
    deadline: form.deadline || null,
    education_requirement: form.education_requirement.trim() || null,
    required_skills: splitList(form.required_skills),
    description: form.description.trim() || null,
    source_url: form.source_url.trim() || null,
    source_type: form.source_type,
    tags: splitList(form.tags),
  };
}

function apiMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : "操作失败，请稍后重试。";
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(new Date(value));
}

type JobCardProps = {
  job: JobPosting;
  onEdit: (job: JobPosting) => void;
  onDelete: (job: JobPosting) => void;
  onTrack: (job: JobPosting) => void;
  onUpdateApplication: (job: JobPosting, update: Record<string, unknown>) => Promise<void>;
  onVerify: (job: JobPosting) => void;
  onHistory: (job: JobPosting) => Promise<ApplicationStatusEvent[]>;
  resumes: ResumeVersionSummary[];
};

function JobCard({ job, onEdit, onDelete, onTrack, onUpdateApplication, onVerify, onHistory, resumes }: JobCardProps) {
  const [showDetails, setShowDetails] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<ApplicationStatusEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [appliedAt, setAppliedAt] = useState(job.application?.applied_at ?? "");
  const [notes, setNotes] = useState(job.application?.notes ?? "");
  const [nextAction, setNextAction] = useState(job.application?.next_action ?? "");
  const [nextActionDue, setNextActionDue] = useState(job.application?.next_action_due ?? "");
  const [resumeVersionId, setResumeVersionId] = useState(job.application?.resume_version_id ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setAppliedAt(job.application?.applied_at ?? "");
    setNotes(job.application?.notes ?? "");
    setNextAction(job.application?.next_action ?? "");
    setNextActionDue(job.application?.next_action_due ?? "");
    setResumeVersionId(job.application?.resume_version_id ?? "");
  }, [job.application]);

  async function toggleHistory() {
    if (showHistory) {
      setShowHistory(false);
      return;
    }
    setHistoryLoading(true);
    try {
      setHistory(await onHistory(job));
      setShowHistory(true);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function saveDetails() {
    setSaving(true);
    try {
      await onUpdateApplication(job, {
        applied_at: appliedAt || null,
        notes: notes.trim() || null,
        next_action: nextAction.trim() || null,
        next_action_due: nextActionDue || null,
        resume_version_id: resumeVersionId || null,
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="job-card">
      <div className="job-card-heading">
        <div className="job-card-title-block">
          <p className="job-company">{job.company_name || "公司待核验"}</p>
          <h3>{job.title || "职位待核验"}</h3>
          <p className="job-meta">
            {[job.city, job.job_type, job.batch, job.education_requirement].filter(Boolean).join(" · ") || "尚未填写职位条件"}
          </p>
        </div>
        <span className={`review-badge ${job.review_status === "verified" ? "review-verified" : "review-pending"}`}>
          {job.review_status === "verified" ? "已核验" : "待核验"}
        </span>
      </div>

      <div className="job-facts">
        <span>截止：{job.deadline || "未填写"}</span>
        <span>来源采集：{formatDate(job.source_captured_at)}</span>
        {job.industry && <span>行业：{job.industry}</span>}
      </div>

      {job.required_skills.length > 0 && (
        <div className="job-chip-row" aria-label="技能要求">
          {job.required_skills.map((skill) => <span className="job-chip" key={skill}>{skill}</span>)}
        </div>
      )}
      {job.tags.length > 0 && (
        <div className="job-chip-row job-tag-row" aria-label="自定义标签">
          {job.tags.map((tag) => <span className="job-tag" key={tag}>{tag}</span>)}
        </div>
      )}

      {job.description && <p className="job-description">{job.description}</p>}
      {job.company_notes && <p className="job-company-note">公司备注：{job.company_notes}</p>}

      <div className="job-links">
        {job.source_url && <a href={job.source_url} target="_blank" rel="noreferrer">打开岗位来源 ↗</a>}
        {job.recruitment_url && <a href={job.recruitment_url} target="_blank" rel="noreferrer">招聘主页 ↗</a>}
        {job.company_website_url && <a href={job.company_website_url} target="_blank" rel="noreferrer">公司官网 ↗</a>}
      </div>

      <div className="job-card-actions">
        {job.application ? (
          <label className="stage-control">
            投递阶段
            <select
              aria-label={`${job.company_name ?? "岗位"}投递阶段`}
              value={job.application.status}
              onChange={(event) => void onUpdateApplication(job, { status: event.target.value as ApplicationStage })}
            >
              {APPLICATION_STAGES.map((stage) => <option key={stage} value={stage}>{APPLICATION_STAGE_LABELS[stage]}</option>)}
            </select>
          </label>
        ) : (
          <button className="button button-primary" onClick={() => onTrack(job)} type="button">加入投递看板</button>
        )}
        <button className="button button-secondary" onClick={() => onEdit(job)} type="button">编辑</button>
        {job.review_status === "needs_review" && (
          <button className="button button-secondary" onClick={() => onVerify(job)} type="button">标记已核验</button>
        )}
        <button className="job-quiet-action" onClick={() => setShowDetails((value) => !value)} type="button">
          {showDetails ? "收起投递记录" : "投递备注与下一步"}
        </button>
        <button className="job-quiet-action danger-text" onClick={() => onDelete(job)} type="button">删除</button>
      </div>

      {showDetails && job.application && (
        <div className="application-editor">
          <div className="application-fields">
            <label>投递日期<input type="date" value={appliedAt} onChange={(event) => setAppliedAt(event.target.value)} /></label>
            <label>关联简历版本<select value={resumeVersionId} onChange={(event) => setResumeVersionId(event.target.value)}>
              <option value="">暂不关联</option>
              {resumes.map((resume) => (
                <option key={resume.id} value={resume.id}>
                  {resume.filename} · {resume.confirmed_at ? "已确认" : "待确认"}
                </option>
              ))}
            </select></label>
            <label>下一步及截止日期<input value={nextAction} onChange={(event) => setNextAction(event.target.value)} placeholder="例如：完成在线测评" /></label>
            <label>下一步日期<input type="date" value={nextActionDue} onChange={(event) => setNextActionDue(event.target.value)} /></label>
            <label className="application-notes-field">联系人/进展备注<textarea rows={3} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
          </div>
          <div className="application-actions">
            <button className="button button-primary" disabled={saving} onClick={() => void saveDetails()} type="button">
              {saving ? "保存中…" : "保存投递记录"}
            </button>
            <button className="button button-secondary" disabled={historyLoading} onClick={() => void toggleHistory()} type="button">
              {historyLoading ? "读取中…" : showHistory ? "隐藏阶段记录" : "查看阶段记录"}
            </button>
          </div>
          {showHistory && (
            <ol className="application-history">
              {history.map((event) => (
                <li key={event.id}>
                  <strong>{event.from_status ? APPLICATION_STAGE_LABELS[event.from_status] : "已加入看板"} → {APPLICATION_STAGE_LABELS[event.to_status]}</strong>
                  <time>{new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.created_at))}</time>
                </li>
              ))}
              {history.length === 0 && <li className="empty-state">暂无阶段记录</li>}
            </ol>
          )}
        </div>
      )}
      {showDetails && !job.application && <p className="empty-state">加入投递看板后，可以记录申请阶段、日期和下一步。</p>}
    </article>
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [resumes, setResumes] = useState<ResumeVersionSummary[]>([]);
  const [view, setView] = useState<View>("jobs");
  const [filters, setFilters] = useState<Filters>({ search: "", city: "", status: "", deadline_before: "", tag: "" });
  const [draftFilters, setDraftFilters] = useState(filters);
  const [form, setForm] = useState<JobForm>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);

  async function loadJobs(nextView: View = view, nextFilters: Filters = filters) {
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    if (nextFilters.search.trim()) params.set("search", nextFilters.search.trim());
    if (nextFilters.city.trim()) params.set("city", nextFilters.city.trim());
    if (nextFilters.status) params.set("status", nextFilters.status);
    if (nextFilters.deadline_before) params.set("deadline_before", nextFilters.deadline_before);
    if (nextFilters.tag.trim()) params.set("tag", nextFilters.tag.trim());
    if (nextView === "board") params.set("tracked", "true");
    try {
      const query = params.toString();
      const result = await apiRequest<JobPosting[]>(`/api/v1/jobs${query ? `?${query}` : ""}`);
      setJobs(result);
      setRequiresLogin(false);
    } catch (cause) {
      setError(apiMessage(cause));
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadJobs();
  }, [view]);

  useEffect(() => {
    apiRequest<ResumeVersionSummary[]>("/api/v1/resumes")
      .then(setResumes)
      .catch(() => setResumes([]));
  }, []);

  function resetForm() {
    setForm({ ...EMPTY_FORM });
    setEditingId(null);
  }

  async function submitJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const method = editingId ? "PUT" : "POST";
      const path = editingId ? `/api/v1/jobs/${editingId}` : "/api/v1/jobs";
      await apiRequest<JobPosting>(path, { method, body: JSON.stringify(payloadFromForm(form)) });
      setSuccess(editingId ? "岗位信息已更新。" : "岗位已保存。缺少公司或职位名称的记录会保留在待核验列表。" );
      resetForm();
      await loadJobs();
    } catch (cause) {
      setError(apiMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  async function mutateJob(job: JobPosting, path: string, method: string, body?: unknown): Promise<boolean> {
    setError("");
    setSuccess("");
    try {
      await apiRequest<JobPosting | void>(path, {
        method,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      await loadJobs();
      return true;
    } catch (cause) {
      setError(apiMessage(cause));
      return false;
    }
  }

  function editJob(job: JobPosting) {
    setForm(formFromJob(job));
    setEditingId(job.id);
    setError("");
    setSuccess("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function deleteJob(job: JobPosting) {
    if (!window.confirm(`确定删除“${job.company_name ?? "未知公司"} - ${job.title ?? "未知职位"}”？关联的投递阶段记录也会删除。`)) return;
    const deleted = await mutateJob(job, `/api/v1/jobs/${job.id}`, "DELETE");
    if (deleted && editingId === job.id) resetForm();
  }

  async function addToBoard(job: JobPosting) {
    await mutateJob(job, `/api/v1/jobs/${job.id}/application`, "POST");
  }

  async function updateApplication(job: JobPosting, update: Record<string, unknown>) {
    await mutateJob(job, `/api/v1/jobs/${job.id}/application`, "PUT", update);
  }

  async function verifyJob(job: JobPosting) {
    await mutateJob(job, `/api/v1/jobs/${job.id}/verify`, "POST");
  }

  async function readHistory(job: JobPosting): Promise<ApplicationStatusEvent[]> {
    try {
      return await apiRequest<ApplicationStatusEvent[]>(`/api/v1/jobs/${job.id}/application/history`);
    } catch (cause) {
      setError(apiMessage(cause));
      return [];
    }
  }

  async function logout() {
    try {
      await apiRequest("/api/v1/auth/logout", { method: "POST" });
      window.location.assign("/login");
    } catch (cause) {
      setError(apiMessage(cause));
    }
  }

  function changeView(nextView: View) {
    setView(nextView);
    const nextFilters = nextView === "board" && filters.status === "untracked"
      ? { ...filters, status: "" }
      : filters;
    setFilters(nextFilters);
    setDraftFilters(nextFilters);
    void loadJobs(nextView, nextFilters);
  }

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFilters(draftFilters);
    void loadJobs(view, draftFilters);
  }

  return (
    <main className="jobs-shell">
      <header className="dashboard-topbar jobs-topbar">
        <Link className="brand" href="/">
          <span className="brand-mark">O</span> OfferPilot
        </Link>
        <nav className="dashboard-actions" aria-label="主导航">
          <Link className="text-link" href="/dashboard">工作台</Link>
          <Link className="text-link" href="/profile">个人档案</Link>
          <button className="text-button" onClick={() => void logout()} type="button">退出登录</button>
        </nav>
      </header>

      <section className="jobs-heading">
        <p className="eyebrow">岗位与投递</p>
        <h1>把机会和下一步放在一起</h1>
        <p>手动记录岗位及其来源，确认关键信息后加入投递看板。岗位状态由你维护，系统不会代替你投递。</p>
      </section>

      {error && <div className="profile-message profile-error" role="alert">{error}{requiresLogin && <> <Link href="/login">去登录</Link></>}</div>}
      {success && <div className="profile-message profile-success" role="status">{success}</div>}

      <section className="profile-panel job-form-panel">
        <div className="profile-panel-heading">
          <div>
            <p className="eyebrow">岗位资料</p>
            <h2>{editingId ? "编辑岗位" : "新增岗位"}</h2>
          </div>
          {editingId && <button className="button button-secondary" onClick={resetForm} type="button">取消编辑</button>}
        </div>
        <form className="profile-form job-form" onSubmit={submitJob}>
          <label>公司名称<input maxLength={200} value={form.company_name} onChange={(event) => setForm({ ...form, company_name: event.target.value })} placeholder="例如：某某科技" /></label>
          <label>职位名称<input maxLength={200} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="例如：后端开发工程师" /></label>
          <label>工作城市<input maxLength={120} value={form.city} onChange={(event) => setForm({ ...form, city: event.target.value })} placeholder="例如：上海" /></label>
          <label>岗位类型<input maxLength={80} value={form.job_type} onChange={(event) => setForm({ ...form, job_type: event.target.value })} placeholder="校招 / 实习" /></label>
          <label>招聘批次<input maxLength={120} value={form.batch} onChange={(event) => setForm({ ...form, batch: event.target.value })} placeholder="例如：2027 届秋招" /></label>
          <label>截止日期<input type="date" value={form.deadline} onChange={(event) => setForm({ ...form, deadline: event.target.value })} /></label>
          <label>学历要求<input maxLength={120} value={form.education_requirement} onChange={(event) => setForm({ ...form, education_requirement: event.target.value })} placeholder="例如：本科及以上" /></label>
          <label>行业<input maxLength={120} value={form.industry} onChange={(event) => setForm({ ...form, industry: event.target.value })} placeholder="例如：互联网" /></label>
          <label>技能要求<span>用逗号分隔</span><input value={form.required_skills} onChange={(event) => setForm({ ...form, required_skills: event.target.value })} placeholder="Python，SQL，Linux" /></label>
          <label>自定义标签<span>用逗号分隔</span><input value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} placeholder="优先申请，上海" /></label>
          <label>公司官网<input type="url" value={form.company_website_url} onChange={(event) => setForm({ ...form, company_website_url: event.target.value })} placeholder="https://example.com" /></label>
          <label>招聘主页<input type="url" value={form.recruitment_url} onChange={(event) => setForm({ ...form, recruitment_url: event.target.value })} placeholder="https://example.com/careers" /></label>
          <label>岗位来源<input type="url" value={form.source_url} onChange={(event) => setForm({ ...form, source_url: event.target.value })} placeholder="招聘官网或岗位页面链接" /></label>
          <label>来源类型<select value={form.source_type} onChange={(event) => setForm({ ...form, source_type: event.target.value as JobForm["source_type"] })}>
            <option value="manual">手动录入</option><option value="paste">粘贴岗位文本</option><option value="link">来自网页链接</option>
          </select></label>
          <label className="profile-full-width">公司备注<textarea rows={2} maxLength={5000} value={form.company_notes} onChange={(event) => setForm({ ...form, company_notes: event.target.value })} /></label>
          <label className="profile-full-width">岗位描述 / 原始文本<span>可粘贴招聘信息；来源原文会随岗位保存</span><textarea rows={6} maxLength={30000} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
          <div className="profile-form-actions profile-full-width">
            <button className="button button-primary" disabled={saving} type="submit">{saving ? "保存中…" : editingId ? "保存修改" : "保存岗位"}</button>
            {!editingId && <p className="job-form-hint">公司和职位信息不完整时，也可以先保存为待核验记录。</p>}
          </div>
        </form>
      </section>

      <section className="job-list-section">
        <div className="job-list-heading">
          <div>
            <p className="eyebrow">我的求职数据</p>
            <h2>{view === "board" ? "投递看板" : "岗位列表"}</h2>
          </div>
          <div className="job-view-toggle" role="tablist" aria-label="岗位视图">
            <button aria-selected={view === "jobs"} className={view === "jobs" ? "active" : ""} onClick={() => changeView("jobs")} role="tab" type="button">全部岗位</button>
            <button aria-selected={view === "board"} className={view === "board" ? "active" : ""} onClick={() => changeView("board")} role="tab" type="button">投递看板</button>
          </div>
        </div>

        <form className="job-filter-form" onSubmit={applyFilters}>
          <label>公司 / 职位 / 行业<input value={draftFilters.search} onChange={(event) => setDraftFilters({ ...draftFilters, search: event.target.value })} placeholder="搜索公司、职位、城市或行业" /></label>
          <label>城市<input value={draftFilters.city} onChange={(event) => setDraftFilters({ ...draftFilters, city: event.target.value })} placeholder="筛选城市" /></label>
          <label>投递状态<select value={draftFilters.status} onChange={(event) => setDraftFilters({ ...draftFilters, status: event.target.value })}>
            <option value="">全部状态</option>
            {view === "jobs" && <option value="untracked">尚未加入看板</option>}
            {APPLICATION_STAGES.map((stage) => <option key={stage} value={stage}>{APPLICATION_STAGE_LABELS[stage]}</option>)}
          </select></label>
          <label>截止日期不晚于<input type="date" value={draftFilters.deadline_before} onChange={(event) => setDraftFilters({ ...draftFilters, deadline_before: event.target.value })} /></label>
          <label>标签<input value={draftFilters.tag} onChange={(event) => setDraftFilters({ ...draftFilters, tag: event.target.value })} placeholder="筛选标签" /></label>
          <button className="button button-primary" type="submit">筛选</button>
        </form>

        {loading ? <div className="profile-loading">正在载入岗位…</div> : jobs.length === 0 ? (
          <div className="job-empty-state"><strong>{requiresLogin ? "请先登录后管理岗位" : view === "board" ? "看板里还没有投递记录" : "还没有保存岗位"}</strong><span>{requiresLogin ? "登录后，岗位和申请记录会保存在你的账户中。" : "先填写上方岗位信息，也可以稍后再加入投递看板。"}</span></div>
        ) : (
          <div className="job-card-list">
            {jobs.map((job) => (
              <JobCard
                key={job.id}
                job={job}
                onEdit={editJob}
                onDelete={(selected) => void deleteJob(selected)}
                onTrack={(selected) => void addToBoard(selected)}
                onUpdateApplication={updateApplication}
                onVerify={(selected) => void verifyJob(selected)}
                onHistory={readHistory}
                resumes={resumes}
              />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
