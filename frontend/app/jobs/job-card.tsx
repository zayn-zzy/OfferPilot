"use client";

import { type FormEvent, useEffect, useState } from "react";
import {
  APPLICATION_STAGES,
  APPLICATION_STAGE_LABELS,
  ApiError,
  type ApplicationStatusEvent,
  type CompanyResearch,
  type JobMatch,
  type JobPosting,
  type JobSourceEvidence,
  type JobPostingWrite,
  type ResumeVersionSummary,
  apiRequest,
} from "@/lib/api";
import JobEditor from "./job-editor";

type JobCardProps = {
  job: JobPosting;
  onSave: (job: JobPosting, payload: JobPostingWrite) => Promise<void>;
  onDelete: (job: JobPosting) => Promise<void>;
  onUpdateApplication: (job: JobPosting, update: Record<string, unknown>) => Promise<void>;
  onHistory: (job: JobPosting) => Promise<ApplicationStatusEvent[]>;
  resumes: ResumeVersionSummary[];
};

function ApplicationEditor({ job, onUpdateApplication, onHistory, resumes, onSaved }: JobCardProps & { onSaved: () => void }) {
  const [appliedAt, setAppliedAt] = useState(job.application?.applied_at ?? "");
  const [notes, setNotes] = useState(job.application?.notes ?? "");
  const [nextAction, setNextAction] = useState(job.application?.next_action ?? "");
  const [nextActionDue, setNextActionDue] = useState(job.application?.next_action_due ?? "");
  const [resumeVersionId, setResumeVersionId] = useState(job.application?.resume_version_id ?? "");
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState<ApplicationStatusEvent[] | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setHistory(null);
  }, [job.application?.status]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onUpdateApplication(job, {
        applied_at: appliedAt || null,
        notes: notes.trim() || null,
        next_action: nextAction.trim() || null,
        next_action_due: nextActionDue || null,
        resume_version_id: resumeVersionId || null,
      });
      onSaved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "投递记录保存失败。");
    } finally {
      setSaving(false);
    }
  }

  async function toggleHistory() {
    if (history !== null) {
      setHistory(null);
      return;
    }
    setHistoryLoading(true);
    setError("");
    try {
      setHistory(await onHistory(job));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取阶段记录。");
    } finally {
      setHistoryLoading(false);
    }
  }

  return (
    <div className="application-editor">
      <form aria-label="投递记录" onSubmit={submit}>
        <fieldset className="application-fields" disabled={saving}>
          <label>投递日期<input type="date" value={appliedAt} onChange={(event) => setAppliedAt(event.target.value)} /></label>
          <label>关联简历版本<select value={resumeVersionId} onChange={(event) => setResumeVersionId(event.target.value)}>
            <option value="">暂不关联</option>
            {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.filename}</option>)}
          </select></label>
          <label>下一步日期<input type="date" value={nextActionDue} onChange={(event) => setNextActionDue(event.target.value)} /></label>
          <label className="application-notes-field">下一步行动<input value={nextAction} maxLength={500} onChange={(event) => setNextAction(event.target.value)} placeholder="例如：完成在线测评" /></label>
          <label className="application-notes-field">联系人/进展备注<textarea rows={3} maxLength={5000} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
        </fieldset>
        <div className="application-actions">
          <button className="button button-primary" disabled={saving} type="submit">{saving ? "保存中…" : "保存投递记录"}</button>
          {job.application && <button className="button button-secondary" disabled={historyLoading} onClick={() => void toggleHistory()} type="button">{historyLoading ? "读取中…" : history !== null ? "隐藏阶段记录" : "查看阶段记录"}</button>}
        </div>
      </form>
      {error && <p className="form-error" role="alert">{error}</p>}
      {history !== null && <ol className="application-history">
        {history.map((event) => <li key={event.id}>
          <strong>{event.from_status ? APPLICATION_STAGE_LABELS[event.from_status] : "开始记录"} → {APPLICATION_STAGE_LABELS[event.to_status]}</strong>
          <time>{new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.created_at))}</time>
        </li>)}
        {history.length === 0 && <li>暂无阶段记录</li>}
      </ol>}
    </div>
  );
}

