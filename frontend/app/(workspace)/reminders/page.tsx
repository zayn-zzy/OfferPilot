"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Accordion,
  Alert,
  Autocomplete,
  Badge,
  Button,
  Drawer,
  Group,
  Menu,
  Paper,
  Select,
  Stack,
  Switch,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { DateTimePicker } from "@mantine/dates";
import {
  IconBell,
  IconCheck,
  IconClock,
  IconDots,
  IconPlus,
  IconWorld,
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
  type JobPosting,
  type Reminder,
  type ReminderCenter,
  type User,
  type UserTimezoneUpdate,
} from "@/lib/api";

const REMINDER_KINDS = [
  ["opening", "招聘开放日"],
  ["deadline", "网申截止"],
  ["assessment", "测评"],
  ["interview", "面试"],
  ["follow_up", "跟进"],
  ["other", "其他"],
] as const;

const REMINDER_KIND_LABELS = Object.fromEntries(REMINDER_KINDS) as Record<
  string,
  string
>;
const REMINDER_STATUS_LABELS = {
  scheduled: "待提醒",
  paused: "已暂停",
  notified: "已通知",
  completed: "已完成",
  cancelled: "已取消",
  failed: "投递失败",
} as const;

type ReminderDraft = {
  title: string;
  details: string;
  kind: (typeof REMINDER_KINDS)[number][0];
  eventAt: string;
  leadMinutes: number;
  jobId: string;
};

function formatLocalDateTime(value: Date, timeZone: string) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(value)
      .map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function localDateTimeToIso(value: string, timeZone: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) throw new Error("请填写有效的事件日期和时间。");
  const [, year, month, day, hour, minute] = match;
  const wallTime = Date.UTC(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
  );
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  let guess = wallTime;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const parts = Object.fromEntries(
      formatter
        .formatToParts(new Date(guess))
        .map((part) => [part.type, part.value]),
    );
    const represented = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour),
      Number(parts.minute),
    );
    const offset = represented - guess;
    if (offset === 0) break;
    guess = wallTime - offset;
  }
  if (formatLocalDateTime(new Date(guess), timeZone) !== value) {
    throw new Error("这个本地时间在所选时区不存在，请调整时间。");
  }
  return new Date(guess).toISOString();
}

