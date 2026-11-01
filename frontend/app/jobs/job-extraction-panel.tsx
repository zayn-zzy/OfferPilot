"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { apiRequest, type AgentTask, type AgentTaskEvent, type JobPosting } from "@/lib/api";

type JobFieldDraft = {
  company_name: string;
  title: string;
  city: string;
  job_type: string;
  batch: string;
  deadline: string;
  education_requirement: string;
  required_skills: string;
};

const FIELD_LABELS: Record<keyof JobFieldDraft, string> = {
  company_name: "公司",
  title: "职位",
  city: "工作地点",
  job_type: "岗位类型",
  batch: "招聘批次",
  deadline: "截止日期",
  education_requirement: "学历要求",
  required_skills: "技能要求",
};

function emptyDraft(): JobFieldDraft {
  return {
    company_name: "",
    title: "",
    city: "",
    job_type: "",
    batch: "",
    deadline: "",
    education_requirement: "",
    required_skills: "",
  };
}

function draftFromTask(task: AgentTask): JobFieldDraft {
  const fields = task.result?.fields;
  if (!fields) return emptyDraft();
  const value = (key: keyof JobFieldDraft): string => {
    const raw = fields[key]?.value;
    return Array.isArray(raw) ? raw.join("、") : raw ?? "";
  };
  return {
    company_name: value("company_name"),
    title: value("title"),
    city: value("city"),
    job_type: value("job_type"),
    batch: value("batch"),
    deadline: value("deadline"),
    education_requirement: value("education_requirement"),
    required_skills: value("required_skills"),
  };
}

type JobExtractionPanelProps = {
  onJobCreated: (job: JobPosting) => void;
  onCancel: () => void;
};