export default function JobCard(props: JobCardProps) {
  const { job, onSave, onDelete, onUpdateApplication } = props;
  const [panel, setPanel] = useState<"edit" | "application" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [sourceEvidence, setSourceEvidence] = useState<JobSourceEvidence | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const [matchAnalysis, setMatchAnalysis] = useState<JobMatch | null>(null);
  const [matchLoading, setMatchLoading] = useState(false);
  const [research, setResearch] = useState<CompanyResearch | null>(null);
  const [researchOpen, setResearchOpen] = useState(false);
  const [researchLoading, setResearchLoading] = useState(false);
  const [researchError, setResearchError] = useState("");
  const hasDetails = Boolean(
    job.description || job.company_notes || job.education_requirement || job.industry
    || job.recruitment_url || job.company_website_url
    || job.required_skills.length || job.tags.length,
  );

  function togglePanel(next: "edit" | "application") {
    setPanel((current) => current === next ? null : next);
    setError("");
    setNotice("");
  }

  async function changeStage(stage: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await onUpdateApplication(job, { status: stage });
      setNotice("投递阶段已保存。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "投递阶段保存失败。");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`确定删除“${job.company_name || "未填写公司"} - ${job.title || "未填写职位"}”？投递记录也会删除。`)) return;
    setBusy(true);
    setError("");
    try {
      await onDelete(job);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除失败。");
    } finally {
      setBusy(false);
    }
  }

  async function toggleEvidence() {
    if (evidenceOpen) {
      setEvidenceOpen(false);
      return;
    }
    setEvidenceLoading(true);
    setEvidenceError("");
    try {
      setSourceEvidence(await apiRequest<JobSourceEvidence>(`/api/v1/agent/jobs/${job.id}/evidence`));
      setEvidenceOpen(true);
    } catch (cause) {
      setEvidenceError(cause instanceof Error ? cause.message : "无法读取来源依据。");
    } finally {
      setEvidenceLoading(false);
    }
  }

  async function analyzeMatch() {
    setMatchLoading(true);
    setError("");
    try {
      setMatchAnalysis(await apiRequest<JobMatch>(`/api/v1/jobs/${job.id}/match`, { method: "POST" }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "岗位匹配分析失败。");
    } finally {
      setMatchLoading(false);
    }
  }

  async function toggleCompanyResearch() {
    if (researchOpen) {
      setResearchOpen(false);
      return;
    }
    setResearchOpen(true);
    setResearchLoading(true);
    setResearchError("");
    try {
      setResearch(await apiRequest<CompanyResearch>(`/api/v1/jobs/${job.id}/research`));
    } catch (cause) {
      if (!(cause instanceof ApiError && cause.status === 404)) {
        setResearchError(cause instanceof Error ? cause.message : "无法读取公司研究结果。");
      }
    } finally {
      setResearchLoading(false);
    }
  }

  async function runCompanyResearch() {
    setResearchLoading(true);
    setResearchError("");
    try {
      setResearch(await apiRequest<CompanyResearch>(`/api/v1/jobs/${job.id}/research?refresh=true`, {
        method: "POST",
      }));
    } catch (cause) {
      setResearchError(cause instanceof Error ? cause.message : "公司研究失败。");
    } finally {
      setResearchLoading(false);
    }
  }

  return (
    <article aria-label={`${job.company_name || "未填写公司"} ${job.title || "未填写职位"}`} className="job-card" id={`job-${job.id}`} tabIndex={-1}>
      <div className="job-card-heading">
        <div>
          <p className="job-company">{job.company_name || "未填写公司"}</p>
          <h3>{job.title || "未填写职位"}</h3>
          <p className="job-meta">{[job.city, job.job_type, job.batch].filter(Boolean).join(" · ")}</p>
        </div>
        <label className="stage-control">
          投递阶段
          <select aria-label="投递阶段" disabled={busy} value={job.application?.status ?? "untracked"} onChange={(event) => void changeStage(event.target.value)}>
            <option disabled value="untracked">未记录</option>
            {APPLICATION_STAGES.map((stage) => <option key={stage} value={stage}>{APPLICATION_STAGE_LABELS[stage]}</option>)}
          </select>
        </label>
      </div>
      <div className="job-facts">
        <span>截止：{job.deadline || "未填写"}</span>
        {job.source_url && <a href={job.source_url} rel="noreferrer" target="_blank">岗位来源 ↗</a>}
      </div>
      {hasDetails && <details className="job-description-details">
        <summary>岗位详情</summary>
        {[job.education_requirement, job.industry].filter(Boolean).length > 0 && <p className="job-meta">{[job.education_requirement, job.industry].filter(Boolean).join(" · ")}</p>}
        {job.required_skills.length > 0 && <p className="job-meta">技能：{job.required_skills.join("、")}</p>}
        {job.tags.length > 0 && <p className="job-meta">标签：{job.tags.join("、")}</p>}
        {job.description && <p className="job-description">{job.description}</p>}
        {job.company_notes && <p className="job-company-note">公司备注：{job.company_notes}</p>}
        <div className="job-links">
          {job.recruitment_url && <a href={job.recruitment_url} rel="noreferrer" target="_blank">招聘主页 ↗</a>}
          {job.company_website_url && <a href={job.company_website_url} rel="noreferrer" target="_blank">公司官网 ↗</a>}
        </div>
      </details>}
      <div className="job-card-actions">
        <button aria-expanded={panel === "edit"} aria-controls={`job-edit-${job.id}`} className="button button-secondary" disabled={busy} onClick={() => togglePanel("edit")} type="button">{panel === "edit" ? "取消编辑" : "编辑"}</button>
        <button aria-expanded={panel === "application"} aria-controls={`job-progress-${job.id}`} className="job-quiet-action" disabled={busy} onClick={() => togglePanel("application")} type="button">{panel === "application" ? "收起投递记录" : "投递记录"}</button>
        {job.source_type === "agent" && <button aria-expanded={evidenceOpen} className="job-quiet-action" disabled={evidenceLoading} onClick={() => void toggleEvidence()} type="button">{evidenceLoading ? "读取依据中…" : evidenceOpen ? "收起抽取依据" : "抽取依据"}</button>}
        <button aria-expanded={Boolean(matchAnalysis)} className="job-quiet-action" disabled={matchLoading} onClick={() => void analyzeMatch()} type="button">{matchLoading ? "分析中…" : matchAnalysis ? "重新分析匹配" : "匹配分析"}</button>
        <button aria-expanded={researchOpen} aria-controls={`job-research-${job.id}`} className="job-quiet-action" disabled={researchLoading || !job.company_name} onClick={() => void toggleCompanyResearch()} type="button">{researchLoading ? "读取中…" : researchOpen ? "收起公司研究" : "公司研究"}</button>
        <button className="job-quiet-action danger-text" disabled={busy} onClick={() => void remove()} type="button">删除</button>
      </div>
      {researchOpen && <section className="company-research-panel" id={`job-research-${job.id}`} aria-label="公司公开信息研究">
        <div className="job-match-heading"><h4>公司公开信息研究</h4><span>只读搜索 · Tavily</span></div>
        {researchLoading && <p className="job-match-disclaimer" role="status">正在搜索公开招聘信息并核验摘要…</p>}
        {researchError && <p className="form-error" role="alert">{researchError}</p>}
        {!researchLoading && !research && <div className="company-research-empty">
          <p>搜索公开招聘页面和公司信息。结果会保留来源链接；搜索摘要不能替代官网核验。</p>
          <button className="button button-primary" disabled={!job.company_name} onClick={() => void runCompanyResearch()} type="button">开始公司研究</button>
        </div>}
        {research && <>
          <p className="company-research-summary">{research.summary}</p>
          <p className="job-match-disclaimer">搜索时间：{new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(research.researched_at))} · 搜索词：{research.query}</p>
          {research.is_stale && <p className="company-research-stale" role="status">该结果已超过 7 天，招聘信息可能变化，请重新搜索或打开来源核验。</p>}
          {research.warning && <p className="form-error" role="status">{research.warning}</p>}
          {research.findings.length > 0 && <ol className="company-research-findings">{research.findings.map((finding, index) => {
            const source = research.sources.find((item) => item.source_id === finding.source_id);
            return <li key={`${finding.source_id}-${index}`}>
              <strong>{finding.claim}</strong>
              <blockquote>{finding.quote}</blockquote>
              {source && <a href={source.url} rel="noreferrer" target="_blank">来源：{source.title} ↗</a>}
            </li>;
          })}</ol>}
          <details className="company-research-sources"><summary>查看全部搜索来源（{research.sources.length}）</summary>
            {research.sources.length === 0 ? <p>搜索服务没有返回来源。</p> : <ul>{research.sources.map((source) => <li key={source.source_id}>
              <a href={source.url} rel="noreferrer" target="_blank">{source.title} ↗</a>
              {source.age && <small>{source.age}</small>}
              <p>{source.excerpt}</p>
            </li>)}</ul>}
          </details>
          <button className="job-quiet-action" disabled={researchLoading} onClick={() => void runCompanyResearch()} type="button">重新搜索</button>
        </>}
      </section>}
      {matchAnalysis && <section className="job-match-analysis" aria-label="岗位匹配分析">
        <div className="job-match-heading"><h4>匹配分析</h4><span>依据：{matchAnalysis.resume_filename}</span></div>
        <ul className="job-match-criteria">{matchAnalysis.criteria.map((criterion) => <li key={criterion.key}>
          <span className={`job-match-status job-match-${criterion.status}`}>{criterion.status === "meets" ? "符合" : criterion.status === "does_not_meet" ? "不符合" : "待确认"}</span>
          <div><strong>{criterion.label}{criterion.category === "hard_requirement" ? " · 硬性要求" : " · 偏好"}</strong><p>{criterion.explanation}</p>
            {(criterion.requirement || criterion.candidate_value) && <small>岗位：{criterion.requirement || "未填写"} · 你的档案：{criterion.candidate_value || "未填写"}</small>}
          </div>
        </li>)}</ul>
        {matchAnalysis.skills.length > 0 && <div className="job-match-skills"><h5>岗位技能要求</h5><ul>{matchAnalysis.skills.map((skill) => <li key={skill.skill}>
          <strong>{skill.status === "evidenced" ? "简历/档案有记录" : "资料中未找到"}</strong> {skill.skill}
          {skill.evidence && <blockquote>{skill.evidence}</blockquote>}
        </li>)}</ul></div>}
        <p className="job-match-disclaimer">{matchAnalysis.disclaimer}</p>
      </section>}
      {evidenceError && <p className="form-error" role="alert">{evidenceError}</p>}
      {evidenceOpen && sourceEvidence && <section className="job-source-evidence" aria-label="岗位字段抽取依据">
        <h4>字段来源依据</h4>
        <ul>{Object.entries(sourceEvidence.field_evidence).map(([field, item]) => <li key={field}>
          <strong>{({ company_name: "公司", title: "职位", city: "地点", job_type: "岗位类型", batch: "招聘批次", deadline: "截止日期", education_requirement: "学历要求", required_skills: "技能" } as Record<string, string>)[field] ?? field}</strong>
          <span>{Array.isArray(item.value) ? item.value.join("、") : item.value || "未提取"} · 置信度 {Math.round(item.confidence * 100)}%</span>
          {item.evidence && <blockquote>{item.evidence}</blockquote>}
        </li>)}</ul>
        <details><summary>查看保存的招聘原文</summary><pre>{sourceEvidence.source_text}</pre></details>
      </section>}
      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p className="job-card-notice" role="status">{notice}</p>}
      {busy && <p className="job-card-notice" role="status">正在保存…</p>}
      {panel === "edit" && <div className="job-inline-editor" id={`job-edit-${job.id}`}>
        <JobEditor job={job} onCancel={() => setPanel(null)} onSave={async (payload) => {
          setBusy(true);
          try {
            await onSave(job, payload);
            setPanel(null);
            setNotice("岗位信息已保存。");
          } finally {
            setBusy(false);
          }
        }} />
      </div>}
      {panel === "application" && <div id={`job-progress-${job.id}`}>
        <ApplicationEditor {...props} onUpdateApplication={async (selected, update) => {
          setBusy(true);
          try {
            await onUpdateApplication(selected, update);
          } finally {
            setBusy(false);
          }
        }} onSaved={() => {
          setPanel(null);
          setNotice("投递记录已保存。");
        }} />
      </div>}
    </article>
  );
}
