"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, apiRequest, type CompanyArchive } from "@/lib/api";

const APPLICATION_LABELS: Record<string, string> = {
  to_research: "待了解",
  interested: "感兴趣",
  preparing: "准备中",
  applied: "已投递",
  assessment: "测评中",
  interview: "面试中",
  offer: "Offer",
  accepted: "已接受",
  rejected: "已拒绝",
  withdrawn: "已撤回",
  closed: "已关闭",
};

function formatDate(value: string | null) {
  if (!value) return "暂无记录";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(new Date(value));
}

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<CompanyArchive[]>([]);
  const [loading, setLoading] = useState(true);
  const [researchingJobId, setResearchingJobId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);

  const loadArchives = useCallback(async () => {
    try {
      setCompanies(await apiRequest<CompanyArchive[]>("/api/v1/companies"));
      setError("");
      setRequiresLogin(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法载入公司档案。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadArchives();
  }, [loadArchives]);

  async function researchJob(jobId: string) {
    setResearchingJobId(jobId);
    setError("");
    setNotice("");
    try {
      await apiRequest(`/api/v1/jobs/${jobId}/research?refresh=true`, { method: "POST" });
      await loadArchives();
      setNotice("研究结果已保存到对应公司档案。请留意来源日期并打开原文核验。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "公司研究失败，请稍后重试。");
      if (cause instanceof ApiError && cause.status === 401) setRequiresLogin(true);
    } finally {
      setResearchingJobId(null);
    }
  }

  return (
    <main className="companies-shell">
      <header className="dashboard-topbar companies-topbar">
        <Link className="brand" href="/dashboard"><span className="brand-mark">O</span> OfferPilot</Link>
        <nav className="dashboard-actions" aria-label="主导航">
          <Link className="text-link" href="/dashboard">工作台</Link>
          <Link className="text-link" href="/jobs">岗位管理</Link>
          <Link className="text-link" href="/reminders">提醒中心</Link>
          <Link className="text-link" href="/skills">Agent Skills</Link>
        </nav>
      </header>

      <section className="companies-heading">
        <p className="eyebrow">公司档案</p>
        <h1>把同一公司的岗位与研究放在一起</h1>
        <p>按公司归集你保存的岗位、招聘批次、公司备注和最新公开研究。研究结论保留引用；过期或缺少证据时会明确标出。</p>
      </section>

      {error && <div className="profile-message profile-error" role="alert">{error}{requiresLogin && <> <Link href="/login">去登录</Link></>}</div>}
      {notice && <div className="profile-message profile-success" role="status">{notice}</div>}

      <section className="company-archive-list" aria-label="公司档案列表">
        {loading ? <p className="profile-loading">正在载入公司档案…</p> : companies.length === 0 ? (
          <div className="profile-panel company-archive-empty">
            <h2>还没有公司档案</h2>
            <p>在岗位中填写公司名称后，系统会自动建立对应档案。</p>
            <Link className="button button-primary" href="/jobs">去管理岗位</Link>
          </div>
        ) : companies.map((company) => (
          <article className="profile-panel company-archive-card" key={company.id}>
            <header className="company-archive-heading">
              <div>
                <p className="eyebrow">{company.industry || "招聘公司"}</p>
                <h2>{company.name}</h2>
              </div>
              <span className="company-archive-count">{company.jobs.length} 个岗位</span>
            </header>

            <div className="company-archive-links">
              {company.website_url && <a href={company.website_url} rel="noreferrer" target="_blank">公司官网 ↗</a>}
              {company.recruitment_url && <a href={company.recruitment_url} rel="noreferrer" target="_blank">招聘主页 ↗</a>}
              <Link href="/jobs">管理岗位</Link>
            </div>

            {company.batches.length > 0 && <p className="company-archive-meta"><strong>招聘批次：</strong>{company.batches.join("、")}</p>}
            {company.notes && <div className="company-archive-notes"><strong>我保存的公司备注</strong><p>{company.notes}</p></div>}

            <section className="company-research-archive" aria-label={`${company.name}的研究归档`}>
              <div className="company-archive-section-heading">
                <h3>公开研究</h3>
                <span>{company.research_count} 份 · {company.finding_count} 条引用事实 · {company.source_count} 个来源</span>
              </div>
              <p className="company-research-summary">{company.research_summary}</p>
              {company.stale_research_count > 0 && <p className="company-research-stale" role="status">
                {company.stale_research_count} 份研究超过 7 天，招聘信息可能已变化，请重新研究或核对官网。
              </p>}
              {company.no_evidence && company.research_count > 0 && <p className="company-archive-no-evidence" role="status">
                当前研究没有可支持事实摘要的证据。来源仍可查看，请勿把无证据结果当作公司事实。
              </p>}

              {company.findings.length > 0 && <ul className="company-archive-findings">
                {company.findings.map((finding, index) => <li key={`${finding.job_id}-${finding.source_url}-${index}`}>
                  <p><strong>{finding.claim}</strong><small>{finding.job_title || "公司公开信息"} · {formatDate(finding.researched_at)}{finding.is_stale ? " · 可能过期" : ""}</small></p>
                  <blockquote>{finding.quote}</blockquote>
                  <a href={finding.source_url} rel="noreferrer" target="_blank">来源：{finding.source_title} ↗</a>
                </li>)}
              </ul>}

              {company.sources.length > 0 && <details className="company-archive-sources">
                <summary>查看保存的来源链接（{company.sources.length}）</summary>
                <ul>{company.sources.map((source) => <li key={`${source.research_run_id}-${source.source_id}`}>
                  <a href={source.url} rel="noreferrer" target="_blank">{source.title} ↗</a>
                  <small>{source.job_title || "公司公开信息"} · {formatDate(source.researched_at)}{source.is_stale ? " · 可能过期" : ""}</small>
                  <p>{source.excerpt}</p>
                </li>)}</ul>
              </details>}
            </section>

            <section className="company-archive-jobs" aria-label={`${company.name}的岗位`}>
              <div className="company-archive-section-heading"><h3>已保存岗位</h3></div>
              {company.jobs.length === 0 ? <p className="empty-state">当前没有关联岗位。</p> : company.jobs.map((job) => (
                <article className="company-archive-job" key={job.id}>
                  <div className="company-archive-job-info">
                    <h4>{job.title || "未填写职位"}</h4>
                    <p>{[job.city, job.job_type, job.batch].filter(Boolean).join(" · ") || "岗位信息待补充"}</p>
                    <small>截止：{job.deadline || "未填写"}{job.application_status ? ` · ${APPLICATION_LABELS[job.application_status] || job.application_status}` : ""}</small>
                    {job.research_summary && <p className="company-archive-job-research">{job.research_summary}{job.research_is_stale ? "（可能过期）" : ""}</p>}
                    {job.source_url && <a href={job.source_url} rel="noreferrer" target="_blank">招聘原始来源 ↗</a>}
                  </div>
                  <button className="button button-secondary" disabled={researchingJobId !== null} onClick={() => void researchJob(job.id)} type="button">
                    {researchingJobId === job.id ? "研究中…" : job.researched_at ? "重新研究" : "开始研究"}
                  </button>
                </article>
              ))}
            </section>
          </article>
        ))}
      </section>
      <p className="company-archive-footnote">公开研究来自只读搜索；搜索片段可能不完整。日期、招聘状态和要求请以招聘官网原文为准。</p>
    </main>
  );
}