export default function JobExtractionPanel({ onJobCreated, onCancel }: JobExtractionPanelProps) {
  const [text, setText] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [task, setTask] = useState<AgentTask | null>(null);
  const [events, setEvents] = useState<AgentTaskEvent[]>([]);
  const [draft, setDraft] = useState<JobFieldDraft>(emptyDraft);
  const [submitting, setSubmitting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [error, setError] = useState("");

  const active = task?.status === "queued" || task?.status === "running";
  const needsReview = useMemo(() => new Set(task?.result?.needs_review_fields ?? []), [task]);

  useEffect(() => {
    let mounted = true;
    void apiRequest<AgentTask[]>("/api/v1/agent/tasks?limit=1")
      .then(async (recent) => {
        const latest = recent[0];
        if (!mounted || !latest) return;
        setTask(latest);
        setEvents(latest.events);
        if (latest.status === "succeeded") setDraft(draftFromTask(latest));
        if (latest.status !== "confirmed") {
          const source = await apiRequest<{ source_text: string }>(`/api/v1/agent/tasks/${latest.id}/source`);
          if (mounted) setText(source.source_text);
        }
      })
      .catch(() => {
        // Task history is optional; a first-time user can still submit a new extraction.
      })
      .finally(() => {
        if (mounted) setHistoryLoading(false);
      });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (!task || !active) return;
    let mounted = true;
    const eventSource = new EventSource(`/api/v1/agent/tasks/${task.id}/events`, { withCredentials: true });

    function receive(event: MessageEvent<string>) {
      try {
        const item = JSON.parse(event.data) as AgentTaskEvent;
        if (
          mounted
          && Number.isInteger(item.id)
          && typeof item.message === "string"
          && Number.isFinite(Date.parse(item.created_at))
        ) {
          setEvents((current) => current.some((existing) => existing.id === item.id)
            ? current
            : [...current, item].sort((a, b) => a.id - b.id));
        }
      } catch {
        // A malformed progress frame is ignored; the persisted task endpoint remains authoritative.
      }
    }

    eventSource.addEventListener("progress", receive as EventListener);
    eventSource.addEventListener("completed", receive as EventListener);
    eventSource.addEventListener("failed", receive as EventListener);

    const poll = window.setInterval(() => {
      void apiRequest<AgentTask>(`/api/v1/agent/tasks/${task.id}`)
        .then((current) => {
          if (!mounted) return;
          setTask(current);
          setEvents(current.events);
          if (current.status === "succeeded") setDraft(draftFromTask(current));
        })
        .catch((cause: unknown) => {
          if (mounted) setError(cause instanceof Error ? cause.message : "无法读取任务状态。");
        });
    }, 1500);

    return () => {
      mounted = false;
      eventSource.close();
      window.clearInterval(poll);
    };
  }, [task?.id, active]);

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const created = await apiRequest<AgentTask>("/api/v1/agent/job-extractions", {
        method: "POST",
        body: JSON.stringify({ text, source_url: sourceUrl.trim() || null }),
      });
      setTask(created);
      setEvents(created.events);
      if (created.status === "succeeded") setDraft(draftFromTask(created));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法创建岗位解析任务。");
    } finally {
      setSubmitting(false);
    }
  }

  async function retry() {
    if (!task) return;
    setError("");
    try {
      const retried = await apiRequest<AgentTask>(`/api/v1/agent/tasks/${task.id}/retry`, { method: "POST" });
      setTask(retried);
      setEvents(retried.events);
      if (retried.status === "succeeded") setDraft(draftFromTask(retried));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "任务重试失败。");
    }
  }

  async function deleteTask() {
    if (!task) return;
    setError("");
    try {
      await apiRequest(`/api/v1/agent/tasks/${task.id}`, { method: "DELETE" });
      startAnother();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除任务失败。");
    }
  }

  async function openSavedJob() {
    if (!task?.job_id) {
      setError("该任务没有可查看的关联岗位。");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const saved = await apiRequest<JobPosting>(`/api/v1/jobs/${task.job_id}`);
      onJobCreated(saved);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取已保存的岗位。");
    } finally {
      setSaving(false);
    }
  }

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!task) return;
    setSaving(true);
    setError("");
    try {
      const payload = {
        company_name: draft.company_name.trim() || null,
        title: draft.title.trim() || null,
        city: draft.city.trim() || null,
        job_type: draft.job_type.trim() || null,
        batch: draft.batch.trim() || null,
        deadline: draft.deadline || null,
        education_requirement: draft.education_requirement.trim() || null,
        required_skills: draft.required_skills.split(/[、,，]/).map((item) => item.trim()).filter(Boolean),
      };
      const job = await apiRequest<JobPosting>(`/api/v1/agent/tasks/${task.id}/confirm`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      onJobCreated(job);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存岗位失败。");
    } finally {
      setSaving(false);
    }
  }

  function updateDraft(key: keyof JobFieldDraft, value: string) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function startAnother() {
    setTask(null);
    setEvents([]);
    setDraft(emptyDraft());
    setText("");
    setSourceUrl("");
    setError("");
  }

  return (
    <section className="job-extraction-panel" aria-label="AI 岗位信息提取">
      {!task && <>
        <p className="job-form-hint">原文会发送到你配置的模型服务商处理，请先确认该服务商符合你的隐私要求。模型只提取原文明确支持的字段，不会访问招聘网站或自动投递。</p>
        <form className="job-extraction-form" onSubmit={start}>
          <label>来源链接（选填）<input type="url" maxLength={2048} value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://…" /></label>
          <label>招聘原文<textarea required minLength={20} maxLength={30000} rows={9} value={text} onChange={(event) => setText(event.target.value)} placeholder="粘贴岗位职责、任职要求和招聘信息，至少 20 个字符" /></label>
          <div className="job-extraction-actions">
            <button className="button button-primary" disabled={submitting || historyLoading} type="submit">{historyLoading ? "读取任务中…" : submitting ? "正在创建任务…" : "提取岗位信息"}</button>
            <button className="button button-secondary" onClick={onCancel} type="button">取消</button>
          </div>
        </form>
      </>}

      {task && <div className="agent-task-state">
        <div className="agent-task-heading">
          <div><p className="eyebrow">岗位信息提取</p><h3>{task.status === "queued" ? "任务排队中" : task.status === "running" ? "正在提取" : task.status === "succeeded" ? "提取完成，请核对" : task.status === "confirmed" ? "岗位已保存" : "提取失败"}</h3></div>
          <span className={`agent-task-status agent-task-${task.status}`}>{({ queued: "排队中", running: "运行中", succeeded: "待核对", failed: "失败", confirmed: "已保存" })[task.status]}</span>
        </div>
        <ol className="agent-task-events" aria-label="任务进度">
          {(events.length ? events : task.events).map((item) => <li key={item.id}><span>{item.message}</span><time>{new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(item.created_at))}</time></li>)}
        </ol>
        {active && <p className="job-form-hint">任务状态会保存在账户中；关闭页面后重新打开此面板可继续查看。</p>}
        {task.status === "failed" && <div className="agent-task-error"><p role="alert">{task.error_message || "任务失败。"}</p><p>尝试次数：{task.attempt_count}/3。修正模型配置或等待服务恢复后可重试。</p><button className="button button-primary" disabled={task.attempt_count >= 3} onClick={() => void retry()} type="button">重试</button></div>}
        {task.status === "failed" && <button className="job-quiet-action danger-text" onClick={() => void deleteTask()} type="button">清理失败任务并新建</button>}
        {task.status === "succeeded" && task.result && <form className="job-extraction-review" onSubmit={confirm}>
          <p className="job-form-hint">确认前请检查每个字段。标为“需要确认”的字段置信度较低、缺少原文引用或未提取到；原文引用已由服务端逐字校验。</p>
          <div className="job-extraction-fields">
            {(Object.keys(FIELD_LABELS) as (keyof JobFieldDraft)[]).map((key) => {
              const evidence = task.result?.fields[key];
              const label = FIELD_LABELS[key];
              return <label className={needsReview.has(key) ? "agent-field agent-field-review" : "agent-field"} key={key}>
                <span className="agent-field-heading"><strong>{label}</strong><small>{needsReview.has(key) ? "需要确认" : "有原文依据"} · 置信度 {Math.round((evidence?.confidence ?? 0) * 100)}%</small></span>
                <input type={key === "deadline" ? "date" : "text"} value={draft[key]} onChange={(event) => updateDraft(key, event.target.value)} placeholder="原文没有明确提供" />
                {evidence?.evidence && <small className="agent-field-evidence">原文：“{evidence.evidence}”</small>}
              </label>;
            })}
          </div>
          <div className="job-extraction-actions"><button className="button button-primary" disabled={saving} type="submit">{saving ? "保存中…" : "确认并保存岗位"}</button><button className="button button-secondary" onClick={onCancel} type="button">取消</button></div>
        </form>}
        {error && <p className="form-error" role="alert">{error}</p>}
        {task.status === "confirmed" && <p className="profile-message profile-success" role="status">岗位已保存，原文与字段引用已关联到岗位。</p>}
        {task.status === "confirmed" && <button className="button button-primary" disabled={saving || !task.job_id} onClick={() => void openSavedJob()} type="button">{saving ? "读取岗位中…" : "查看已保存岗位"}</button>}
        {text && task.status !== "confirmed" && <details className="agent-source-text"><summary>查看提交的招聘原文</summary><pre>{text}</pre></details>}
        {task.status === "confirmed" && <button className="button button-secondary" onClick={startAnother} type="button">新建岗位解析任务</button>}
        {task.status === "succeeded" && <button className="job-quiet-action danger-text" onClick={() => void deleteTask()} type="button">清理此结果并新建任务</button>}
      </div>}
    </section>
  );
}
