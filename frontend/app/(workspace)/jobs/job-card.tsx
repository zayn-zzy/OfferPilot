"use client";

import { type FormEvent, useEffect, useState } from "react";
import { Accordion, Alert, Anchor, Badge, Blockquote, Button, Collapse, Divider, Fieldset, Group, Menu, Paper, Select, SimpleGrid, Stack, Tabs, Text, Textarea, TextInput, ThemeIcon, Timeline, Title } from "@mantine/core";
import { DateInput } from "@mantine/dates";
import { IconBuilding, IconCalendar, IconDots, IconEdit, IconExternalLink, IconFileText, IconSearch, IconTarget, IconTrash } from "@tabler/icons-react";
import { Feedback, LoadingState } from "@/components/ui";
import { useConfirm } from "@/lib/use-confirm";
import classes from "./jobs.module.css";
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
    <Stack gap="md">
      <form aria-label="投递记录" onSubmit={submit}>
        <Stack>
          <Fieldset disabled={saving} variant="unstyled"><SimpleGrid cols={{ base: 1, sm: 2 }}>
            <DateInput label="投递日期" value={appliedAt || null} clearable onChange={(value) => setAppliedAt(value ?? "")} valueFormat="YYYY-MM-DD" />
            <Select label="关联简历版本" value={resumeVersionId || null} clearable placeholder="暂不关联" onChange={(value) => setResumeVersionId(value ?? "")} data={resumes.map((resume) => ({ value: resume.id, label: resume.filename }))} />
            <DateInput label="下一步日期" value={nextActionDue || null} clearable onChange={(value) => setNextActionDue(value ?? "")} valueFormat="YYYY-MM-DD" />
            <TextInput label="下一步行动" value={nextAction} maxLength={500} onChange={(event) => setNextAction(event.currentTarget.value)} placeholder="例如：完成在线测评" />
          </SimpleGrid>
          <Textarea mt="md" label="联系人/进展备注" minRows={3} autosize maxLength={5000} value={notes} onChange={(event) => setNotes(event.currentTarget.value)} /></Fieldset>
          <Group><Button loading={saving} type="submit">保存投递记录</Button>{job.application && <Button variant="default" loading={historyLoading} onClick={() => void toggleHistory()} type="button">{history !== null ? "隐藏阶段记录" : "查看阶段记录"}</Button>}</Group>
        </Stack>
      </form>
      <Feedback error={error} />
      {history !== null && <Timeline active={history.length - 1} bulletSize={16} lineWidth={2}>{history.map((event) => <Timeline.Item key={event.id} title={`${event.from_status ? APPLICATION_STAGE_LABELS[event.from_status] : "开始记录"} → ${APPLICATION_STAGE_LABELS[event.to_status]}`}><Text size="xs" c="dimmed">{new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(event.created_at))}</Text></Timeline.Item>)}{history.length === 0 && <Text size="sm" c="dimmed">暂无阶段记录</Text>}</Timeline>}
    </Stack>
  );
}

