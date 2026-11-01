"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import {
  APPLICATION_STAGES,
  APPLICATION_STAGE_LABELS,
  ApiError,
  apiRequest,
  type JobCsvPreview,
  type JobCsvPreviewRow,
  type ApplicationStatusEvent,
  type JobPosting,
  type JobPostingWrite,
  type ResumeVersionSummary,
} from "@/lib/api";
import JobCard from "./job-card";
import JobEditor from "./job-editor";
import JobExtractionPanel from "./job-extraction-panel";

type Filters = { search: string; city: string; status: string; deadline_before: string; tag: string };
const DEFAULT_FILTERS: Filters = { search: "", city: "", status: "", deadline_before: "", tag: "" };

function apiMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : "操作失败，请稍后重试。";
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [resumes, setResumes] = useState<ResumeVersionSummary[]>([]);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<JobCsvPreview | null>(null);
  const [selectedCsvRows, setSelectedCsvRows] = useState<number[]>([]);
  const [previewingCsv, setPreviewingCsv] = useState(false);
  const [importingCsv, setImportingCsv] = useState(false);
  const [createPanel, setCreatePanel] = useState<"new" | "csv" | "extract" | null>(null);
  const [filters, setFilters] = useState<Filters>({ ...DEFAULT_FILTERS });
  const [draftFilters, setDraftFilters] = useState(filters);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const [savedJobId, setSavedJobId] = useState<string | null>(null);
  const listRequestVersion = useRef(0);
  const pendingSavedJobFocus = useRef<string | null>(null);

  async function loadJobs(nextFilters: Filters = filters, visibleJob?: JobPosting) {
    const requestVersion = ++listRequestVersion.current;
    setError("");
    const params = new URLSearchParams();
    if (nextFilters.search.trim()) params.set("search", nextFilters.search.trim());
    if (nextFilters.city.trim()) params.set("city", nextFilters.city.trim());
    if (nextFilters.status) params.set("status", nextFilters.status);
    if (nextFilters.deadline_before) params.set("deadline_before", nextFilters.deadline_before);
    if (nextFilters.tag.trim()) params.set("tag", nextFilters.tag.trim());
    try {
      const query = params.toString();
      const result = await apiRequest<JobPosting[]>(`/api/v1/jobs${query ? `?${query}` : ""}`);
      if (requestVersion !== listRequestVersion.current) return;
      if (visibleJob) {
        const current = result.find((job) => job.id === visibleJob.id) ?? visibleJob;
        pendingSavedJobFocus.current = current.id;
        setJobs([current, ...result.filter((job) => job.id !== current.id)]);
      } else {
        setJobs(result);
      }
      setRequiresLogin(false);
    } catch (cause) {
      if (requestVersion !== listRequestVersion.current) return;
      setError(apiMessage(cause));
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      if (requestVersion === listRequestVersion.current) setLoading(false);
    }
  }

  async function showSavedJobs(saved: JobPosting[], message: string) {
    // A pre-save list response must not replace the newly confirmed records.
    listRequestVersion.current += 1;
    const nextFilters = { ...DEFAULT_FILTERS };
    const latestFirst = [...saved].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
    const savedIds = new Set(latestFirst.map((job) => job.id));
    pendingSavedJobFocus.current = latestFirst[0]?.id ?? null;
    setSavedJobId(latestFirst[0]?.id ?? null);
    setFilters(nextFilters);
    setDraftFilters(nextFilters);
    setJobs((current) => [...latestFirst, ...current.filter((job) => !savedIds.has(job.id))]);
    setLoading(false);
    setRequiresLogin(false);
    setError("");
    setSuccess(message);
    await loadJobs(nextFilters, latestFirst[0]);
  }

  useEffect(() => {
    const jobId = pendingSavedJobFocus.current;
    if (!jobId) return;
    const card = document.getElementById(`job-${jobId}`);
    if (!card) return;
    pendingSavedJobFocus.current = null;
    card.scrollIntoView({ block: "center" });
    card.focus({ preventScroll: true });
  }, [jobs]);

  async function previewCsv(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!csvFile) {
      setError("请先选择岗位 CSV 文件。");
      return;
    }
    setError("");
    setSuccess("");
    setPreviewingCsv(true);
    const formData = new FormData();
    formData.append("file", csvFile);
    try {
      const result = await apiRequest<JobCsvPreview>("/api/v1/jobs/import/preview", {
        method: "POST",
        body: formData,
      });
      setCsvPreview(result);
      setSelectedCsvRows(
        result.rows
          .filter((row) => row.status === "ready")
          .map((row) => row.row_number),
      );
    } catch (cause) {
      setError(apiMessage(cause));
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      setCsvPreview(null);
    } finally {
      setPreviewingCsv(false);
    }
  }

  async function importSelectedCsvRows() {
    const jobsToImport = csvPreview?.rows
      .filter((row) => selectedCsvRows.includes(row.row_number) && row.status === "ready")
      .flatMap((row) => row.data ? [row.data] : []) ?? [];
    if (jobsToImport.length === 0) {
      setError("请选择至少一条校验通过的岗位。");
      return;
    }
    setError("");
    setSuccess("");
    setImportingCsv(true);
    try {
      const imported = await apiRequest<JobPosting[]>("/api/v1/jobs/import", {
        method: "POST",
        body: JSON.stringify({ jobs: jobsToImport }),
      });
      setCsvFile(null);
      setCsvPreview(null);
      setSelectedCsvRows([]);
      await showSavedJobs(imported, `已导入 ${imported.length} 条岗位。可以在岗位列表中继续编辑。`);
    } catch (cause) {
      setError(apiMessage(cause));
    } finally {
      setImportingCsv(false);
    }
  }

  function toggleCsvRow(row: JobCsvPreviewRow, checked: boolean) {
    setSelectedCsvRows((current) => checked
      ? [...current, row.row_number]
      : current.filter((number) => number !== row.row_number));
  }

  function toggleAllCsvRows(checked: boolean) {
    setSelectedCsvRows(checked
      ? csvPreview?.rows.filter((row) => row.status === "ready").map((row) => row.row_number) ?? []
      : []);
  }

  useEffect(() => {
    void loadJobs();
  }, []);

  useEffect(() => {
    apiRequest<ResumeVersionSummary[]>("/api/v1/resumes")
      .then(setResumes)
      .catch(() => setResumes([]));
  }, []);

  async function createJob(payload: JobPostingWrite) {
    setSuccess("");
    const saved = await apiRequest<JobPosting>("/api/v1/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setCreatePanel(null);
    await showSavedJobs([saved], "岗位已保存。");
  }

  async function saveJob(job: JobPosting, payload: JobPostingWrite) {
    const saved = await apiRequest<JobPosting>(`/api/v1/jobs/${job.id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    setJobs((current) => current.map((item) => item.id === saved.id ? saved : item));
    await loadJobs();
  }

  async function deleteJob(job: JobPosting) {
    await apiRequest(`/api/v1/jobs/${job.id}`, { method: "DELETE" });
    setJobs((current) => current.filter((item) => item.id !== job.id));
    setSavedJobId(null);
    setSuccess("岗位已删除。");
  }

  async function updateApplication(job: JobPosting, update: Record<string, unknown>) {
    const saved = await apiRequest<JobPosting>(`/api/v1/jobs/${job.id}/application`, {
      method: "PUT",
      body: JSON.stringify(update),
    });
    setJobs((current) => current.map((item) => item.id === saved.id ? saved : item));
    await loadJobs();
  }

  async function readHistory(job: JobPosting): Promise<ApplicationStatusEvent[]> {
    return apiRequest<ApplicationStatusEvent[]>(`/api/v1/jobs/${job.id}/application/history`);
  }

  async function logout() {
    try {
      await apiRequest("/api/v1/auth/logout", { method: "POST" });
      window.location.assign("/login");
    } catch (cause) {
      setError(apiMessage(cause));
    }
  }

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSuccess("");
    setSavedJobId(null);
    setFilters(draftFilters);
    void loadJobs(draftFilters);
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
          <Link className="text-link" href="/knowledge">资料问答</Link>
          <button className="text-button" onClick={() => void logout()} type="button">退出登录</button>
        </nav>
      </header>

      <section className="jobs-heading">
        <h1>岗位管理</h1>
        <p>记录岗位、投递进度和下一步安排。</p>
        <div className="jobs-toolbar">
          <button aria-expanded={createPanel === "new"} className="button button-primary" onClick={() => setCreatePanel((current) => current === "new" ? null : "new")} type="button">{createPanel === "new" ? "收起新增" : "新增岗位"}</button>
          <button aria-expanded={createPanel === "csv"} className="button button-secondary" onClick={() => setCreatePanel((current) => current === "csv" ? null : "csv")} type="button">{createPanel === "csv" ? "收起导入" : "导入 CSV"}</button>
          <button aria-expanded={createPanel === "extract"} className="button button-secondary" onClick={() => setCreatePanel((current) => current === "extract" ? null : "extract")} type="button">{createPanel === "extract" ? "收起 AI 提取" : "AI 提取岗位"}</button>
        </div>
      </section>

      {error && <div className="profile-message profile-error" role="alert">{error}{requiresLogin && <> <Link href="/login">去登录</Link></>}</div>}
      {success && <div className="profile-message profile-success" role="status">{success}{savedJobId && <> <a className="text-link" href={`#job-${savedJobId}`}>查看岗位</a></>}</div>}

      {createPanel === "csv" && <section className="profile-panel job-form-panel csv-import-panel">
        <div className="profile-panel-heading">
          <div>
            <p className="eyebrow">批量导入</p>
            <h2>从 CSV 添加岗位</h2>
          </div>
          <a className="button button-secondary" href="/api/v1/jobs/import/template">
            下载 CSV 模板
          </a>
        </div>
        <p className="job-form-hint">
          支持 UTF-8 或 GB18030 编码，最多 500 条、5 MB。先预览校验结果，再选择要保存的岗位；导入后可继续编辑。
        </p>
        <form className="csv-upload-row" onSubmit={previewCsv}>
          <label>
            选择 CSV 文件
            <input
              accept=".csv,text/csv"
              onChange={(event) => {
                setCsvFile(event.target.files?.[0] ?? null);
                setCsvPreview(null);
                setSelectedCsvRows([]);
              }}
              type="file"
            />
          </label>
          <button className="button button-primary" disabled={!csvFile || previewingCsv} type="submit">
            {previewingCsv ? "正在检查…" : "预览并检查"}
          </button>
        </form>

        {csvPreview && (
          <div className="csv-preview">
            <div className="csv-preview-summary">
              <span>可导入 {csvPreview.ready_count} 条</span>
              <span>重复 {csvPreview.duplicate_count} 条</span>
              <span>有错误 {csvPreview.invalid_count} 条</span>
            </div>
            <div className="csv-preview-table-wrap">
              <table className="csv-preview-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        aria-label="选择全部可导入岗位"
                        checked={csvPreview.ready_count > 0 && selectedCsvRows.length === csvPreview.ready_count}
                        onChange={(event) => toggleAllCsvRows(event.target.checked)}
                        type="checkbox"
                      />
                    </th>
                    <th>行</th><th>公司</th><th>职位</th><th>城市</th><th>截止日期</th><th>来源</th><th>检查结果</th>
                  </tr>
                </thead>
                <tbody>
                  {csvPreview.rows.map((row) => (
                    <tr key={row.row_number}>
                      <td>
                        <input
                          aria-label={`选择 CSV 第 ${row.row_number} 行`}
                          checked={selectedCsvRows.includes(row.row_number)}
                          disabled={row.status !== "ready"}
                          onChange={(event) => toggleCsvRow(row, event.target.checked)}
                          type="checkbox"
                        />
                      </td>
                      <td>{row.row_number}</td>
                      <td>{row.company_name || "—"}</td>
                      <td>{row.title || "—"}</td>
                      <td>{row.city || "—"}</td>
                      <td>{row.deadline || "—"}</td>
                      <td>
                        {row.source_url
                          ? <a href={row.source_url} rel="noreferrer" target="_blank">打开来源</a>
                          : "—"}
                      </td>
                      <td>
                        <strong className={`csv-row-status csv-row-${row.status}`}>
                          {row.status === "ready" ? "可导入" : row.status === "duplicate" ? "重复来源" : "需要修正"}
                        </strong>
                        {row.duplicate_detail && <small>{row.duplicate_detail}</small>}
                        {row.errors.map((message) => <small key={message}>{message}</small>)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="csv-preview-actions">
              <button
                className="button button-primary"
                disabled={selectedCsvRows.length === 0 || importingCsv}
                onClick={() => void importSelectedCsvRows()}
                type="button"
              >
                {importingCsv ? "导入中…" : `导入选中的 ${selectedCsvRows.length} 条`}
              </button>
              <button className="button button-secondary" onClick={() => setCsvPreview(null)} type="button">
                取消预览
              </button>
            </div>
          </div>
        )}
      </section>}

      {createPanel === "new" && <section className="profile-panel job-form-panel">
        <div className="profile-panel-heading"><h2>新增岗位</h2></div>
        <JobEditor onSave={createJob} onCancel={() => setCreatePanel(null)} />
      </section>}

      {createPanel === "extract" && <section className="profile-panel job-form-panel">
        <div className="profile-panel-heading"><div><p className="eyebrow">Agent 岗位抽取</p><h2>从招聘原文提取岗位字段</h2></div></div>
        <JobExtractionPanel onCancel={() => setCreatePanel(null)} onJobCreated={(saved) => {
          setCreatePanel(null);
          void showSavedJobs([saved], "AI 提取的岗位已保存，原文和字段依据已关联。");
        }} />
      </section>}

      <section className="job-list-section">
        <div className="job-list-heading"><h2>我的岗位</h2></div>

        <form className="job-filter-form" onSubmit={applyFilters}>
          <label>公司 / 职位 / 行业<input value={draftFilters.search} onChange={(event) => setDraftFilters({ ...draftFilters, search: event.target.value })} placeholder="搜索公司、职位、城市或行业" /></label>
          <label>城市<input value={draftFilters.city} onChange={(event) => setDraftFilters({ ...draftFilters, city: event.target.value })} placeholder="筛选城市" /></label>
          <label>投递状态<select value={draftFilters.status} onChange={(event) => setDraftFilters({ ...draftFilters, status: event.target.value })}>
            <option value="">全部状态</option>
            <option value="untracked">未记录投递</option>
            {APPLICATION_STAGES.map((stage) => <option key={stage} value={stage}>{APPLICATION_STAGE_LABELS[stage]}</option>)}
          </select></label>
          <label>截止日期不晚于<input type="date" value={draftFilters.deadline_before} onChange={(event) => setDraftFilters({ ...draftFilters, deadline_before: event.target.value })} /></label>
          <label>标签<input value={draftFilters.tag} onChange={(event) => setDraftFilters({ ...draftFilters, tag: event.target.value })} placeholder="筛选标签" /></label>
          <button className="button button-primary" type="submit">筛选</button>
        </form>

        {loading ? <div className="profile-loading">正在载入岗位…</div> : jobs.length === 0 ? (
          <div className="job-empty-state"><strong>{requiresLogin ? "请先登录后管理岗位" : "还没有保存岗位"}</strong><span>{requiresLogin ? "登录后，岗位和申请记录会保存在你的账户中。" : "点击“新增岗位”或“导入 CSV”开始记录。"}</span></div>
        ) : (
          <div className="job-card-list">
            {jobs.map((job) => (
              <JobCard
                key={job.id}
                job={job}
                onSave={saveJob}
                onDelete={deleteJob}
                onUpdateApplication={updateApplication}
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
