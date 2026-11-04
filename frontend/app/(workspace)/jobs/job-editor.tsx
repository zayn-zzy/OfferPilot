"use client";

import { type FormEvent, useState } from "react";
import { Accordion, Alert, Button, Fieldset, Group, SimpleGrid, Stack, Text, Textarea, TextInput } from "@mantine/core";
import { DateInput } from "@mantine/dates";
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
    <form aria-label={job ? "编辑岗位" : "新增岗位"} onSubmit={submit}>
      <Stack gap="md">
        <Fieldset disabled={saving} variant="unstyled">
          <Stack gap="md">
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput label="公司名称" maxLength={200} value={draft.company_name ?? ""} onChange={(event) => update("company_name", event.currentTarget.value)} />
              <TextInput label="职位名称" maxLength={200} value={draft.title ?? ""} onChange={(event) => update("title", event.currentTarget.value)} />
              <TextInput label="工作城市" maxLength={120} value={draft.city ?? ""} onChange={(event) => update("city", event.currentTarget.value)} />
              <DateInput label="截止日期" clearable value={draft.deadline || null} onChange={(value) => update("deadline", value ?? "")} valueFormat="YYYY-MM-DD" />
            </SimpleGrid>
            <TextInput label="岗位来源" type="url" value={draft.source_url ?? ""} onChange={(event) => update("source_url", event.currentTarget.value)} placeholder="招聘页面链接" />
            <Textarea label="岗位描述" autosize minRows={4} maxRows={10} maxLength={30000} value={draft.description ?? ""} onChange={(event) => update("description", event.currentTarget.value)} />
            <Accordion variant="separated">
              <Accordion.Item value="details">
                <Accordion.Control>更多信息（技能、标签、公司资料）</Accordion.Control>
                <Accordion.Panel>
                  <Stack>
                    <SimpleGrid cols={{ base: 1, sm: 2 }}>
                      <TextInput label="岗位类型" maxLength={80} value={draft.job_type ?? ""} onChange={(event) => update("job_type", event.currentTarget.value)} placeholder="校招 / 实习" />
                      <TextInput label="招聘批次" maxLength={120} value={draft.batch ?? ""} onChange={(event) => update("batch", event.currentTarget.value)} />
                      <TextInput label="学历要求" maxLength={120} value={draft.education_requirement ?? ""} onChange={(event) => update("education_requirement", event.currentTarget.value)} />
                      <TextInput label="行业" maxLength={120} value={draft.industry ?? ""} onChange={(event) => update("industry", event.currentTarget.value)} />
                      <TextInput label="技能要求" value={draft.required_skills} onChange={(event) => update("required_skills", event.currentTarget.value)} placeholder="Python，SQL" />
                      <TextInput label="标签" value={draft.tags} onChange={(event) => update("tags", event.currentTarget.value)} placeholder="优先申请，上海" />
                      <TextInput label="公司官网" type="url" value={draft.company_website_url ?? ""} onChange={(event) => update("company_website_url", event.currentTarget.value)} />
                      <TextInput label="招聘主页" type="url" value={draft.recruitment_url ?? ""} onChange={(event) => update("recruitment_url", event.currentTarget.value)} />
                    </SimpleGrid>
                    <Textarea label="公司备注" minRows={2} autosize maxLength={5000} value={draft.company_notes ?? ""} onChange={(event) => update("company_notes", event.currentTarget.value)} />
                  </Stack>
                </Accordion.Panel>
              </Accordion.Item>
            </Accordion>
            <Group>
              <Button loading={saving} type="submit">{job ? "保存修改" : "保存岗位"}</Button>
              <Button variant="default" onClick={onCancel} type="button">取消</Button>
            </Group>
          </Stack>
        </Fieldset>
        {duplicateTarget && onMerge && <Alert title="发现已有岗位" color="yellow" role="status">
          <Stack gap="sm">
            <Text size="sm">{duplicateTarget.company_name || "未填写公司"} / {duplicateTarget.title || "未填写职位"} 使用了相同来源链接。</Text>
            <Text size="sm">合并会保留已有非空字段，仅补齐空字段；技能和标签会去重合并。已有投递记录与阶段历史保持不变。</Text>
            <Button loading={saving} onClick={() => void mergeIntoExisting()} type="button">合并到这个岗位</Button>
          </Stack>
        </Alert>}
        {error && <Alert color="red" role="alert">{error}</Alert>}
      </Stack>
    </form>
  );
}
