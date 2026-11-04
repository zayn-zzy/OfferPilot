"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Paper,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Timeline,
  Title,
} from "@mantine/core";
import { IconMail, IconSend, IconShieldCheck } from "@tabler/icons-react";
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
  type ExternalAction,
  type ExternalActionCapabilities,
  type JobPosting,
  type SkillRun,
} from "@/lib/api";

const STATUS_LABELS: Record<ExternalAction["status"], string> = {
  pending: "等待审批",
  approved: "已批准，等待发送",
  executing: "发送中",
  executed: "已发送",
  rejected: "已拒绝",
  expired: "已过期",
  invalidated: "审批失效",
  outcome_unknown: "发送结果待核对",
};

function labelJob(job: JobPosting | undefined) {
  if (!job) return "岗位已删除或不可用";
  return (
    [job.company_name, job.title].filter(Boolean).join(" · ") || "未命名岗位"
  );
}

export default function ExternalActionsPage() {
  const confirm = useConfirm();
  const [lastActionId, setLastActionId] = useState<string | null>(null);
  const [actions, setActions] = useState<ExternalAction[]>([]);
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [capabilities, setCapabilities] =
    useState<ExternalActionCapabilities | null>(null);
  const [recipient, setRecipient] = useState("");
  const [jobId, setJobId] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  const loadActions = useCallback(async () => {
    const results = await Promise.allSettled([
      apiRequest<ExternalAction[]>("/api/v1/external-actions"),
      apiRequest<ExternalActionCapabilities>(
        "/api/v1/external-actions/capabilities",
      ),
      apiRequest<JobPosting[]>("/api/v1/jobs"),
    ]);
    const [actionResult, capabilityResult, jobResult] = results;
    if (actionResult.status === "fulfilled") setActions(actionResult.value);
    if (capabilityResult.status === "fulfilled")
      setCapabilities(capabilityResult.value);
    if (jobResult.status === "fulfilled") setJobs(jobResult.value);
    const failure = results.find((result) => result.status === "rejected");
    if (failure?.status === "rejected") {
      setError(
        failure.reason instanceof Error
          ? failure.reason.message
          : "无法载入外部动作。",
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
    void loadActions();
  }, [loadActions]);

  const hasExecutingAction = actions.some(
    (action) => action.status === "executing",
  );
  useEffect(() => {
    if (!hasExecutingAction) return;
    const timer = window.setInterval(() => void loadActions(), 1500);
    return () => window.clearInterval(timer);
  }, [hasExecutingAction, loadActions]);

  useEffect(() => {
    const runId = new URLSearchParams(window.location.search).get(
      "skill_run_id",
    );
    if (!runId) return;
    apiRequest<SkillRun[]>("/api/v1/skills/runs?limit=20")
      .then((runs) => {
        const run = runs.find(
          (item) => item.id === runId && item.status === "succeeded",
        );
        if (!run?.result || run.skill_id !== "application_answers") {
          setError("找不到可用的申请问答草稿，请回 Skills 页面检查任务状态。");
          return;
        }
        const sections = run.result.sections.map(
          (section) => section.title + "\n" + section.content,
        );
        const draft = [run.result.summary, ...sections]
          .filter(Boolean)
          .join("\n\n");
        setJobId(run.job_id);
        setBody(draft.slice(0, 20_000));
        setSubject("求职申请问题回复草稿");
        setNotice(
          "已载入 Agent 生成的申请问答草稿。请逐句核对并补充真实信息，再创建审批；尚未发送。",
        );
      })
      .catch((cause) =>
        setError(
          cause instanceof Error ? cause.message : "无法载入 Agent 草稿。",
        ),
      );
  }, []);

  function markDraftChanged() {
    idempotencyKey.current = null;
  }

  async function createAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!capabilities?.email_send_enabled) {
      setError("邮件执行器未配置，请先设置服务端 SMTP 环境变量。");
      return;
    }
    setWorking(true);
    setLastActionId(null);
    setError("");
    setNotice("");
    idempotencyKey.current ??= window.crypto.randomUUID();
    try {
      const action = await apiRequest<ExternalAction>(
        "/api/v1/external-actions",
        {
          method: "POST",
          body: JSON.stringify({
            recipient,
            job_id: jobId || null,
            subject,
            body,
            idempotency_key: idempotencyKey.current,
          }),
        },
      );
      setActions((current) => [
        action,
        ...current.filter((item) => item.id !== action.id),
      ]);
      setNotice(
        "邮件已保存为待审批动作，尚未发送。请核对完整收件人、主题和正文。",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法创建邮件审批。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setWorking(false);
    }
  }

  async function runAction(
    action: ExternalAction,
    operation: "approve" | "reject" | "execute",
  ) {
    if (operation === "execute") {
      const confirmed = await confirm({
        title: "最终确认并发送邮件",
        confirmLabel: "确认发送",
        message: (
          <Stack gap="sm">
            <Text>邮件发送后可能无法撤回。请最后核对完整内容。</Text>
            <Text fw={600}>收件人：{action.target}</Text>
            <Text fw={600}>主题：{action.payload.subject}</Text>
            <Divider />
            <Text component="pre" className={classes.pre}>
              {action.payload.body}
            </Text>
          </Stack>
        ),
      });
      if (!confirmed) return;
    }
    setWorking(true);
    setLastActionId(action.id);
    setError("");
    setNotice("");
    try {
      const updated = await apiRequest<ExternalAction>(
        "/api/v1/external-actions/" + action.id + "/" + operation,
        { method: "POST" },
      );
      setActions((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice(
        operation === "approve"
          ? "动作已批准。邮件仍未发送，需要再次点击发送并确认。"
          : operation === "reject"
            ? "动作已拒绝，没有发送邮件。"
            : "邮件服务已接受发送请求。请检查邮件账户中的已发送记录。",
      );
    } catch (cause) {
      await loadActions();
      setError(cause instanceof Error ? cause.message : "外部动作执行失败。");
    } finally {
      setWorking(false);
    }
  }

  return (
    <Stack gap="xl">
      <PageHeader
        title="外部动作"
        description="核对每一封邮件，通过审批后由你最终确认发送。"
        actions={
          <Badge variant="light" leftSection={<IconShieldCheck size={14} />}>
            逐项审批
          </Badge>
        }
      />
      <Feedback error={error} notice={notice} requiresLogin={requiresLogin} />
      {loading && <LoadingState />}
      {!loading && !initialized && !requiresLogin && (
        <Button
          variant="light"
          w="fit-content"
          onClick={() => void loadActions()}
        >
          重新载入
        </Button>
      )}
      {!loading && initialized && (
        <>
          <div className={classes.equalGrid}>
            <Paper withBorder p="xl" radius="lg" className={classes.panel}>
              <Stack gap="lg">
                <Group justify="space-between">
                  <Title order={2} size="h3">
                    撰写邮件
                  </Title>
                  <Badge
                    color={capabilities?.email_send_enabled ? "teal" : "orange"}
                  >
                    {capabilities?.email_send_enabled
                      ? "SMTP 已配置"
                      : "SMTP 未配置"}
                  </Badge>
                </Group>
                {!capabilities?.email_send_enabled && (
                  <Alert color="orange" title="邮件服务尚未启用">
                    部署者需要配置 SMTP 服务。配置完成后重启
                    API，即可创建和执行邮件动作。
                  </Alert>
                )}
                <form onSubmit={createAction}>
                  <Stack gap="md">
                    <Select
                      label="关联岗位（选填）"
                      searchable
                      clearable
                      value={jobId || null}
                      onChange={(value) => {
                        markDraftChanged();
                        setJobId(value || "");
                      }}
                      data={jobs.map((job) => ({
                        value: job.id,
                        label: labelJob(job),
                      }))}
                      placeholder="不关联岗位"
                    />
                    <TextInput
                      label="收件人邮箱"
                      autoComplete="email"
                      required
                      type="email"
                      maxLength={320}
                      value={recipient}
                      onChange={(event) => {
                        markDraftChanged();
                        setRecipient(event.currentTarget.value);
                      }}
                      placeholder="recruiter@example.com"
                    />
                    <TextInput
                      label="邮件主题"
                      required
                      maxLength={200}
                      value={subject}
                      onChange={(event) => {
                        markDraftChanged();
                        setSubject(event.currentTarget.value);
                      }}
                      placeholder="应聘后端开发工程师 - 张同学"
                    />
                    <Textarea
                      label="邮件正文"
                      required
                      maxLength={20000}
                      minRows={9}
                      autosize
                      value={body}
                      onChange={(event) => {
                        markDraftChanged();
                        setBody(event.currentTarget.value);
                      }}
                      placeholder="粘贴并核对邮件正文"
                    />
                    <Button
                      type="submit"
                      loading={working}
                      disabled={!capabilities?.email_send_enabled}
                      leftSection={<IconShieldCheck size={17} />}
                    >
                      创建待审批邮件
                    </Button>
                    <Text size="xs" c="dimmed">
                      创建只保存待审批记录，不会发送邮件；审批 15 分钟后过期。
                    </Text>
                  </Stack>
                </form>
              </Stack>
            </Paper>
            <Paper withBorder p="xl" radius="lg" className={classes.panel}>
              <Stack gap="lg">
                <Group gap="sm">
                  <IconMail size={20} />
                  <Title order={2} size="h3">
                    邮件预览
                  </Title>
                </Group>
                <Text size="sm" c="dimmed">
                  收件人
                </Text>
                <Text className={classes.break}>
                  {recipient || "填写收件人后显示"}
                </Text>
                <Divider />
                <Title order={3} size="h4">
                  {subject || "邮件主题"}
                </Title>
                <Text component="pre" className={classes.pre}>
                  {body || "在左侧撰写正文，完整内容将在这里同步显示。"}
                </Text>
                <Alert variant="light" color="gray">
                  邮件内容和收件人会发送给服务端配置的 SMTP
                  服务。请检查事实、附件说明与收件地址。
                </Alert>
              </Stack>
            </Paper>
          </div>
          <Stack gap="md">
            <Group justify="space-between">
              <Title order={2} size="h3">
                外部动作记录
              </Title>
              <Button variant="subtle" onClick={() => void loadActions()}>
                刷新记录
              </Button>
            </Group>
            {actions.length === 0 ? (
              <EmptyState
                title="目前没有外部动作记录"
                description="创建邮件后，审批与发送状态会保存在这里。"
              />
            ) : (
              actions.map((action) => (
                <Paper withBorder radius="lg" p="xl" key={action.id}>
                  <Stack gap="md">
                    <Group justify="space-between" align="flex-start">
                      <div>
                        <Title order={3} size="h4">
                          {action.payload.subject}
                        </Title>
                        <Text size="sm" c="dimmed" mt={4}>
                          {action.job_id
                            ? labelJob(
                                jobs.find((job) => job.id === action.job_id),
                              )
                            : "未关联岗位"}
                        </Text>
                      </div>
                      <StatusBadge
                        status={action.status}
                        label={STATUS_LABELS[action.status]}
                      />
                    </Group>
                    <Text size="sm">
                      <Text span fw={600}>
                        收件人：
                      </Text>
                      {action.target}
                    </Text>
                    <Text size="sm" c="dimmed">
                      {action.summary}
                    </Text>
                    <Text component="pre" className={classes.pre}>
                      {action.payload.body}
                    </Text>
                    <Timeline
                      active={
                        action.status === "executed"
                          ? 2
                          : action.status === "approved" ||
                              action.status === "executing"
                            ? 1
                            : 0
                      }
                      bulletSize={20}
                      lineWidth={2}
                    >
                      <Timeline.Item title="创建待审批邮件">
                        <Text size="xs" c="dimmed">
                          {new Date(action.created_at).toLocaleString("zh-CN")}
                        </Text>
                      </Timeline.Item>
                      <Timeline.Item title="核对并批准">
                        <Text size="xs" c="dimmed">
                          审批有效期至{" "}
                          {new Date(action.expires_at).toLocaleString("zh-CN")}
                        </Text>
                      </Timeline.Item>
                      <Timeline.Item title={STATUS_LABELS[action.status]} />
                    </Timeline>
                    {action.status === "pending" && (
                      <Group>
                        <Button
                          disabled={working}
                          onClick={() => void runAction(action, "approve")}
                        >
                          核对后批准
                        </Button>
                        <Button
                          variant="default"
                          disabled={working}
                          onClick={() => void runAction(action, "reject")}
                        >
                          拒绝
                        </Button>
                      </Group>
                    )}
                    {action.status === "approved" && (
                      <Button
                        leftSection={<IconSend size={16} />}
                        loading={working}
                        onClick={() => void runAction(action, "execute")}
                      >
                        最终确认并发送
                      </Button>
                    )}
                    {error && lastActionId === action.id && (
                      <Alert color="red">{error}</Alert>
                    )}
                    {action.status === "executed" && (
                      <Alert color="teal">
                        SMTP 接受发送请求。Message-ID：
                        {String(action.result?.message_id ?? "未返回")}
                      </Alert>
                    )}
                    {action.status === "outcome_unknown" && (
                      <Alert color="orange" title="发送结果待核对">
                        服务未能确认邮件是否送达。请检查已发送邮件和收件人邮箱；系统不会自动重试。
                      </Alert>
                    )}
                  </Stack>
                </Paper>
              ))
            )}
          </Stack>
        </>
      )}
    </Stack>
  );
}
