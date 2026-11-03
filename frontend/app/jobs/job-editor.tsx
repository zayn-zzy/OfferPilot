"use client";

import { type FormEvent, useState } from "react";
import {
  apiRequest,
  duplicateJobIdFromError,
  type JobPosting,
  type JobPostingWrite,
} from "@/lib/api";

type JobDraft = Omit<JobPostingWrite, "required_skills" | "tags"> & {
  required_skills: string;
  tags: string;
};

function makeDraft(job?: JobPosting): JobDraft {
  return {
    company_name: job?.company_name ?? "",
    company_website_url: job?.company_website_url ?? "",
    recruitment_url: job?.recruitment_url ?? "",
    industry: job?.industry ?? "",
    company_notes: job?.company_notes ?? "",
    title: job?.title ?? "",
    city: job?.city ?? "",
    job_type: job?.job_type ?? "",
    batch: job?.batch ?? "",
    deadline: job?.deadline ?? "",
    education_requirement: job?.education_requirement ?? "",
    required_skills: job?.required_skills.join("，") ?? "",
    description: job?.description ?? "",
    source_url: job?.source_url ?? "",
    source_type: job?.source_type ?? "manual",
    tags: job?.tags.join("，") ?? "",
  };
}

function makePayload(draft: JobDraft): JobPostingWrite {
  const splitList = (value: string) => value.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean);
  const optional = (value: string | null) => value?.trim() || null;
  return {
    company_name: optional(draft.company_name),
    company_website_url: optional(draft.company_website_url),
    recruitment_url: optional(draft.recruitment_url),
    industry: optional(draft.industry),
    company_notes: optional(draft.company_notes),
    title: optional(draft.title),
    city: optional(draft.city),
    job_type: optional(draft.job_type),
    batch: optional(draft.batch),
    deadline: draft.deadline || null,
    education_requirement: optional(draft.education_requirement),
    required_skills: splitList(draft.required_skills),
    description: optional(draft.description),
    source_url: optional(draft.source_url),
    source_type: draft.source_type,
    tags: splitList(draft.tags),
  };
}

type JobEditorProps = {
  job?: JobPosting;
  onSave: (payload: JobPostingWrite) => Promise<void>;
  onMerge?: (targetJobId: string, payload: JobPostingWrite) => Promise<void>;
  onCancel: () => void;
};

export default function JobEditor({ job, onSave, onMerge, onCancel }: JobEditorProps) {
  const [draft, setDraft] = useState(() => makeDraft(job));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [duplicateTarget, setDuplicateTarget] = useState<JobPosting | null>(null);

  function update(field: Exclude<keyof JobDraft, "source_type">, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setDuplicateTarget(null);
    setSaving(true);
    try {
      await onSave(makePayload(draft));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败，请重试。");
      const duplicateJobId = !job ? duplicateJobIdFromError(cause) : null;
      if (duplicateJobId) {
        try {
          setDuplicateTarget(await apiRequest<JobPosting>(`/api/v1/jobs/${duplicateJobId}`));
        } catch {
          // Keep the actionable conflict message if the target cannot be loaded.
        }
      }
    } finally {
      setSaving(false);
    }
  }

  async function mergeIntoExisting() {
    if (!duplicateTarget || !onMerge) return;
    setSaving(true);
    setError("");
    try {
      await onMerge(duplicateTarget.id, makePayload(draft));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "合并岗位信息失败，请重试。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form aria-label={job ? "编辑岗位" : "新增岗位"} className="job-editor" onSubmit={submit}>
      <fieldset className="profile-form job-form" disabled={saving}>
        <label>公司名称<input maxLength={200} value={draft.company_name ?? ""} onChange={(event) => update("company_name", event.target.value)} /></label>
        <label>职位名称<input maxLength={200} value={draft.title ?? ""} onChange={(event) => update("title", event.target.value)} /></label>
        <label>工作城市<input maxLength={120} value={draft.city ?? ""} onChange={(event) => update("city", event.target.value)} /></label>
        <label>截止日期<input type="date" value={draft.deadline ?? ""} onChange={(event) => update("deadline", event.target.value)} /></label>
        <label className="job-field-wide">岗位来源<input type="url" value={draft.source_url ?? ""} onChange={(event) => update("source_url", event.target.value)} placeholder="招聘页面链接" /></label>
        <label className="profile-full-width">岗位描述<textarea rows={4} maxLength={30000} value={draft.description ?? ""} onChange={(event) => update("description", event.target.value)} /></label>
        <details className="job-more-fields profile-full-width">
          <summary>更多信息（技能、标签、公司资料）</summary>
          <div className="profile-form job-form">
            <label>岗位类型<input maxLength={80} value={draft.job_type ?? ""} onChange={(event) => update("job_type", event.target.value)} placeholder="校招 / 实习" /></label>
            <label>招聘批次<input maxLength={120} value={draft.batch ?? ""} onChange={(event) => update("batch", event.target.value)} /></label>
            <label>学历要求<input maxLength={120} value={draft.education_requirement ?? ""} onChange={(event) => update("education_requirement", event.target.value)} /></label>
            <label>行业<input maxLength={120} value={draft.industry ?? ""} onChange={(event) => update("industry", event.target.value)} /></label>
            <label>技能要求<input value={draft.required_skills} onChange={(event) => update("required_skills", event.target.value)} placeholder="Python，SQL" /></label>
            <label>标签<input value={draft.tags} onChange={(event) => update("tags", event.target.value)} placeholder="优先申请，上海" /></label>
            <label>公司官网<input type="url" value={draft.company_website_url ?? ""} onChange={(event) => update("company_website_url", event.target.value)} /></label>
            <label>招聘主页<input type="url" value={draft.recruitment_url ?? ""} onChange={(event) => update("recruitment_url", event.target.value)} /></label>
            <label className="profile-full-width">公司备注<textarea rows={2} maxLength={5000} value={draft.company_notes ?? ""} onChange={(event) => update("company_notes", event.target.value)} /></label>
          </div>
        </details>
        <div className="profile-full-width profile-form-actions">
          <button className="button button-primary" type="submit">{saving ? "保存中…" : job ? "保存修改" : "保存岗位"}</button>
          <button className="button button-secondary" onClick={onCancel} type="button">取消</button>
        </div>
      </fieldset>
      {duplicateTarget && onMerge && <div className="job-duplicate-merge" role="status">
        <strong>发现已有岗位</strong>
        <p>“{duplicateTarget.company_name || "未填写公司"} · {duplicateTarget.title || "未填写职位"}”使用了相同来源链接。</p>
        <p>合并会保留已有非空字段，仅补齐空字段；技能和标签会去重合并。已有投递记录与阶段历史保持不变。</p>
        <button className="button button-primary" disabled={saving} onClick={() => void mergeIntoExisting()} type="button">
          {saving ? "正在合并…" : "合并到这个岗位"}
        </button>
      </div>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </form>
  );
}