function formatDate(value: string, timeZone: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone,
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function leadLabel(minutes: number) {
  if (minutes === 0) return "事件时间提醒";
  if (minutes % 1440 === 0) return `提前 ${minutes / 1440} 天提醒`;
  if (minutes % 60 === 0) return `提前 ${minutes / 60} 小时提醒`;
  return `提前 ${minutes} 分钟提醒`;
}

export default function RemindersPage() {
  const confirm = useConfirm();
  const [createOpened, setCreateOpened] = useState(false);
  const [center, setCenter] = useState<ReminderCenter | null>(null);
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [draft, setDraft] = useState<ReminderDraft>({
    title: "",
    details: "",
    kind: "deadline",
    eventAt: "",
    leadMinutes: 60,
    jobId: "",
  });
  const [timeZone, setTimeZone] = useState("Asia/Shanghai");
  const [timeZoneDraft, setTimeZoneDraft] = useState("Asia/Shanghai");
  const [includeClosed, setIncludeClosed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingTimeZone, setSavingTimeZone] = useState(false);
  const [lastActionId, setLastActionId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  async function loadCenter(closed = includeClosed) {
    setLoading(true);
    setError("");
    try {
      setCenter(
        await apiRequest<ReminderCenter>(
          `/api/v1/reminders?include_closed=${closed}`,
        ),
      );
      setRequiresLogin(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法载入提醒中心。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setDraft((current) => ({
      ...current,
      eventAt: formatLocalDateTime(
        new Date(Date.now() + 24 * 60 * 60 * 1000),
        "Asia/Shanghai",
      ),
    }));
    void loadCenter(false);
    apiRequest<User>("/api/v1/auth/me")
      .then((user) => {
        setTimeZone(user.timezone);
        setTimeZoneDraft(user.timezone);
        setDraft((current) => ({
          ...current,
          eventAt: formatLocalDateTime(
            new Date(Date.now() + 24 * 60 * 60 * 1000),
            user.timezone,
          ),
        }));
      })
      .catch(() => undefined);
    apiRequest<JobPosting[]>("/api/v1/jobs")
      .then(setJobs)
      .catch(() => setJobs([]));
    // Load once on mount. The filter has its own explicit reload action.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updateDraft(change: Partial<ReminderDraft>) {
    idempotencyKey.current = null;
    setDraft((current) => ({ ...current, ...change }));
  }

  async function updateTimeZone() {
    if (timeZoneDraft === timeZone) return;
    const accepted = await confirm({
      title: "保存时区并重算未来提醒",
      confirmLabel: "确认重算",
      message: `将时区从 ${timeZone} 改为 ${timeZoneDraft}。未来提醒会保留原来的本地钟点，并重新计算 UTC 触发时间。是否继续？`,
    });
    if (!accepted) return;
    setSavingTimeZone(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<UserTimezoneUpdate>(
        "/api/v1/auth/me/timezone",
        {
          method: "PUT",
          body: JSON.stringify({
            timezone: timeZoneDraft,
            recalculate_future: true,
          }),
        },
      );
      setTimeZone(result.user.timezone);
      setTimeZoneDraft(result.user.timezone);
      setNotice(
        `时区已更新，已重算 ${result.recalculated_reminders} 条未来提醒。`,
      );
      await loadCenter(includeClosed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "时区更新失败。");
    } finally {
      setSavingTimeZone(false);
    }
  }

  async function createReminder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.eventAt) {
      setError("请设置事件日期和时间。");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    idempotencyKey.current ??= window.crypto.randomUUID();
    try {
      await apiRequest<Reminder>("/api/v1/reminders", {
        method: "POST",
        body: JSON.stringify({
          job_id: draft.jobId || null,
          title: draft.title,
          details: draft.details || null,
          kind: draft.kind,
          event_at: localDateTimeToIso(draft.eventAt, timeZone),
          timezone: timeZone,
          lead_minutes: draft.leadMinutes,
          channel: "in_app",
          idempotency_key: idempotencyKey.current,
        }),
      });
      idempotencyKey.current = null;
      setDraft((current) => ({ ...current, title: "", details: "" }));
      setNotice("提醒已保存，站内通知将在设定时间生成。");
      setCreateOpened(false);
      await loadCenter(includeClosed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提醒保存失败。");
    } finally {
      setSaving(false);
    }
  }

  async function runAction(
    reminder: Reminder,
    action: "complete" | "cancel" | "pause" | "resume" | "snooze" | "retry",
    delayMinutes?: number,
  ) {
    setBusyId(reminder.id);
    setLastActionId(reminder.id);
    setError("");
    setNotice("");
    try {
      await apiRequest<Reminder>(`/api/v1/reminders/${reminder.id}/${action}`, {
        method: "POST",
        ...(action === "snooze"
          ? { body: JSON.stringify({ delay_minutes: delayMinutes }) }
          : {}),
      });
      setNotice(
        action === "complete"
          ? "提醒已完成。"
          : action === "cancel"
            ? "提醒已取消。"
            : action === "pause"
              ? "提醒已暂停。"
              : action === "resume"
                ? "提醒已恢复。"
                : action === "retry"
                  ? "已安排立即重试。"
                  : "提醒时间已延期。",
      );
      await loadCenter(includeClosed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提醒操作失败。");
    } finally {
      setBusyId(null);
    }
  }

  async function markRead(notificationId: string) {
    try {
      await apiRequest(`/api/v1/notifications/${notificationId}/read`, {
        method: "POST",
      });
      await loadCenter(includeClosed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法更新通知状态。");
    }
  }

  const groupedReminders = useMemo(() => {
    const groups = new Map<string, Reminder[]>();
    for (const reminder of [...(center?.reminders || [])].sort(
      (a, b) => Date.parse(a.event_at) - Date.parse(b.event_at),
    )) {
      const day = new Intl.DateTimeFormat("zh-CN", {
        timeZone: reminder.timezone,
        dateStyle: "full",
      }).format(new Date(reminder.event_at));
      groups.set(day, [...(groups.get(day) || []), reminder]);
    }
    return [...groups];
  }, [center]);

  return (
    <Stack gap="xl">
      <PageHeader
        title="提醒中心"
        description="掌握招聘节奏，让每一个重要日期都有安排。"
        actions={
          <Group>
            <Button component={Link} href="/agent" variant="default">
              用自然语言规划提醒
            </Button>
            <Button
              leftSection={<IconPlus size={17} />}
              onClick={() => {
                setError("");
                setCreateOpened(true);
              }}
            >
              新建提醒
            </Button>
          </Group>
        }
      />
      <Feedback error={error} notice={notice} requiresLogin={requiresLogin} />
      {loading && !center && <LoadingState />}
      {!loading && !center && error && !requiresLogin && (
        <Button
          variant="light"
          w="fit-content"
          onClick={() => void loadCenter(includeClosed)}
        >
          重新载入
        </Button>
      )}
      <Paper withBorder radius="lg" px="lg">
        <Accordion variant="default">
          <Accordion.Item value="timezone">
            <Accordion.Control icon={<IconWorld size={18} />}>
              账户时区：{timeZone}
            </Accordion.Control>
            <Accordion.Panel>
              <Stack gap="sm">
                <Text size="sm" c="dimmed">
                  修改时区将保留未来提醒的本地钟点，并重新计算触发时间。保存前会再次确认。
                </Text>
                <Group align="end">
                  <Autocomplete
                    id="reminder-timezone"
                    label="账户时区"
                    value={timeZoneDraft}
                    onChange={setTimeZoneDraft}
                    data={[
                      "Asia/Shanghai",
                      "Asia/Tokyo",
                      "Asia/Singapore",
                      "Europe/London",
                      "America/Los_Angeles",
                      "America/New_York",
                    ]}
                    style={{ flex: 1, minWidth: 200 }}
                  />
                  <Button
                    variant="light"
                    loading={savingTimeZone}
                    disabled={timeZoneDraft === timeZone}
                    onClick={() => void updateTimeZone()}
                  >
                    保存时区并重算
                  </Button>
                </Group>
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
      </Paper>
      {center && (
        <Tabs defaultValue="reminders" keepMounted={false}>
          <Tabs.List mb="lg">
            <Tabs.Tab value="reminders" leftSection={<IconClock size={17} />}>
              我的提醒
            </Tabs.Tab>
            <Tabs.Tab
              value="notifications"
              leftSection={<IconBell size={17} />}
              rightSection={
                center?.unread_count ? (
                  <Badge size="sm" circle>
                    {center.unread_count}
                  </Badge>
                ) : undefined
              }
            >
              站内通知
            </Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="reminders">
            <Stack gap="lg">
              <Group justify="space-between">
                <Text size="sm" c="dimmed">
                  按事件日期查看提醒与投递状态
                </Text>
                <Switch
                  label="显示已完成/取消"
                  checked={includeClosed}
                  onChange={(event) => {
                    const closed = event.currentTarget.checked;
                    setIncludeClosed(closed);
                    void loadCenter(closed);
                  }}
                />
              </Group>
              {loading ? (
                <LoadingState />
              ) : groupedReminders.length ? (
                groupedReminders.map(([day, reminders]) => (
                  <section className={classes.dateGroup} key={day}>
                    <Title order={2} size="h4">
                      {day}
                    </Title>
                    {reminders.map((reminder) => {
                      const closed =
                        reminder.status === "completed" ||
                        reminder.status === "cancelled";
                      return (
                        <Paper
                          component="article"
                          withBorder
                          radius="lg"
                          p="lg"
                          key={reminder.id}
                        >
                          <Stack gap="md">
                            <Group
                              justify="space-between"
                              align="flex-start"
                              wrap="nowrap"
                            >
                              <div className={classes.break}>
                                <Title order={3} size="h4">
                                  {reminder.title}
                                </Title>
                                <Text size="sm" c="dimmed" mt={4}>
                                  {REMINDER_KIND_LABELS[reminder.kind]}
                                  {reminder.job_label
                                    ? ` / ${reminder.job_label}`
                                    : ""}
                                </Text>
                              </div>
                              <StatusBadge
                                status={reminder.status}
                                label={REMINDER_STATUS_LABELS[reminder.status]}
                              />
                            </Group>
                            <div className={classes.timeGrid}>
                              <div>
                                <Text size="xs" c="dimmed">
                                  事件时间
                                </Text>
                                <Text size="sm" fw={500}>
                                  {formatDate(
                                    reminder.event_at,
                                    reminder.timezone,
                                  )}
                                </Text>
                              </div>
                              <div>
                                <Text size="xs" c="dimmed">
                                  下次通知
                                </Text>
                                <Text size="sm">
                                  {formatDate(
                                    reminder.notify_at,
                                    reminder.timezone,
                                  )}
                                </Text>
                              </div>
                            </div>
                            <Group gap="xs">
                              <Badge variant="light" color="gray">
                                {leadLabel(reminder.lead_minutes)}
                              </Badge>
                              <Text size="xs" c="dimmed">
                                {reminder.timezone}
                              </Text>
                            </Group>
                            {reminder.details && (
                              <Text
                                size="sm"
                                style={{ whiteSpace: "pre-wrap" }}
                              >
                                {reminder.details}
                              </Text>
                            )}
                            {error && lastActionId === reminder.id && (
                              <Alert color="red">{error}</Alert>
                            )}
                            {reminder.last_delivery_error && (
                              <Alert color="orange">
                                {reminder.last_delivery_error}（失败尝试{" "}
                                {reminder.delivery_attempts} 次）
                              </Alert>
                            )}
                            {!closed && (
                              <Group justify="end">
                                <Button
                                  size="sm"
                                  variant="light"
                                  leftSection={<IconCheck size={15} />}
                                  disabled={busyId === reminder.id}
                                  onClick={() =>
                                    void runAction(reminder, "complete")
                                  }
                                >
                                  完成
                                </Button>
                                <Menu position="bottom-end" shadow="md">
                                  <Menu.Target>
                                    <Button
                                      size="sm"
                                      variant="default"
                                      leftSection={<IconDots size={16} />}
                                      disabled={busyId === reminder.id}
                                    >
                                      更多操作
                                    </Button>
                                  </Menu.Target>
                                  <Menu.Dropdown>
                                    {reminder.last_delivery_error && (
                                      <Menu.Item
                                        onClick={() =>
                                          void runAction(reminder, "retry")
                                        }
                                      >
                                        立即重试
                                      </Menu.Item>
                                    )}
                                    {reminder.status === "scheduled" && (
                                      <Menu.Item
                                        onClick={() =>
                                          void runAction(reminder, "pause")
                                        }
                                      >
                                        暂停
                                      </Menu.Item>
                                    )}
                                    {reminder.status === "paused" && (
                                      <Menu.Item
                                        onClick={() =>
                                          void runAction(reminder, "resume")
                                        }
                                      >
                                        恢复
                                      </Menu.Item>
                                    )}
                                    {reminder.status !== "paused" && (
                                      <>
                                        <Menu.Item
                                          onClick={() =>
                                            void runAction(
                                              reminder,
                                              "snooze",
                                              60,
                                            )
                                          }
                                        >
                                          延后 1 小时
                                        </Menu.Item>
                                        <Menu.Item
                                          onClick={() =>
                                            void runAction(
                                              reminder,
                                              "snooze",
                                              1440,
                                            )
                                          }
                                        >
                                          延后 1 天
                                        </Menu.Item>
                                      </>
                                    )}
                                    <Menu.Divider />
                                    <Menu.Item
                                      color="red"
                                      onClick={() =>
                                        void runAction(reminder, "cancel")
                                      }
                                    >
                                      取消
                                    </Menu.Item>
                                  </Menu.Dropdown>
                                </Menu>
                              </Group>
                            )}
                          </Stack>
                        </Paper>
                      );
                    })}
                  </section>
                ))
              ) : (
                <EmptyState
                  title="还没有提醒"
                  description="添加一个网申截止、测评或面试提醒，重要日期会按时出现在这里。"
                  action={
                    <Button
                      onClick={() => {
                        setError("");
                        setCreateOpened(true);
                      }}
                    >
                      新建提醒
                    </Button>
                  }
                />
              )}
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="notifications">
            <Stack gap="md">
              <Group justify="space-between">
                <Text size="sm" c="dimmed">
                  {center?.unread_count ?? 0} 条未读，最多展示最近 50 条
                </Text>
                <Button
                  variant="subtle"
                  disabled={loading}
                  onClick={() => void loadCenter(includeClosed)}
                >
                  刷新
                </Button>
              </Group>
              {center?.notifications.length ? (
                center.notifications.map((notification) => (
                  <Paper withBorder radius="lg" p="lg" key={notification.id}>
                    <Group justify="space-between" align="start">
                      <Stack gap="xs" className={classes.break}>
                        <Group>
                          <Text fw={600}>{notification.title}</Text>
                          {!notification.read_at && (
                            <Badge size="sm">未读</Badge>
                          )}
                        </Group>
                        <Text size="sm">{notification.body}</Text>
                        <Text size="xs" c="dimmed">
                          {formatDate(notification.created_at, timeZone)}
                        </Text>
                      </Stack>
                      {!notification.read_at && (
                        <Button
                          size="xs"
                          variant="light"
                          onClick={() => void markRead(notification.id)}
                        >
                          标为已读
                        </Button>
                      )}
                    </Group>
                  </Paper>
                ))
              ) : (
                <EmptyState
                  title="还没有站内通知"
                  description="提醒送达后会出现在这里。"
                />
              )}
            </Stack>
          </Tabs.Panel>
        </Tabs>
      )}
      <Drawer
        opened={createOpened}
        onClose={() => setCreateOpened(false)}
        title="新建提醒"
        position="right"
        size="lg"
      >
        {error && (
          <Alert color="red" mb="md">
            {error}
          </Alert>
        )}
        <form onSubmit={createReminder}>
          <Stack gap="md">
            <TextInput
              label="提醒事项"
              maxLength={200}
              required
              value={draft.title}
              onChange={(event) =>
                updateDraft({ title: event.currentTarget.value })
              }
              placeholder="例如：星河科技网申截止"
            />
            <Select
              label="类型"
              value={draft.kind}
              onChange={(value) =>
                updateDraft({
                  kind: (value || "other") as ReminderDraft["kind"],
                })
              }
              data={REMINDER_KINDS.map(([value, label]) => ({ value, label }))}
              allowDeselect={false}
            />
            <Select
              label="关联岗位"
              clearable
              searchable
              value={draft.jobId || null}
              onChange={(value) => updateDraft({ jobId: value || "" })}
              placeholder="不关联岗位"
              data={jobs.map((job) => ({
                value: job.id,
                label:
                  [job.company_name, job.title].filter(Boolean).join(" / ") ||
                  "未命名岗位",
              }))}
            />
            <DateTimePicker
              label="事件时间"
              required
              value={draft.eventAt ? draft.eventAt.replace("T", " ") : null}
              onChange={(value) =>
                updateDraft({
                  eventAt: value ? value.replace(" ", "T").slice(0, 16) : "",
                })
              }
              valueFormat="YYYY-MM-DD HH:mm"
              description={`事件时区：${timeZone}`}
            />
            <Select
              label="提前提醒"
              value={String(draft.leadMinutes)}
              onChange={(value) =>
                updateDraft({ leadMinutes: Number(value || 0) })
              }
              data={[
                { value: "0", label: "事件发生时" },
                { value: "15", label: "提前 15 分钟" },
                { value: "60", label: "提前 1 小时" },
                { value: "1440", label: "提前 1 天" },
                { value: "10080", label: "提前 7 天" },
              ]}
              allowDeselect={false}
            />
            <Textarea
              label="备注"
              maxLength={2000}
              minRows={3}
              autosize
              value={draft.details}
              onChange={(event) =>
                updateDraft({ details: event.currentTarget.value })
              }
              placeholder="测评链接、面试联系人或准备事项"
            />
            <Button type="submit" loading={saving}>
              保存提醒
            </Button>
            <Text size="xs" c="dimmed">
              保存后由后台任务按时生成站内通知。
            </Text>
          </Stack>
        </form>
      </Drawer>
    </Stack>
  );
}