export default function JobCard(props: JobCardProps) {
  const { job, onSave, onDelete, onUpdateApplication } = props;
  const confirm = useConfirm();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [detailTab, setDetailTab] = useState<string | null>("details");
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
    if (!await confirm({ title: "删除岗位", message: `确定删除“${job.company_name || "未填写公司"} - ${job.title || "未填写职位"}”？投递记录也会删除。`, confirmLabel: "删除岗位", danger: true })) return;
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

  function openDetail(value: string) {
    setDetailsOpen(true);
    setDetailTab(value);
    if (value === "match" && !matchAnalysis) void analyzeMatch();
    if (value === "research" && !researchOpen) void toggleCompanyResearch();
    if (value === "evidence" && !evidenceOpen) void toggleEvidence();
  }

  return (
    <Paper component="article" aria-label={`${job.company_name || "未填写公司"} ${job.title || "未填写职位"}`} className={`job-card ${classes.card}`} id={`job-${job.id}`} tabIndex={-1} withBorder p={{ base: "md", sm: "lg" }} radius="md">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="wrap" className={classes.cardHeading}>
          <Group wrap="nowrap" align="flex-start" className={classes.jobIdentity}>
            <ThemeIcon variant="light" size={42} radius="md"><IconBuilding size={22} /></ThemeIcon>
            <Stack gap={4} className={classes.jobIdentity}>
              <Text size="sm" c="dimmed">{job.company_name || "未填写公司"}</Text>
              <Title order={3} size="h4" className={classes.breakWords}>{job.title || "未填写职位"}</Title>
              <Group gap="xs">{[job.city, job.job_type, job.batch].filter(Boolean).map((value) => <Badge key={value} variant="light" color="gray">{value}</Badge>)}</Group>
            </Stack>
          </Group>
          <Group gap="xs" align="flex-end" className={classes.stageActions}>
            <Select label="投递阶段" aria-label="投递阶段" className={classes.stageSelect} size="sm" disabled={busy} value={job.application?.status ?? "untracked"} onChange={(value) => { if (value && value !== "untracked") void changeStage(value); }} data={[{ value: "untracked", label: "未记录", disabled: true }, ...APPLICATION_STAGES.map((stage) => ({ value: stage, label: APPLICATION_STAGE_LABELS[stage] }))]} />
            <Menu position="bottom-end" withinPortal><Menu.Target><Button variant="subtle" color="gray" px="xs" aria-label="岗位更多操作" disabled={busy}><IconDots size={18} /></Button></Menu.Target><Menu.Dropdown><Menu.Item color="red" leftSection={<IconTrash size={16} />} onClick={() => void remove()}>删除</Menu.Item></Menu.Dropdown></Menu>
          </Group>
        </Group>
        <Group justify="space-between" gap="sm">
          <Group gap="xs"><IconCalendar size={15} /><Text size="sm" c="dimmed">截止：{job.deadline || "未填写"}</Text></Group>
          {job.source_url && <Anchor href={job.source_url} rel="noreferrer" target="_blank" size="sm">岗位来源 <IconExternalLink size={13} /></Anchor>}
        </Group>
        <Group gap="xs" className={classes.cardActions}>
          <Button size="xs" variant={panel === "edit" ? "light" : "default"} leftSection={<IconEdit size={14} />} aria-expanded={panel === "edit"} aria-controls={`job-edit-${job.id}`} disabled={busy} onClick={() => togglePanel("edit")}>{panel === "edit" ? "取消编辑" : "编辑"}</Button>
          <Button size="xs" variant={panel === "application" ? "light" : "subtle"} aria-expanded={panel === "application"} aria-controls={`job-progress-${job.id}`} disabled={busy} onClick={() => togglePanel("application")}>{panel === "application" ? "收起投递记录" : "投递记录"}</Button>
          <Button size="xs" variant="subtle" leftSection={<IconTarget size={14} />} loading={matchLoading} onClick={() => { openDetail("match"); if (matchAnalysis) void analyzeMatch(); }}>{matchAnalysis ? "重新分析匹配" : "匹配分析"}</Button>
          <Button size="xs" variant="subtle" leftSection={<IconSearch size={14} />} disabled={!job.company_name} onClick={() => openDetail("research")}>公司研究</Button>
          {job.source_type === "agent" && <Button size="xs" variant="subtle" leftSection={<IconFileText size={14} />} loading={evidenceLoading} onClick={() => openDetail("evidence")}>抽取依据</Button>}
          <Button size="xs" variant="subtle" color="gray" onClick={() => { setDetailsOpen((open) => !open); setDetailTab("details"); }}>{detailsOpen ? "收起详情" : "岗位详情"}</Button>
        </Group>
        <Feedback error={error} notice={notice} />
        {busy && <Text size="sm" c="dimmed" role="status">正在保存…</Text>}
        <Collapse transitionDuration={0} keepMounted={false} in={panel === "edit"}>
          <Stack id={`job-edit-${job.id}`} gap="md"><Divider /><Title order={4} size="sm">编辑岗位</Title><JobEditor key={job.id} job={job} onCancel={() => setPanel(null)} onSave={async (payload) => { setBusy(true); try { await onSave(job, payload); setPanel(null); setNotice("岗位信息已保存。"); } finally { setBusy(false); } }} /></Stack>
        </Collapse>
        <Collapse transitionDuration={0} keepMounted={false} in={panel === "application"}>
          <Stack id={`job-progress-${job.id}`} gap="md"><Divider /><Title order={4} size="sm">投递记录</Title><ApplicationEditor {...props} onUpdateApplication={async (selected, update) => { setBusy(true); try { await onUpdateApplication(selected, update); } finally { setBusy(false); } }} onSaved={() => { setPanel(null); setNotice("投递记录已保存。"); }} /></Stack>
        </Collapse>
        <Collapse transitionDuration={0} keepMounted={false} in={detailsOpen}>
          <Tabs value={detailTab} onChange={(value) => { if (value) openDetail(value); }} keepMounted={false}>
            <Tabs.List className={classes.tabsList}><Tabs.Tab value="details">岗位详情</Tabs.Tab><Tabs.Tab value="match">匹配分析</Tabs.Tab><Tabs.Tab value="research">公司研究</Tabs.Tab>{job.source_type === "agent" && <Tabs.Tab value="evidence">来源依据</Tabs.Tab>}</Tabs.List>
            <Tabs.Panel value="details" pt="md"><Stack gap="sm">
              {!hasDetails && <Text size="sm" c="dimmed">暂未补充岗位详情，可点击编辑添加。</Text>}
              <Group gap="xs">{[job.education_requirement, job.industry].filter(Boolean).map((value) => <Badge key={value} color="gray" variant="light">{value}</Badge>)}</Group>
              {job.required_skills.length > 0 && <Group gap="xs">{job.required_skills.map((skill) => <Badge key={skill} variant="outline">{skill}</Badge>)}</Group>}
              {job.tags.length > 0 && <Group gap="xs">{job.tags.map((tag) => <Badge key={tag} variant="light" color="gray">{tag}</Badge>)}</Group>}
              {job.description && <Text size="sm" className={classes.preserveText}>{job.description}</Text>}
              {job.company_notes && <Text size="sm" c="dimmed">公司备注：{job.company_notes}</Text>}
              <Group>{job.recruitment_url && <Anchor size="sm" href={job.recruitment_url} rel="noreferrer" target="_blank">招聘主页</Anchor>}{job.company_website_url && <Anchor size="sm" href={job.company_website_url} rel="noreferrer" target="_blank">公司官网</Anchor>}</Group>
            </Stack></Tabs.Panel>
            <Tabs.Panel value="match" pt="md"><Stack gap="md" aria-label="岗位匹配分析">
              {matchLoading && <LoadingState />}
              {matchAnalysis && <>
                <Text size="xs" c="dimmed">依据：{matchAnalysis.resume_filename}</Text>
                {matchAnalysis.criteria.map((criterion) => <Group key={criterion.key} align="flex-start" wrap="nowrap"><Badge variant="light" color={criterion.status === "meets" ? "teal" : criterion.status === "does_not_meet" ? "red" : "yellow"} className={classes.noShrink}>{criterion.status === "meets" ? "符合" : criterion.status === "does_not_meet" ? "不符合" : "待确认"}</Badge><Stack gap={3}><Text fw={600} size="sm">{criterion.label} <Text component="span" size="xs" c="dimmed">{criterion.category === "hard_requirement" ? "硬性要求" : "偏好"}</Text></Text><Text size="sm">{criterion.explanation}</Text>{(criterion.requirement || criterion.candidate_value) && <Text size="xs" c="dimmed">岗位：{criterion.requirement || "未填写"}；你的档案：{criterion.candidate_value || "未填写"}</Text>}</Stack></Group>)}
                {matchAnalysis.skills.length > 0 && <><Divider label="岗位技能要求" />{matchAnalysis.skills.map((skill) => <Stack key={skill.skill} gap={4}><Group><Text size="sm" fw={600}>{skill.skill}</Text><Badge color={skill.status === "evidenced" ? "teal" : "gray"} variant="light">{skill.status === "evidenced" ? "简历/档案有记录" : "资料中未找到"}</Badge></Group>{skill.evidence && <Blockquote p="sm" fz="sm">{skill.evidence}</Blockquote>}</Stack>)}</>}
                <Alert variant="light" color="gray">{matchAnalysis.disclaimer}</Alert>
              </>}
            </Stack></Tabs.Panel>
            <Tabs.Panel value="research" pt="md"><Stack gap="md" id={`job-research-${job.id}`} aria-label="公司公开信息研究">
              {researchLoading && <LoadingState />}<Feedback error={researchError} />
              {!researchLoading && !research && <><Text size="sm" c="dimmed">搜索公开招聘页面和公司信息。结果保留来源链接，请通过官网核验。</Text><Button onClick={() => void runCompanyResearch()} disabled={!job.company_name}>开始公司研究</Button></>}
              {research && <>
                <Text size="sm">{research.summary}</Text><Text size="xs" c="dimmed">搜索时间：{new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(research.researched_at))}</Text><Text size="xs" c="dimmed">搜索词：{research.query}</Text>
                {research.is_stale && <Alert color="yellow">该结果已超过 7 天，招聘信息可能变化，请重新搜索或打开来源核验。</Alert>}
                {research.warning && <Alert color="yellow">{research.warning}</Alert>}
                {research.findings.map((finding, index) => { const source = research.sources.find((item) => item.source_id === finding.source_id); return <Stack key={`${finding.source_id}-${index}`} gap="xs"><Text fw={600} size="sm">{finding.claim}</Text><Blockquote p="sm" fz="sm">{finding.quote}</Blockquote>{source && <Anchor size="sm" href={source.url} target="_blank" rel="noreferrer">来源：{source.title}</Anchor>}</Stack>; })}
                <Accordion variant="separated"><Accordion.Item value="sources"><Accordion.Control>查看全部搜索来源（{research.sources.length}）</Accordion.Control><Accordion.Panel><Stack>{research.sources.length === 0 && <Text size="sm">搜索服务没有返回来源。</Text>}{research.sources.map((source) => <Stack key={source.source_id} gap={4}><Anchor size="sm" href={source.url} rel="noreferrer" target="_blank">{source.title}</Anchor>{source.age && <Text size="xs" c="dimmed">{source.age}</Text>}<Text size="sm">{source.excerpt}</Text></Stack>)}</Stack></Accordion.Panel></Accordion.Item></Accordion>
                <Button variant="default" loading={researchLoading} onClick={() => void runCompanyResearch()}>重新搜索</Button>
              </>}
            </Stack></Tabs.Panel>
            {job.source_type === "agent" && <Tabs.Panel value="evidence" pt="md"><Stack gap="md" aria-label="岗位字段抽取依据"><Feedback error={evidenceError} />{evidenceLoading && <LoadingState />}{sourceEvidence && <>
              <Title order={4} size="sm">字段来源依据</Title>
              {Object.entries(sourceEvidence.field_evidence).map(([field, item]) => <Stack key={field} gap={4}><Group><Text fw={600} size="sm">{({ company_name: "公司", title: "职位", city: "地点", job_type: "岗位类型", batch: "招聘批次", deadline: "截止日期", education_requirement: "学历要求", required_skills: "技能" } as Record<string, string>)[field] ?? field}</Text><Badge variant="light" color="gray">置信度 {Math.round(item.confidence * 100)}%</Badge></Group><Text size="sm">{Array.isArray(item.value) ? item.value.join("、") : item.value || "未提取"}</Text>{item.evidence && <Blockquote p="sm" fz="sm">{item.evidence}</Blockquote>}</Stack>)}
              <Accordion variant="separated"><Accordion.Item value="raw"><Accordion.Control>查看保存的招聘原文</Accordion.Control><Accordion.Panel><Text component="pre" size="sm" className={classes.preserveText}>{sourceEvidence.source_text}</Text></Accordion.Panel></Accordion.Item></Accordion>
            </>}</Stack></Tabs.Panel>}
          </Tabs>
        </Collapse>
      </Stack>
    </Paper>
  );
}
