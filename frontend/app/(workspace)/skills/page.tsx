"use client";

import Link from "next/link";
import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Blockquote,
  Button,
  CopyButton,
  Divider,
  Group,
  List,
  Paper,
  Select,
  Stack,
  Tabs,
  Text,
  Textarea,
  Timeline,
  Title,
  UnstyledButton,
} from "@mantine/core";
import {
  IconCheck,
  IconCopy,
  IconFileText,
  IconHistory,
  IconPlayerPlay,
  IconShieldCheck,
} from "@tabler/icons-react";
import {
  EmptyState,
  Feedback,
  LoadingState,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import { useConfirm } from "@/lib/use-confirm";
import classes from "../agent/agent.module.css";
import {
  ApiError,
  apiRequest,
  type ApplicationPrepPack,
  type JobPosting,
  type SkillApproval,
  type SkillAuditEvent,
  type SkillCatalogItem,
  type SkillId,
  type SkillDraft,
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
  return (
    [job.company_name, job.title].filter(Boolean).join(" · ") || "未命名岗位"
  );
}

function DraftContent({ draft }: { draft: SkillDraft }) {
  return (
    <Stack gap="lg">
      <Text size="sm" fw={500}>
        {draft.summary}
      </Text>
      {draft.warnings.map((warning) => (
        <Alert key={warning} color="orange">
          {warning}
        </Alert>
      ))}
      {draft.checklist.length > 0 && (
        <section>
          <Title order={4} size="h5" mb="sm">
            材料与准备清单
          </Title>
          <Stack gap="sm">
            {draft.checklist.map((item, index) => (
              <Group key={`${item.title}-${index}`} wrap="nowrap" align="start">
                <IconCheck size={18} />
                <div>
                  <Text size="sm" fw={600}>
                    {item.title}
                  </Text>
                  <Text size="sm" c="dimmed">
                    {item.reason}
                  </Text>
                  <Text size="xs" c="dimmed">
                    需要你确认
                  </Text>
                </div>
              </Group>
            ))}
          </Stack>
        </section>
      )}
      {draft.sections.map((section, index) => (
        <section key={`${section.title}-${index}`}>
          <Divider mb="lg" />
          <Stack gap="sm">
            <Group justify="space-between">
              <Group gap="sm">
                <Title order={4} size="h5">
                  {section.title}
                </Title>
                {section.needs_user_input && (
                  <Badge color="orange" size="xs">
                    需要补充 / 核对
                  </Badge>
                )}
              </Group>
              <CopyButton value={section.content}>
                {({ copied, copy }) => (
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={copy}
                    leftSection={
                      copied ? <IconCheck size={14} /> : <IconCopy size={14} />
                    }
                  >
                    {copied ? "已复制" : "复制"}
                  </Button>
                )}
              </CopyButton>
            </Group>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {section.content}
            </Text>
            {section.citations.map((citation, citationIndex) => (
              <Blockquote
                key={`${citation.source_id}-${citationIndex}`}
                cite={
                  <Group gap="xs">
                    <Text span size="xs">
                      {citation.source_label}
                    </Text>
                    {citation.source_url && (
                      <Anchor
                        href={citation.source_url}
                        target="_blank"
                        rel="noreferrer"
                        size="xs"
                      >
                        打开来源
                      </Anchor>
                    )}
                  </Group>
                }
                p="md"
                color="teal"
              >
                <Text size="sm">{citation.quote}</Text>
              </Blockquote>
            ))}
          </Stack>
        </section>
      ))}
      {draft.open_questions.length > 0 && (
        <section>
          <Title order={4} size="h5" mb="sm">
            需要你补充的问题
          </Title>
          <List size="sm" spacing="xs">
            {draft.open_questions.map((question, index) => (
              <List.Item key={`${question}-${index}`}>{question}</List.Item>
            ))}
          </List>
        </section>
      )}
    </Stack>
  );
}

export default function SkillsPage() {
  const confirm = useConfirm();
  const [workspaceTab, setWorkspaceTab] = useState<string | null>("runs");
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
  const [initialized, setInitialized] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  const jobsById = useMemo(
    () => new Map(jobs.map((job) => [job.id, job])),
    [jobs],
  );
  const activeSkill = skills.find((skill) => skill.id === skillId);
  const activeRun = runs.find((run) => run.id === activeRunId) ?? runs[0];
  const latestRunApproval = approvals.find(
    (approval) => approval.agent_run_id === activeRun?.id,
  );
  const activeApproval = approvals.find(
    (approval) =>
      approval.agent_run_id === activeRun?.id &&
      ["pending", "approved"].includes(approval.status) &&
      new Date(approval.expires_at).getTime() > Date.now(),
  );
  const canRequestApproval =
    activeRun?.skill_id === "application_prep_pack" &&
    activeRun.status === "succeeded" &&
    !activeApproval &&
    (!latestRunApproval || latestRunApproval.status === "expired");
  const hasQuestionInput =
    skillId === "application_answers" || skillId === "application_prep_pack";
  const usesResume = [
    "resume_targeting",
    "application_answers",
    "interview_prep",
    "application_prep_pack",
  ].includes(skillId);

  const loadWorkspace = useCallback(async () => {
    const results = await Promise.allSettled([
      apiRequest<SkillCatalogItem[]>("/api/v1/skills"),
      apiRequest<JobPosting[]>("/api/v1/jobs"),
      apiRequest<SkillRun[]>("/api/v1/skills/runs?limit=20"),
      apiRequest<SkillApproval[]>("/api/v1/skills/approvals"),
      apiRequest<ApplicationPrepPack[]>("/api/v1/skills/packs?limit=50"),
      apiRequest<SkillAuditEvent[]>("/api/v1/skills/audit?limit=50"),
    ]);
    const [
      skillResult,
      jobResult,
      runResult,
      approvalResult,
      packResult,
      auditResult,
    ] = results;
    if (skillResult.status === "fulfilled") setSkills(skillResult.value);
    if (jobResult.status === "fulfilled") setJobs(jobResult.value);
    if (runResult.status === "fulfilled") setRuns(runResult.value);
    if (approvalResult.status === "fulfilled")
      setApprovals(approvalResult.value);
    if (packResult.status === "fulfilled") setPacks(packResult.value);
    if (auditResult.status === "fulfilled") setAuditEvents(auditResult.value);
    const failure = results.find((result) => result.status === "rejected");
    if (failure?.status === "rejected") {
      setError(
        failure.reason instanceof Error
          ? failure.reason.message
          : "无法载入求职工作流。",
      );
      setRequiresLogin(
        failure.reason instanceof ApiError && failure.reason.status === 401,
      );
    } else {
      setInitialized(true);
      setError("");
      setRequiresLogin(false);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    const hasActiveRun = runs.some((run) =>
      ["queued", "running", "cancelling"].includes(run.status),
    );
    if (!hasActiveRun) return;
    const timer = window.setInterval(() => {
      void apiRequest<SkillRun[]>("/api/v1/skills/runs?limit=20")
        .then(setRuns)
        .catch((cause) =>
          setError(
            cause instanceof Error ? cause.message : "无法刷新任务状态。",
          ),
        );
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
    const questions = questionText
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean);
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
      setWorkspaceTab("runs");
      setRuns((current) => [
        run,
        ...current.filter((item) => item.id !== run.id),
      ]);
      setNotice(
        "任务已创建。结果会先作为草稿展示，不会自动修改投递状态或提交到招聘网站。",
      );
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
      const updated = await apiRequest<SkillRun>(
        `/api/v1/skills/runs/${run.id}/${action}`,
        {
          method: "POST",
        },
      );
      setActiveRunId(updated.id);
      setRuns((current) => [
        updated,
        ...current.filter((item) => item.id !== updated.id),
      ]);
      setNotice(
        action === "retry"
          ? "已安排任务重试。"
          : updated.status === "cancelling"
            ? "已请求取消；模型响应完成后会丢弃结果。"
            : "任务已取消。模型结果不会保存。",
      );
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
      const approval = await apiRequest<SkillApproval>(
        `/api/v1/skills/runs/${run.id}/approval`,
        {
          method: "POST",
        },
      );
      setApprovals((current) => [
        approval,
        ...current.filter((item) => item.id !== approval.id),
      ]);
      setNotice("审批已创建。请核对具体操作后，再批准并保存到本地工作台。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法创建审批请求。");
    } finally {
      setWorking(false);
    }
  }

  async function executeSave(approval: SkillApproval) {
    if (
      !(await confirm({
        title: "确认执行本地保存",
        confirmLabel: "确认保存",
        message: `${approval.summary}\n\n确认后只保存到 OfferPilot，不会提交招聘网站。`,
      }))
    )
      return;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const pack = await apiRequest<ApplicationPrepPack>(
        `/api/v1/skills/approvals/${approval.id}/execute`,
        {
          method: "POST",
        },
      );
      setPacks((current) => [
        pack,
        ...current.filter((item) => item.id !== pack.id),
      ]);
      setNotice("申请准备包已保存。你仍需自行核对内容并复制到招聘网站。");
      await loadWorkspace();
    } catch (cause) {
      await loadWorkspace();
      setError(cause instanceof Error ? cause.message : "保存申请准备包失败。");
    } finally {
      setWorking(false);
    }
  }

  async function rejectApproval(approval: SkillApproval) {
    setWorking(true);
    setError("");
    try {
      const rejected = await apiRequest<SkillApproval>(
        `/api/v1/skills/approvals/${approval.id}/reject`,
        {
          method: "POST",
        },
      );
      setApprovals((current) =>
        current.map((item) => (item.id === rejected.id ? rejected : item)),
      );
      setNotice("审批已拒绝，没有保存准备包。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法拒绝审批。");
    } finally {
      setWorking(false);
    }
  }

  async function approveApproval(approval: SkillApproval) {
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const approved = await apiRequest<SkillApproval>(
        `/api/v1/skills/approvals/${approval.id}/approve`,
        { method: "POST" },
      );
      setApprovals((current) =>
        current.map((item) => (item.id === approved.id ? approved : item)),
      );
      setNotice("操作已批准。准备包尚未保存，请点击确认执行本地保存。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批准操作失败。");
    } finally {
      setWorking(false);
    }
  }

  return (
    <Stack gap="xl">
      <PageHeader
        title="求职 Skills"
        description="用有版本、有引用的工作流准备材料，让每份草稿都有依据。"
        actions={
          <Button
            variant="default"
            onClick={() => void loadWorkspace()}
            loading={loading}
          >
            刷新工作区
          </Button>
        }
      />
      <Feedback error={error} notice={notice} requiresLogin={requiresLogin} />
      {!loading && !initialized && !requiresLogin && (
        <Button
          variant="light"
          w="fit-content"
          onClick={() => void loadWorkspace()}
        >
          重新载入
        </Button>
      )}
      {loading ? (
        <LoadingState />
      ) : initialized ? (
        <div className={classes.grid}>
          <Paper
            withBorder
            p="xl"
            radius="lg"
            className={`${classes.panel} ${classes.sticky}`}
          >
            <Stack gap="lg">
              <Group justify="space-between">
                <Title order={2} size="h3">
                  配置任务
                </Title>
                {activeSkill && (
                  <Badge variant="light">v{activeSkill.version}</Badge>
                )}
              </Group>
              <form onSubmit={createRun}>
                <Stack gap="md">
                  <Select
                    label="求职 Skill"
                    value={skillId}
                    onChange={(value) =>
                      value && updateInput(() => setSkillId(value as SkillId))
                    }
                    data={skills.map((skill) => ({
                      value: skill.id,
                      label: skill.name,
                    }))}
                    allowDeselect={false}
                  />
                  {activeSkill && (
                    <Text size="sm" c="dimmed">
                      {activeSkill.description}
                    </Text>
                  )}
                  <Select
                    label="目标岗位"
                    required
                    searchable
                    value={jobId || null}
                    onChange={(value) =>
                      updateInput(() => setJobId(value || ""))
                    }
                    data={jobs.map((job) => ({
                      value: job.id,
                      label: jobLabel(job),
                    }))}
                    placeholder="选择一个已保存岗位"
                  />
                  {hasQuestionInput && (
                    <Textarea
                      label="申请问题"
                      description="每行一个真实问题；申请问答 Skill 必填，申请准备包可留空"
                      maxLength={8000}
                      minRows={4}
                      autosize
                      value={questionText}
                      onChange={(event) =>
                        updateInput(() =>
                          setQuestionText(event.currentTarget.value),
                        )
                      }
                      placeholder="例如：请介绍一次你用数据解决问题的经历。"
                    />
                  )}
                  {usesResume && (
                    <Alert color="gray">
                      此 Skill
                      可能读取你最新的已确认简历和个人档案，并发送给服务端配置的模型服务以生成草稿。岗位描述和公开研究片段也会作为不可信资料；请检查服务提供方的隐私政策。
                    </Alert>
                  )}
                  {!jobs.length && (
                    <Text size="sm" c="dimmed">
                      还没有可用岗位。
                      <Anchor component={Link} href="/jobs">
                        先添加岗位
                      </Anchor>
                    </Text>
                  )}
                  <Button
                    type="submit"
                    loading={working}
                    disabled={!jobs.length}
                    leftSection={<IconPlayerPlay size={17} />}
                  >
                    生成可检查草稿
                  </Button>
                  <Text size="xs" c="dimmed">
                    当前运行最多 3 次；草稿不会自动改动业务记录。
                  </Text>
                </Stack>
              </form>
              {activeSkill && (
                <Accordion variant="default">
                  <Accordion.Item value="boundaries">
                    <Accordion.Control>运行边界</Accordion.Control>
                    <Accordion.Panel>
                      <List size="xs" spacing="sm">
                        {activeSkill.boundaries.map((boundary) => (
                          <List.Item key={boundary}>{boundary}</List.Item>
                        ))}
                      </List>
                    </Accordion.Panel>
                  </Accordion.Item>
                  <Accordion.Item value="contract">
                    <Accordion.Control>输入 / 输出与模板示例</Accordion.Control>
                    <Accordion.Panel>
                      <Stack gap="md">
                        {[
                          ["输入", activeSkill.inputs],
                          ["输出", activeSkill.outputs],
                          ["输入示例", activeSkill.example_input],
                          ["输出示例", activeSkill.example_output],
                        ].map(([label, value]) => (
                          <div key={String(label)}>
                            <Text size="xs" fw={600} mb="xs">
                              {String(label)}
                            </Text>
                            <Text component="pre" className={classes.pre}>
                              {JSON.stringify(value, null, 2)}
                            </Text>
                          </div>
                        ))}
                      </Stack>
                    </Accordion.Panel>
                  </Accordion.Item>
                </Accordion>
              )}
            </Stack>
          </Paper>
          <div className={classes.panel}>
            <Tabs
              value={workspaceTab}
              onChange={setWorkspaceTab}
              keepMounted={false}
            >
              <Tabs.List mb="lg">
                <Tabs.Tab
                  value="runs"
                  leftSection={<IconPlayerPlay size={16} />}
                >
                  运行与草稿
                </Tabs.Tab>
                <Tabs.Tab
                  value="packs"
                  leftSection={<IconFileText size={16} />}
                >
                  已保存材料
                </Tabs.Tab>
                <Tabs.Tab value="audit" leftSection={<IconHistory size={16} />}>
                  操作审计
                </Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="runs">
                <Stack gap="lg">
                  {!runs.length ? (
                    <EmptyState
                      title="尚无 Skill 运行记录"
                      description="选择岗位和模板，开始准备第一份草稿。"
                    />
                  ) : (
                    <>
                      <Paper withBorder radius="lg" p="sm">
                        <Accordion variant="default" defaultValue="recent">
                          <Accordion.Item value="recent">
                            <Accordion.Control>
                              最近的 Agent 任务（{runs.length}）
                            </Accordion.Control>
                            <Accordion.Panel>
                              <Stack gap="xs">
                                {runs.map((run) => (
                                  <UnstyledButton
                                    key={run.id}
                                    className={`${classes.listButton} ${activeRun?.id === run.id ? classes.selected : ""}`}
                                    aria-pressed={activeRun?.id === run.id}
                                    onClick={() => setActiveRunId(run.id)}
                                  >
                                    <Group
                                      justify="space-between"
                                      wrap="nowrap"
                                    >
                                      <div className={classes.break}>
                                        <Text size="sm" fw={600}>
                                          {skills.find(
                                            (item) => item.id === run.skill_id,
                                          )?.name || run.skill_id}
                                        </Text>
                                        <Text size="xs" c="dimmed">
                                          {jobLabel(jobsById.get(run.job_id))} /
                                          v{run.skill_version}
                                        </Text>
                                      </div>
                                      <StatusBadge
                                        status={run.status}
                                        label={STATUS_LABELS[run.status]}
                                      />
                                    </Group>
                                  </UnstyledButton>
                                ))}
                              </Stack>
                            </Accordion.Panel>
                          </Accordion.Item>
                        </Accordion>
                      </Paper>
                      {activeRun && (
                        <Paper withBorder p="xl" radius="lg">
                          <Stack gap="lg">
                            <Group justify="space-between" align="flex-start">
                              <div>
                                <Title order={2} size="h3">
                                  {skills.find(
                                    (item) => item.id === activeRun.skill_id,
                                  )?.name || activeRun.skill_id}
                                </Title>
                                <Text size="sm" c="dimmed" mt={4}>
                                  {jobLabel(jobsById.get(activeRun.job_id))} / v
                                  {activeRun.skill_version}
                                </Text>
                              </div>
                              <StatusBadge
                                status={activeRun.status}
                                label={STATUS_LABELS[activeRun.status]}
                              />
                            </Group>
                            {activeRun.error_message && (
                              <Alert color="red" title="任务未完成">
                                <Stack gap="sm">
                                  <Text size="sm">
                                    {activeRun.error_message}
                                  </Text>
                                  {activeRun.status === "failed" &&
                                    activeRun.attempt_count < 3 && (
                                      <Button
                                        variant="light"
                                        loading={working}
                                        onClick={() =>
                                          void runAction(activeRun, "retry")
                                        }
                                      >
                                        重试任务
                                      </Button>
                                    )}
                                </Stack>
                              </Alert>
                            )}
                            {activeRun.status === "cancelling" && (
                              <Alert color="orange">
                                正在等待当前模型请求结束；返回内容不会保存。
                              </Alert>
                            )}
                            {(activeRun.status === "queued" ||
                              activeRun.status === "running") && (
                              <Button
                                variant="default"
                                disabled={working}
                                onClick={() =>
                                  void runAction(activeRun, "cancel")
                                }
                              >
                                取消任务
                              </Button>
                            )}
                            {activeRun.events.length > 0 && (
                              <Accordion
                                variant="default"
                                defaultValue={
                                  activeRun.status === "running" ||
                                  activeRun.status === "queued"
                                    ? "progress"
                                    : undefined
                                }
                              >
                                <Accordion.Item value="progress">
                                  <Accordion.Control>
                                    运行进度
                                  </Accordion.Control>
                                  <Accordion.Panel>
                                    <Timeline
                                      active={activeRun.events.length - 1}
                                      bulletSize={16}
                                      lineWidth={2}
                                    >
                                      {activeRun.events.map((event) => (
                                        <Timeline.Item
                                          key={`${activeRun.id}-${event.id}`}
                                          title={
                                            <Text size="sm">
                                              {event.message}
                                            </Text>
                                          }
                                        >
                                          <Text size="xs" c="dimmed">
                                            {new Date(
                                              event.created_at,
                                            ).toLocaleTimeString("zh-CN", {
                                              hour: "2-digit",
                                              minute: "2-digit",
                                            })}
                                          </Text>
                                        </Timeline.Item>
                                      ))}
                                    </Timeline>
                                  </Accordion.Panel>
                                </Accordion.Item>
                              </Accordion>
                            )}
                            {activeRun.result && (
                              <DraftContent draft={activeRun.result} />
                            )}
                            {activeRun.result &&
                              activeRun.skill_id === "application_answers" && (
                                <Button
                                  component={Link}
                                  href={`/actions?skill_run_id=${activeRun.id}`}
                                  variant="light"
                                >
                                  把申请问答草稿载入外部邮件审批
                                </Button>
                              )}
                            {activeRun.result &&
                              activeRun.skill_id ===
                                "application_prep_pack" && (
                                <>
                                  <Divider />
                                  <Stack gap="md">
                                    {canRequestApproval && (
                                      <Button
                                        variant="light"
                                        loading={working}
                                        onClick={() =>
                                          void requestApproval(activeRun)
                                        }
                                        leftSection={
                                          <IconShieldCheck size={16} />
                                        }
                                      >
                                        {latestRunApproval
                                          ? "重新申请保存审批"
                                          : "申请保存到工作台"}
                                      </Button>
                                    )}
                                    {activeApproval && (
                                      <Alert
                                        color="teal"
                                        title={
                                          activeApproval.status === "pending"
                                            ? "待确认操作"
                                            : "已批准，尚未写入"
                                        }
                                      >
                                        <Stack gap="sm">
                                          <Text size="sm">
                                            {activeApproval.summary}
                                          </Text>
                                          <Text size="xs">
                                            审批有效期至{" "}
                                            {new Date(
                                              activeApproval.expires_at,
                                            ).toLocaleString("zh-CN")}
                                          </Text>
                                          <Group>
                                            {activeApproval.status ===
                                            "pending" ? (
                                              <Button
                                                loading={working}
                                                onClick={() =>
                                                  void approveApproval(
                                                    activeApproval,
                                                  )
                                                }
                                              >
                                                核对后批准
                                              </Button>
                                            ) : (
                                              <Button
                                                loading={working}
                                                onClick={() =>
                                                  void executeSave(
                                                    activeApproval,
                                                  )
                                                }
                                              >
                                                确认执行本地保存
                                              </Button>
                                            )}
                                            {activeApproval.status ===
                                              "pending" && (
                                              <Button
                                                variant="default"
                                                disabled={working}
                                                onClick={() =>
                                                  void rejectApproval(
                                                    activeApproval,
                                                  )
                                                }
                                              >
                                                拒绝
                                              </Button>
                                            )}
                                          </Group>
                                        </Stack>
                                      </Alert>
                                    )}
                                    {latestRunApproval && !activeApproval && (
                                      <Text size="sm" c="dimmed">
                                        {latestRunApproval.status === "expired"
                                          ? "审批已过期，可重新申请。"
                                          : latestRunApproval.status ===
                                              "rejected"
                                            ? "审批已拒绝；如仍需保存，请重新运行申请准备包。"
                                            : latestRunApproval.status ===
                                                "invalidated"
                                              ? "草稿或目标变化导致审批失效；请重新运行 Skill 生成新草稿。"
                                              : APPROVAL_LABELS[
                                                  latestRunApproval.status
                                                ]}
                                      </Text>
                                    )}
                                  </Stack>
                                </>
                              )}
                          </Stack>
                        </Paper>
                      )}
                    </>
                  )}
                </Stack>
              </Tabs.Panel>
              <Tabs.Panel value="packs">
                {!packs.length ? (
                  <EmptyState
                    title="还没有已保存的申请准备包"
                    description="用户批准并执行保存后，材料会显示在这里。"
                  />
                ) : (
                  <Paper withBorder radius="lg" p="lg">
                    <Accordion>
                      {packs.map((pack) => (
                        <Accordion.Item key={pack.id} value={pack.id}>
                          <Accordion.Control>
                            <Text fw={600} size="sm">
                              {jobLabel(jobsById.get(pack.job_id))}
                            </Text>
                            <Text size="xs" c="dimmed">
                              v{pack.skill_version} /{" "}
                              {new Date(pack.created_at).toLocaleString(
                                "zh-CN",
                              )}
                            </Text>
                          </Accordion.Control>
                          <Accordion.Panel>
                            <DraftContent draft={pack.content} />
                          </Accordion.Panel>
                        </Accordion.Item>
                      ))}
                    </Accordion>
                  </Paper>
                )}
              </Tabs.Panel>
              <Tabs.Panel value="audit">
                {!auditEvents.length ? (
                  <EmptyState
                    title="还没有审计记录"
                    description="批准、拒绝和保存操作会记录在这里。"
                  />
                ) : (
                  <Paper withBorder radius="lg" p="xl">
                    <Timeline
                      active={auditEvents.length - 1}
                      bulletSize={18}
                      lineWidth={2}
                    >
                      {auditEvents.map((event) => (
                        <Timeline.Item
                          key={event.id}
                          title={
                            <Text size="sm" fw={600}>
                              {event.action}
                            </Text>
                          }
                        >
                          <Text size="xs" c="dimmed" className={classes.break}>
                            {event.entity_type} / {event.entity_id}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {new Date(event.created_at).toLocaleString("zh-CN")}
                          </Text>
                        </Timeline.Item>
                      ))}
                    </Timeline>
                  </Paper>
                )}
              </Tabs.Panel>
            </Tabs>
          </div>
        </div>
      ) : null}
    </Stack>
  );
}
