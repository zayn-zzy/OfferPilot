"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Anchor,
  Badge,
  Box,
  Button,
  Card,
  Grid,
  Group,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import {
  IconArrowUpRight,
  IconBriefcase2,
  IconCalendarEvent,
  IconClock,
  IconPlus,
  IconRobot,
} from "@tabler/icons-react";
import {
  ApiError,
  apiRequest,
  APPLICATION_STAGE_LABELS,
  type DashboardSummary,
} from "@/lib/api";
import {
  EmptyState,
  Feedback,
  LoadingState,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import classes from "./dashboard.module.css";

function dateLabel(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return `${year}年${month}月${day}日`;
}
function timeLabel(value: string, timezone: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(value));
}
const taskLabels: Record<string, string> = {
  job_extraction: "岗位信息提取",
  company_research: "公司研究",
  task_plan: "提醒计划",
  skill_workflow: "求职 Skill",
  knowledge_qa: "个人资料问答",
  job_match: "岗位匹配",
};
function taskHref(task: string) {
  return task === "task_plan"
    ? "/agent"
    : task === "skill_workflow"
      ? "/skills"
      : task === "company_research"
        ? "/companies"
        : task === "knowledge_qa"
          ? "/knowledge"
          : "/jobs";
}

export default function DashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    setError("");
    apiRequest<DashboardSummary>("/api/v1/dashboard", {
      signal: controller.signal,
    })
      .then((summary) => {
        if (active) {
          setDashboard(summary);
          setRequiresLogin(false);
        }
      })
      .catch((cause) => {
        if (!active) return;
        setError(
          cause instanceof DOMException && cause.name === "AbortError"
            ? "工作台请求超时，请检查服务后重试。"
            : cause instanceof Error
              ? cause.message
              : "无法载入工作台。",
        );
        setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [refresh]);
  return (
    <main>
      <PageHeader
        title="求职总览"
        description={
          dashboard
            ? `${dateLabel(dashboard.today)}，按 ${dashboard.timezone} 汇总你的求职安排。`
            : "把岗位、准备事项和下一步安排放在一起。"
        }
        actions={
          <Button
            component={Link}
            href="/jobs"
            leftSection={<IconPlus size={17} />}
          >
            管理岗位
          </Button>
        }
      />
      <Feedback error={error} requiresLogin={requiresLogin} />
      {!dashboard ? (
        error ? (
          !requiresLogin && (
            <Button
              variant="default"
              onClick={() => setRefresh((value) => value + 1)}
            >
              重新加载
            </Button>
          )
        ) : (
          <LoadingState />
        )
      ) : (
        <Stack gap="lg">
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="lg">
            {[
              {
                label: "投递记录",
                value: dashboard.stage_counts.reduce(
                  (sum, item) => sum + item.count,
                  0,
                ),
                detail: "已保存的投递阶段记录",
                icon: IconBriefcase2,
                href: "/jobs",
              },
              {
                label: "近期待办",
                value: dashboard.upcoming_tasks.length,
                detail: "未来 7 天的提醒与跟进",
                icon: IconCalendarEvent,
                href: "/reminders",
              },
              {
                label: "临近截止",
                value: dashboard.approaching_deadlines.length,
                detail: "未来 14 天内截止的岗位",
                icon: IconClock,
                href: "/jobs",
              },
            ].map((stat) => (
              <Card
                key={stat.label}
                component={Link}
                href={stat.href}
                className={classes.stat}
              >
                <Group justify="space-between">
                  <Text size="sm" c="dimmed">
                    {stat.label}
                  </Text>
                  <ThemeIcon variant="light" color="teal" size={36}>
                    <stat.icon size={20} />
                  </ThemeIcon>
                </Group>
                <Text fz={34} fw={650} mt="sm" lh={1.2}>
                  {stat.value}
                </Text>
                <Group justify="space-between" mt="sm">
                  <Text size="xs" c="dimmed">
                    {stat.detail}
                  </Text>
                  <IconArrowUpRight size={17} />
                </Group>
              </Card>
            ))}
          </SimpleGrid>
          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, lg: 8 }}>
              <Card h="100%">
                <Group justify="space-between" mb="lg">
                  <Title order={2} size="h4">
                    当前投递进展
                  </Title>
                  <Anchor component={Link} href="/jobs" size="sm">
                    岗位列表
                  </Anchor>
                </Group>
                {dashboard.current_stage ? (
                  <Stack gap="sm">
                    <Badge w="fit-content">
                      {APPLICATION_STAGE_LABELS[dashboard.current_stage.status]}
                    </Badge>
                    <Text fw={600} fz="lg">
                      {dashboard.current_stage.job_label}
                    </Text>
                    <Text c="dimmed" size="xs">
                      最近更新于{" "}
                      {timeLabel(
                        dashboard.current_stage.updated_at,
                        dashboard.timezone,
                      )}
                    </Text>
                  </Stack>
                ) : (
                  <Text c="dimmed" size="sm">
                    还没有进行中的投递记录。从岗位卡片记录你的进度。
                  </Text>
                )}
                <Group mt="lg" gap="xs" aria-label="各投递阶段数量">
                  {dashboard.stage_counts.map((item) => (
                    <Badge key={item.status} variant="default" size="lg">
                      {APPLICATION_STAGE_LABELS[item.status]} {item.count}
                    </Badge>
                  ))}
                </Group>
              </Card>
            </Grid.Col>
            <Grid.Col span={{ base: 12, lg: 4 }}>
              <Card className={classes.quick} h="100%">
                <ThemeIcon variant="light" size={42}>
                  <IconRobot size={24} />
                </ThemeIcon>
                <Title order={2} size="h4" mt="md">
                  继续求职准备
                </Title>
                <Text c="dimmed" size="sm" mt="xs">
                  从一项具体任务开始，让 Agent 帮你整理下一步。
                </Text>
                <Group mt="lg">
                  <Button component={Link} href="/agent" variant="light">
                    规划近期任务
                  </Button>
                  <Anchor component={Link} href="/profile" size="sm">
                    完善档案与简历
                  </Anchor>
                </Group>
              </Card>
            </Grid.Col>
          </Grid>
          <Grid gutter="lg">
            <Grid.Col span={{ base: 12, lg: 6 }}>
              <Card h="100%">
                <Group justify="space-between" mb="md">
                  <Title order={2} size="h4">
                    近期待办
                  </Title>
                  <Anchor component={Link} href="/reminders" size="sm">
                    提醒中心
                  </Anchor>
                </Group>
                {dashboard.upcoming_tasks.length ? (
                  <Stack gap={0}>
                    {dashboard.upcoming_tasks.map((task) => (
                      <Group
                        key={`${task.kind}-${task.id}`}
                        className={classes.row}
                        justify="space-between"
                        wrap="nowrap"
                      >
                        <Box miw={0}>
                          <Text fw={550} size="sm">
                            {task.title}
                          </Text>
                          <Text c="dimmed" size="xs" mt={4}>
                            {task.due_at
                              ? timeLabel(task.due_at, task.timezone)
                              : task.due_date
                                ? dateLabel(task.due_date)
                                : "时间未设置"}
                          </Text>
                          {task.job_label && (
                            <Text c="dimmed" size="xs" mt={3}>
                              {task.job_label}
                            </Text>
                          )}
                        </Box>
                        <Button
                          component={Link}
                          href={
                            task.kind === "reminder" ? "/reminders" : "/jobs"
                          }
                          variant="subtle"
                          size="compact-sm"
                        >
                          打开
                        </Button>
                      </Group>
                    ))}
                  </Stack>
                ) : (
                  <EmptyState
                    title="近期暂无待办"
                    description="未来 7 天没有提醒或投递跟进。"
                    action={
                      <Button
                        component={Link}
                        href="/reminders"
                        variant="light"
                      >
                        创建提醒
                      </Button>
                    }
                  />
                )}
              </Card>
            </Grid.Col>
            <Grid.Col span={{ base: 12, lg: 6 }}>
              <Card h="100%">
                <Group justify="space-between" mb="md">
                  <Title order={2} size="h4">
                    临近截止岗位
                  </Title>
                  <Anchor component={Link} href="/jobs" size="sm">
                    全部岗位
                  </Anchor>
                </Group>
                {dashboard.approaching_deadlines.length ? (
                  <Stack gap={0}>
                    {dashboard.approaching_deadlines.map((job) => (
                      <Group
                        key={job.job_id}
                        className={classes.row}
                        justify="space-between"
                        wrap="nowrap"
                      >
                        <Box miw={0}>
                          <Text fw={550} size="sm">
                            {job.job_label}
                          </Text>
                          <Text size="xs" c="dimmed" mt={4}>
                            {dateLabel(job.deadline)} 截止
                          </Text>
                        </Box>
                        <Badge
                          color={job.days_remaining < 3 ? "red" : "orange"}
                        >
                          {job.days_remaining === 0
                            ? "今天"
                            : `${job.days_remaining} 天`}
                        </Badge>
                      </Group>
                    ))}
                  </Stack>
                ) : (
                  <EmptyState
                    title="暂未记录近期截止岗位"
                    description="完善岗位截止时间，便于提前准备。"
                    action={
                      <Button component={Link} href="/jobs" variant="light">
                        查看岗位
                      </Button>
                    }
                  />
                )}
              </Card>
            </Grid.Col>
          </Grid>
          <Card>
            <Group justify="space-between" mb="md">
              <Title order={2} size="h4">
                最近 Agent 运行
              </Title>
              <Anchor component={Link} href="/agent" size="sm">
                查看任务
              </Anchor>
            </Group>
            {dashboard.recent_agent_runs.length ? (
              <Stack gap={0}>
                {dashboard.recent_agent_runs.map((run) => (
                  <Group
                    key={run.id}
                    className={classes.row}
                    justify="space-between"
                    wrap="wrap"
                  >
                    <Group wrap="nowrap">
                      <StatusBadge status={run.status} />
                      <Box>
                        <Text size="sm" fw={550}>
                          {taskLabels[run.task_type] ?? "Agent 任务"}
                        </Text>
                        <Text size="xs" c="dimmed" mt={4}>
                          {run.job_label ?? "未关联岗位"}
                        </Text>
                      </Box>
                    </Group>
                    <Group gap="md">
                      <Text size="xs" c="dimmed">
                        {timeLabel(run.created_at, dashboard.timezone)}
                      </Text>
                      <Button
                        component={Link}
                        href={taskHref(run.task_type)}
                        variant="subtle"
                        size="compact-sm"
                      >
                        打开
                      </Button>
                    </Group>
                  </Group>
                ))}
              </Stack>
            ) : (
              <EmptyState
                title="还没有 Agent 任务"
                description="你发起的岗位提取、公司研究和求职准备会显示在这里。"
                action={
                  <Button component={Link} href="/agent" variant="light">
                    打开 Agent 工作区
                  </Button>
                }
              />
            )}
          </Card>
        </Stack>
      )}
    </main>
  );
}
