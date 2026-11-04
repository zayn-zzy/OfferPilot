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
  ApiError,
  apiRequest,
  type AgentTaskPlan,
  type AgentWorkspace,
} from "@/lib/api";
import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  Timeline,
  Title,
  UnstyledButton,
} from "@mantine/core";
import {
  IconArrowUpRight,
  IconRefresh,
  IconSparkles,
} from "@tabler/icons-react";
import {
  EmptyState,
  Feedback,
  LoadingState,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import classes from "./agent.module.css";

const STATUS_LABELS: Record<AgentTaskPlan["status"], string> = {
  queued: "排队中",
  running: "整理计划中",
  cancelling: "取消中",
  awaiting_confirmation: "等待确认",
  needs_clarification: "需要补充信息",
  confirmed: "提醒已创建",
  cancelled: "已取消",
  failed: "处理失败",
};

const KIND_LABELS: Record<string, string> = {
  opening: "开放日",
  deadline: "截止日期",
  assessment: "测评",
  interview: "面试",
  follow_up: "跟进",
  other: "其他",
};

const RUN_TASK_LABELS: Record<string, string> = {
  job_extraction: "岗位信息提取",
  job_match: "岗位匹配分析",
  company_research: "公司研究",
  knowledge_qa: "个人资料问答",
  skill_workflow: "求职材料准备",
};

const RUN_STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  failed: "处理失败",
  cancelled: "已取消",
  confirmed: "已确认",
};

type AgentActivity =
  | { type: "plan"; updatedAt: string; plan: AgentTaskPlan }
  | {
      type: "run";
      updatedAt: string;
      run: NonNullable<AgentWorkspace>["recent_runs"][number];
    };

function isActionRequired(activity: AgentActivity) {
  return (
    activity.type === "plan" &&
    ["awaiting_confirmation", "needs_clarification", "failed"].includes(
      activity.plan.status,
    )
  );
}

function activityTitle(activity: AgentActivity) {
  if (activity.type === "plan")
    return activity.plan.preview?.title || "求职提醒计划";
  if (activity.run.task_type === "skill_workflow" && activity.run.skill_id) {
    return `求职材料准备：${activity.run.skill_id}`;
  }
  return RUN_TASK_LABELS[activity.run.task_type] || "Agent 任务";
}

function activityHref(activity: AgentActivity) {
  if (activity.type === "plan") return "/agent#task-planner";
  if (activity.run.task_type === "skill_workflow") return "/skills";
  if (activity.run.task_type === "company_research") return "/companies";
  if (activity.run.task_type === "knowledge_qa") return "/knowledge";
  return "/jobs";
}

function activityStatus(activity: AgentActivity) {
  if (activity.type === "plan") return STATUS_LABELS[activity.plan.status];
  return RUN_STATUS_LABELS[activity.run.status] || activity.run.status;
}

function formatEventTime(value: string | null, timezone: string) {
  if (!value) return "日期待补充";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: timezone,
    }).format(new Date(value));
  } catch {
    return new Date(value).toLocaleString("zh-CN");
  }
}

function apiErrorMessage(
  cause: unknown,
  fallback: string,
  loginMessage: string,
) {
  if (cause instanceof ApiError && cause.status === 401) return loginMessage;
  return cause instanceof Error ? cause.message : fallback;
}

export default function AgentTaskPlannerPage() {
  const [selectedActivityId, setSelectedActivityId] = useState<string | null>(
    null,
  );
  const [plans, setPlans] = useState<AgentTaskPlan[]>([]);
  const [workspace, setWorkspace] = useState<AgentWorkspace | null>(null);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [workingId, setWorkingId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [planListError, setPlanListError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceRequiresLogin, setWorkspaceRequiresLogin] = useState(false);
  const [showAllActivities, setShowAllActivities] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  const loadPlans = useCallback(async () => {
    try {
      setPlans(
        await apiRequest<AgentTaskPlan[]>("/api/v1/agent/task-plans?limit=20"),
      );
      setPlanListError("");
      setRequiresLogin(false);
    } catch (cause) {
      setPlanListError(
        apiErrorMessage(cause, "无法载入提醒计划。", "登录后可查看提醒计划。"),
      );
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadWorkspace = useCallback(async () => {
    try {
      setWorkspace(await apiRequest<AgentWorkspace>("/api/v1/agent/workspace"));
      setWorkspaceError("");
      setWorkspaceRequiresLogin(false);
    } catch (cause) {
      setWorkspaceError(
        apiErrorMessage(
          cause,
          "无法载入求职工作流。",
          "登录后可查看求职工作流和运行记录。",
        ),
      );
      setWorkspaceRequiresLogin(
        cause instanceof ApiError && cause.status === 401,
      );
    } finally {
      setWorkspaceLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPlans();
  }, [loadPlans]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  useEffect(() => {
    if (
      !plans.some((plan) =>
        ["queued", "running", "cancelling"].includes(plan.status),
      )
    )
      return;
    const timer = window.setInterval(() => {
      void loadPlans();
    }, 1500);
    return () => window.clearInterval(timer);
  }, [plans, loadPlans]);

  const activities = useMemo<AgentActivity[]>(() => {
    const planItems: AgentActivity[] = plans.map((plan) => ({
      type: "plan",
      updatedAt: plan.updated_at,
      plan,
    }));
    const runItems: AgentActivity[] = (workspace?.recent_runs || []).map(
      (run) => ({
        type: "run",
        updatedAt: run.updated_at,
        run,
      }),
    );
    return [...planItems, ...runItems].sort((left, right) => {
      const priority =
        Number(isActionRequired(right)) - Number(isActionRequired(left));
      return (
        priority || Date.parse(right.updatedAt) - Date.parse(left.updatedAt)
      );
    });
  }, [plans, workspace]);

  const visibleActivities = showAllActivities
    ? activities
    : activities.slice(0, 6);
  const moreActivityCount = activities.length - visibleActivities.length;

  async function refreshActivity() {
    setError("");
    await Promise.all([loadPlans(), loadWorkspace()]);
  }

  async function createPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setNotice("");
    idempotencyKey.current ??= window.crypto.randomUUID();
    try {
      const plan = await apiRequest<AgentTaskPlan>("/api/v1/agent/task-plans", {
        method: "POST",
        body: JSON.stringify({ text, idempotency_key: idempotencyKey.current }),
      });
      idempotencyKey.current = null;
      setText("");
      setSelectedActivityId(`plan-${plan.id}`);
      setPlanListError("");
      setPlans((current) => [
        plan,
        ...current.filter((item) => item.id !== plan.id),
      ]);
      setNotice("已收到请求。提醒草稿生成后会先展示给你确认。");
      setRequiresLogin(false);
    } catch (cause) {
      setError(
        apiErrorMessage(
          cause,
          "无法创建提醒计划。",
          "登录状态已失效，请重新登录后再创建提醒。",
        ),
      );
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setSubmitting(false);
    }
  }

  async function runAction(
    plan: AgentTaskPlan,
    action: "confirm" | "cancel" | "retry",
  ) {
    setWorkingId(plan.id);
    setError("");
    setNotice("");
    try {
      const updated = await apiRequest<AgentTaskPlan>(
        `/api/v1/agent/task-plans/${plan.id}/${action}`,
        {
          method: "POST",
        },
      );
      setPlans((current) => [
        updated,
        ...current.filter((item) => item.id !== updated.id),
      ]);
      setNotice(
        action === "confirm"
          ? "提醒已保存，可在提醒中心查看。"
          : action === "cancel"
            ? updated.status === "cancelling"
              ? "已请求取消；模型响应完成后会丢弃结果。"
              : "任务计划已取消。"
            : "已安排重试。",
      );
    } catch (cause) {
      setError(
        apiErrorMessage(
          cause,
          "任务操作失败。",
          "登录状态已失效，请重新登录后再操作。",
        ),
      );
      if (cause instanceof ApiError && cause.status === 401)
        setRequiresLogin(true);
      await loadPlans();
    } finally {
      setWorkingId(null);
    }
  }

  const capabilities = (workspace?.capabilities || []).filter(
    (item) => item.id !== "reminder_plan",
  );
  const actionableCount = activities.filter(isActionRequired).length;
  const loadingActivities = loading || workspaceLoading;
  const loginRequired =
    (requiresLogin || workspaceRequiresLogin) && !loadingActivities;

  const selectedActivity =
    activities.find(
      (activity) =>
        `${activity.type}-${activity.type === "plan" ? activity.plan.id : activity.run.id}` ===
        selectedActivityId,
    ) || activities[0];
  const selectedPlan =
    selectedActivity?.type === "plan" ? selectedActivity.plan : null;
  const selectedRun =
    selectedActivity?.type === "run" ? selectedActivity.run : null;
  const preview = selectedPlan?.preview;
  const busy = selectedPlan ? workingId === selectedPlan.id : false;

  return (
    <Stack gap="xl">
      <PageHeader
        title="Agent 工作区"
        description="选择求职工作流，查看待处理任务，或规划一条提醒。"
        actions={
          <Button
            variant="default"
            leftSection={<IconRefresh size={16} />}
            loading={loadingActivities}
            onClick={() => void refreshActivity()}
          >
            刷新任务状态
          </Button>
        }
      />
      <Feedback
        error={loginRequired ? "登录后才能查看和使用 Agent 工作区。" : error}
        notice={notice}
        requiresLogin={loginRequired}
      />
      <Paper
        withBorder
        radius="lg"
        p="xl"
        component="section"
        id="task-planner"
        aria-labelledby="task-planner-title"
      >
        <Stack gap="md">
          <Group gap="sm">
            <IconSparkles size={21} />
            <Title order={2} size="h3" id="task-planner-title">
              创建求职提醒
            </Title>
          </Group>
          <Text size="sm" c="dimmed">
            描述要做的事和日期。生成草稿后，你确认才会保存。
          </Text>
          <form onSubmit={createPlan}>
            <Stack gap="md">
              <Textarea
                id="task-request"
                label="提醒内容"
                value={text}
                onChange={(event) => {
                  idempotencyKey.current = null;
                  setText(event.currentTarget.value);
                }}
                placeholder="例如：周三前完成目标岗位的在线测评。"
                aria-describedby="task-request-help"
                minRows={3}
                autosize
                minLength={3}
                maxLength={4000}
                required
              />
              <Group justify="space-between">
                <Text id="task-request-help" size="xs" c="dimmed">
                  未写具体时间时，按账户时区当天 09:00 安排。
                </Text>
                <Button type="submit" loading={submitting}>
                  生成提醒草稿
                </Button>
              </Group>
            </Stack>
          </form>
        </Stack>
      </Paper>
      <section aria-labelledby="activity-title">
        <Stack gap="md">
          <Group justify="space-between">
            <Title order={2} size="h3" id="activity-title">
              任务记录
            </Title>
            {actionableCount > 0 && (
              <Badge color="orange">{actionableCount} 项需要你处理</Badge>
            )}
          </Group>
          {planListError && !requiresLogin && (
            <Alert color="red" title="提醒计划载入失败">
              <Stack gap="sm">
                <Text size="sm">{planListError}</Text>
                <Button
                  variant="light"
                  size="xs"
                  onClick={() => void loadPlans()}
                >
                  重新载入提醒计划
                </Button>
              </Stack>
            </Alert>
          )}
          {workspaceError && !workspaceRequiresLogin && (
            <Alert color="orange">
              <Group justify="space-between">
                <Stack gap={4}>
                  <Text size="sm">
                    运行记录暂时不可用，提醒计划会单独显示。
                  </Text>
                  <Text size="xs">{workspaceError}</Text>
                </Stack>
                <Button
                  variant="subtle"
                  size="xs"
                  onClick={() => void loadWorkspace()}
                >
                  重新载入运行记录
                </Button>
              </Group>
            </Alert>
          )}
          {loadingActivities && activities.length === 0 ? (
            <LoadingState />
          ) : !activities.length &&
            (planListError || workspaceError) ? null : !activities.length ? (
            <EmptyState
              title="还没有 Agent 任务记录"
              description={
                loginRequired
                  ? "登录后会显示你的任务记录。"
                  : "创建提醒或选择一个求职工作流，任务会显示在这里。"
              }
              action={
                <Button component="a" href="#task-request" variant="light">
                  规划一条提醒
                </Button>
              }
            />
          ) : (
            <div className={classes.taskGrid}>
              <Paper withBorder radius="lg" p="sm">
                <Stack gap="xs">
                  {visibleActivities.map((activity) => {
                    const id = `${activity.type}-${activity.type === "plan" ? activity.plan.id : activity.run.id}`;
                    const selected = activity === selectedActivity;
                    return (
                      <UnstyledButton
                        key={id}
                        className={`${classes.listButton} ${selected ? classes.selected : ""}`}
                        onClick={() => setSelectedActivityId(id)}
                        aria-pressed={selected}
                      >
                        <Stack gap={6}>
                          <Group justify="space-between" gap="xs">
                            <Text size="xs" c="dimmed">
                              {activity.type === "plan"
                                ? "提醒计划"
                                : "Agent 运行"}
                            </Text>
                            <StatusBadge
                              status={
                                activity.type === "plan"
                                  ? activity.plan.status
                                  : activity.run.status
                              }
                              label={activityStatus(activity)}
                            />
                          </Group>
                          <Text size="sm" fw={600}>
                            {activityTitle(activity)}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {formatEventTime(
                              activity.updatedAt,
                              workspace?.timezone || "Asia/Shanghai",
                            )}
                          </Text>
                        </Stack>
                      </UnstyledButton>
                    );
                  })}
                  {moreActivityCount > 0 && (
                    <Button
                      variant="subtle"
                      onClick={() => setShowAllActivities(true)}
                    >
                      显示另外 {moreActivityCount} 项记录
                    </Button>
                  )}
                </Stack>
              </Paper>
              {selectedActivity && (
                <Paper withBorder p="xl" radius="lg" className={classes.panel}>
                  <Stack gap="lg">
                    <Group justify="space-between" align="flex-start">
                      <Title order={3} size="h4">
                        {activityTitle(selectedActivity)}
                      </Title>
                      <StatusBadge
                        status={
                          selectedPlan?.status || selectedRun?.status || ""
                        }
                        label={activityStatus(selectedActivity)}
                      />
                    </Group>
                    {(preview?.job_label || selectedRun?.job_label) && (
                      <Text size="sm" c="dimmed">
                        {preview?.job_label || selectedRun?.job_label}
                      </Text>
                    )}
                    {selectedPlan && (
                      <>
                        {preview && (
                          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                            {preview.event_at && (
                              <div>
                                <Text size="xs" c="dimmed">
                                  提醒时间
                                </Text>
                                <Text size="sm" fw={500}>
                                  {formatEventTime(
                                    preview.event_at,
                                    preview.timezone,
                                  )}
                                </Text>
                                <Text size="xs" c="dimmed">
                                  {preview.timezone}
                                </Text>
                              </div>
                            )}
                            {preview.kind && (
                              <div>
                                <Text size="xs" c="dimmed">
                                  提醒类型
                                </Text>
                                <Text size="sm">
                                  {KIND_LABELS[preview.kind] || preview.kind}
                                </Text>
                              </div>
                            )}
                            {preview.details && (
                              <div>
                                <Text size="xs" c="dimmed">
                                  补充说明
                                </Text>
                                <Text size="sm">{preview.details}</Text>
                              </div>
                            )}
                          </SimpleGrid>
                        )}
                        {selectedPlan.status === "needs_clarification" && (
                          <Alert color="orange" title="需要补充信息">
                            {preview?.clarification_question ||
                              "请补充具体日期和任务动作后重新创建。"}
                          </Alert>
                        )}
                        {selectedPlan.status === "cancelling" && (
                          <Alert color="orange">
                            正在等待当前模型请求结束；返回内容不会保存，也不会创建提醒。
                          </Alert>
                        )}
                        {selectedPlan.status === "failed" && (
                          <Alert color="red" title="任务规划失败">
                            <Stack gap="sm">
                              <Text size="sm">
                                {selectedPlan.error_message || "任务规划失败。"}
                              </Text>
                              <Button
                                variant="light"
                                size="sm"
                                loading={busy}
                                disabled={selectedPlan.attempt_count >= 3}
                                onClick={() =>
                                  void runAction(selectedPlan, "retry")
                                }
                              >
                                {selectedPlan.attempt_count >= 3
                                  ? "已达到重试上限"
                                  : "重试任务"}
                              </Button>
                            </Stack>
                          </Alert>
                        )}
                        {selectedPlan.status === "confirmed" && (
                          <Alert color="teal">
                            提醒已保存。
                            <Button
                              component={Link}
                              href="/reminders"
                              variant="subtle"
                              size="xs"
                            >
                              打开提醒中心
                            </Button>
                          </Alert>
                        )}
                        {selectedPlan.status === "awaiting_confirmation" && (
                          <Group>
                            <Button
                              loading={busy}
                              onClick={() =>
                                void runAction(selectedPlan, "confirm")
                              }
                            >
                              确认并创建提醒
                            </Button>
                            <Button
                              variant="default"
                              disabled={busy}
                              onClick={() =>
                                void runAction(selectedPlan, "cancel")
                              }
                            >
                              取消计划
                            </Button>
                          </Group>
                        )}
                        {(selectedPlan.status === "queued" ||
                          selectedPlan.status === "running") && (
                          <Button
                            variant="default"
                            loading={busy}
                            onClick={() =>
                              void runAction(selectedPlan, "cancel")
                            }
                          >
                            取消任务
                          </Button>
                        )}
                        {selectedPlan.status === "needs_clarification" && (
                          <Button
                            variant="default"
                            disabled={busy}
                            onClick={() =>
                              void runAction(selectedPlan, "cancel")
                            }
                          >
                            关闭计划
                          </Button>
                        )}
                        {selectedPlan.events.length > 0 && (
                          <>
                            <Divider label="运行进度" />
                            <Timeline
                              active={selectedPlan.events.length - 1}
                              bulletSize={18}
                              lineWidth={2}
                            >
                              {selectedPlan.events.map((event) => (
                                <Timeline.Item
                                  key={event.id}
                                  title={<Text size="sm">{event.message}</Text>}
                                >
                                  <Text size="xs" c="dimmed">
                                    {formatEventTime(
                                      event.created_at,
                                      workspace?.timezone || "Asia/Shanghai",
                                    )}
                                  </Text>
                                </Timeline.Item>
                              ))}
                            </Timeline>
                          </>
                        )}
                      </>
                    )}
                    {selectedRun && (
                      <>
                        <Button
                          component={Link}
                          href={activityHref(selectedActivity)}
                          variant="light"
                          rightSection={<IconArrowUpRight size={16} />}
                        >
                          打开相关工作区
                        </Button>
                        <Divider label="运行信息" />
                        <SimpleGrid cols={{ base: 1, sm: 2 }}>
                          <div>
                            <Text size="xs" c="dimmed">
                              更新时间
                            </Text>
                            <Text size="sm">
                              {formatEventTime(
                                selectedRun.updated_at,
                                workspace?.timezone || "Asia/Shanghai",
                              )}
                            </Text>
                          </div>
                          {selectedRun.duration_ms !== null && (
                            <div>
                              <Text size="xs" c="dimmed">
                                耗时
                              </Text>
                              <Text size="sm">
                                {selectedRun.duration_ms} ms
                              </Text>
                            </div>
                          )}
                          {selectedRun.total_tokens !== null && (
                            <div>
                              <Text size="xs" c="dimmed">
                                Token
                              </Text>
                              <Text size="sm">{selectedRun.total_tokens}</Text>
                            </div>
                          )}
                          {selectedRun.estimated_cost_usd !== null && (
                            <div>
                              <Text size="xs" c="dimmed">
                                估算费用
                              </Text>
                              <Text size="sm">
                                ${selectedRun.estimated_cost_usd.toFixed(6)}
                              </Text>
                            </div>
                          )}
                        </SimpleGrid>
                      </>
                    )}
                  </Stack>
                </Paper>
              )}
            </div>
          )}
        </Stack>
      </section>
      <section aria-labelledby="agent-capabilities-title">
        <Stack gap="md">
          <Title order={2} size="h3" id="agent-capabilities-title">
            求职工作流
          </Title>
          {workspaceLoading ? (
            <LoadingState />
          ) : loginRequired ? (
            <Text size="sm" c="dimmed">
              登录后将载入可用的求职工作流。
            </Text>
          ) : workspaceError ? null : capabilities.length ? (
            <SimpleGrid cols={{ base: 1, sm: 2, xl: 3 }}>
              {capabilities.map((capability) => (
                <Paper withBorder radius="lg" p="lg" key={capability.id}>
                  <Stack h="100%" gap="md">
                    <Group justify="space-between">
                      <Title order={3} size="h4">
                        {capability.title}
                      </Title>
                      <Badge
                        size="xs"
                        color={
                          capability.action_level === "read_only"
                            ? "gray"
                            : "teal"
                        }
                      >
                        {capability.action_level === "read_only"
                          ? "只读"
                          : capability.confirmation_required
                            ? "草稿，需确认"
                            : "生成草稿"}
                      </Badge>
                    </Group>
                    <Text size="sm" c="dimmed" style={{ flex: 1 }}>
                      {capability.description}
                    </Text>
                    <Button
                      component={Link}
                      href={capability.href}
                      variant="subtle"
                      justify="space-between"
                      rightSection={<IconArrowUpRight size={16} />}
                    >
                      {capability.action_label}
                    </Button>
                  </Stack>
                </Paper>
              ))}
            </SimpleGrid>
          ) : (
            <EmptyState
              title="暂时没有可用工作流"
              action={
                <Button variant="light" onClick={() => void loadWorkspace()}>
                  重新载入工作流
                </Button>
              }
            />
          )}
        </Stack>
      </section>
      <Text size="xs" c="dimmed">
        各工作流只在授权范围内读取资料。生成草稿不会自动改动投递状态；本地保存与外部邮件发送分别需要审批。MVP
        不会登录或提交招聘网站，也不会代替用户完成测评。
      </Text>
    </Stack>
  );
}
