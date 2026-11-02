"use client";

import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest, type JobPosting, type Reminder, type ReminderCenter, type User, type UserTimezoneUpdate } from "@/lib/api";

const REMINDER_KINDS = [
  ["opening", "招聘开放日"],
  ["deadline", "网申截止"],
  ["assessment", "测评"],
  ["interview", "面试"],
  ["follow_up", "跟进"],
  ["other", "其他"],
] as const;

const REMINDER_KIND_LABELS = Object.fromEntries(REMINDER_KINDS) as Record<string, string>;
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
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function localDateTimeToIso(value: string, timeZone: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) throw new Error("请填写有效的事件日期和时间。");
  const [, year, month, day, hour, minute] = match;
  const wallTime = Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute));
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
    const parts = Object.fromEntries(formatter.formatToParts(new Date(guess)).map((part) => [part.type, part.value]));
    const represented = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute));
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
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const idempotencyKey = useRef<string | null>(null);

  async function loadCenter(closed = includeClosed) {
    setLoading(true);
    setError("");
    try {
      setCenter(await apiRequest<ReminderCenter>(`/api/v1/reminders?include_closed=${closed}`));
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
      eventAt: formatLocalDateTime(new Date(Date.now() + 24 * 60 * 60 * 1000), "Asia/Shanghai"),
    }));
    void loadCenter(false);
    apiRequest<User>("/api/v1/auth/me")
      .then((user) => {
        setTimeZone(user.timezone);
        setTimeZoneDraft(user.timezone);
        setDraft((current) => ({
          ...current,
          eventAt: formatLocalDateTime(new Date(Date.now() + 24 * 60 * 60 * 1000), user.timezone),
        }));
      })
      .catch(() => undefined);
    apiRequest<JobPosting[]>("/api/v1/jobs").then(setJobs).catch(() => setJobs([]));
    // Load once on mount. The filter has its own explicit reload action.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updateDraft(change: Partial<ReminderDraft>) {
    idempotencyKey.current = null;
    setDraft((current) => ({ ...current, ...change }));
  }

  async function updateTimeZone() {
    if (timeZoneDraft === timeZone) return;
    const accepted = window.confirm(
      `将时区从 ${timeZone} 改为 ${timeZoneDraft}。未来提醒会保留原来的本地钟点，并重新计算 UTC 触发时间。是否继续？`,
    );
    if (!accepted) return;
    setSavingTimeZone(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<UserTimezoneUpdate>("/api/v1/auth/me/timezone", {
        method: "PUT",
        body: JSON.stringify({ timezone: timeZoneDraft, recalculate_future: true }),
      });
      setTimeZone(result.user.timezone);
      setTimeZoneDraft(result.user.timezone);
      setNotice(`时区已更新，已重算 ${result.recalculated_reminders} 条未来提醒。`);
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
      await loadCenter(includeClosed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提醒保存失败。");
    } finally {
      setSaving(false);
    }
  }

  async function runAction(reminder: Reminder, action: "complete" | "cancel" | "pause" | "resume" | "snooze" | "retry", delayMinutes?: number) {
    setBusyId(reminder.id);
    setError("");
    setNotice("");
    try {
      await apiRequest<Reminder>(`/api/v1/reminders/${reminder.id}/${action}`, {
        method: "POST",
        ...(action === "snooze" ? { body: JSON.stringify({ delay_minutes: delayMinutes }) } : {}),
      });
      setNotice(action === "complete" ? "提醒已完成。" : action === "cancel" ? "提醒已取消。" : action === "pause" ? "提醒已暂停。" : action === "resume" ? "提醒已恢复。" : action === "retry" ? "已安排立即重试。" : "提醒时间已延期。");
      await loadCenter(includeClosed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提醒操作失败。");
    } finally {
      setBusyId(null);
    }
  }

  async function markRead(notificationId: string) {
    try {
      await apiRequest(`/api/v1/notifications/${notificationId}/read`, { method: "POST" });
      await loadCenter(includeClosed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法更新通知状态。");
    }
  }

  async function logout() {
    await apiRequest("/api/v1/auth/logout", { method: "POST" });
    window.location.assign("/login");
  }

  return (
    <main className="reminders-shell">
      <header className="dashboard-topbar">
        <Link className="brand" href="/"><span className="brand-mark">O</span> OfferPilot</Link>
        <nav className="dashboard-actions" aria-label="主导航">
          <Link className="text-link" href="/dashboard">工作台</Link>
          <Link className="text-link" href="/profile">个人档案</Link>
          <Link className="text-link" href="/jobs">岗位管理</Link>
          <Link className="text-link" href="/skills">Agent Skills</Link>
          <Link className="text-link" href="/agent">任务规划</Link>
          <button className="text-button" onClick={() => void logout()} type="button">退出登录</button>
        </nav>
      </header>

      <section className="reminders-heading">
        <p className="eyebrow">招聘节奏</p>
        <h1>提醒中心</h1>
        <p>记录开放日、截止时间、测评和面试；目前仅发送站内通知。</p>
        <p><Link className="button button-secondary" href="/agent">用自然语言规划提醒</Link></p>
        <div className="reminder-timezone-setting"><label htmlFor="reminder-timezone">账户时区</label><input id="reminder-timezone" list="common-timezones" value={timeZoneDraft} onChange={(event) => setTimeZoneDraft(event.target.value)} /><datalist id="common-timezones"><option value="Asia/Shanghai" /><option value="Asia/Tokyo" /><option value="Asia/Singapore" /><option value="Europe/London" /><option value="America/Los_Angeles" /><option value="America/New_York" /></datalist><button className="button button-secondary" disabled={savingTimeZone || timeZoneDraft === timeZone} onClick={() => void updateTimeZone()} type="button">{savingTimeZone ? "重算中…" : "保存时区并重算"}</button><span>当前：{timeZone}</span></div>
      </section>

      {error && <div className="profile-message profile-error" role="alert">{error}{requiresLogin && <> <Link href="/login">去登录</Link></>}</div>}
      {notice && <div className="profile-message profile-success" role="status">{notice}</div>}

      <section className="reminder-create-panel" aria-labelledby="reminder-create-title">
        <div className="profile-panel-heading">
          <div><h2 id="reminder-create-title">新建提醒</h2><p>保存后由后台任务按时生成站内通知。</p></div>
          <span className="reminder-channel">站内通知</span>
        </div>
        <form className="reminder-form" onSubmit={createReminder}>
          <label>提醒事项<input maxLength={200} required value={draft.title} onChange={(event) => updateDraft({ title: event.target.value })} placeholder="例如：星河科技网申截止" /></label>
          <label>类型<select value={draft.kind} onChange={(event) => updateDraft({ kind: event.target.value as ReminderDraft["kind"] })}>{REMINDER_KINDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>关联岗位<select value={draft.jobId} onChange={(event) => updateDraft({ jobId: event.target.value })}><option value="">不关联岗位</option>{jobs.map((job) => <option key={job.id} value={job.id}>{[job.company_name, job.title].filter(Boolean).join(" · ") || "未命名岗位"}</option>)}</select></label>
          <label>事件时间<input required type="datetime-local" value={draft.eventAt} onChange={(event) => updateDraft({ eventAt: event.target.value })} /></label>
          <label>提前提醒<select value={draft.leadMinutes} onChange={(event) => updateDraft({ leadMinutes: Number(event.target.value) })}><option value={0}>事件发生时</option><option value={15}>提前 15 分钟</option><option value={60}>提前 1 小时</option><option value={1440}>提前 1 天</option><option value={10080}>提前 7 天</option></select></label>
          <label className="reminder-details-field">备注<textarea maxLength={2000} rows={2} value={draft.details} onChange={(event) => updateDraft({ details: event.target.value })} placeholder="测评链接、面试联系人或需要准备的事项" /></label>
          <div className="reminder-form-actions"><button className="button button-primary" disabled={saving} type="submit">{saving ? "保存中…" : "保存提醒"}</button><span>时区和日期会保存到提醒记录中</span></div>
        </form>
      </section>

      <section className="reminder-list-section">
        <div className="reminder-section-heading"><div><h2>我的提醒</h2><p>展示事件时间、后台触发时间和提醒状态。</p></div><label className="reminder-closed-toggle"><input checked={includeClosed} onChange={(event) => { setIncludeClosed(event.target.checked); void loadCenter(event.target.checked); }} type="checkbox" />显示已完成/取消</label></div>
        {loading ? <p className="empty-state">正在载入提醒…</p> : center?.reminders.length ? <div className="reminder-list">{center.reminders.map((reminder) => {
          const closed = reminder.status === "completed" || reminder.status === "cancelled";
          return <article className="reminder-card" key={reminder.id}>
            <div className="reminder-card-main"><div className="reminder-title-row"><h3>{reminder.title}</h3><span className={`reminder-status reminder-status-${reminder.status}`}>{REMINDER_STATUS_LABELS[reminder.status]}</span></div>
              <p className="reminder-meta">{REMINDER_KIND_LABELS[reminder.kind]}{reminder.job_label ? ` · ${reminder.job_label}` : ""}</p>
              <p className="reminder-time">事件：{formatDate(reminder.event_at, reminder.timezone)} · {leadLabel(reminder.lead_minutes)}</p>
              <p className="reminder-time">下次通知：{formatDate(reminder.notify_at, reminder.timezone)} · {reminder.timezone}</p>
              {reminder.details && <p className="reminder-details">{reminder.details}</p>}
              {reminder.last_delivery_error && <p className="form-error" role="status">{reminder.last_delivery_error}（失败尝试 {reminder.delivery_attempts} 次）</p>}
            </div>
            {!closed && <div className="reminder-actions">{reminder.last_delivery_error && <button disabled={busyId === reminder.id} onClick={() => void runAction(reminder, "retry")} type="button">立即重试</button>}{reminder.status === "scheduled" ? <button disabled={busyId === reminder.id} onClick={() => void runAction(reminder, "pause")} type="button">暂停</button> : reminder.status === "paused" ? <button disabled={busyId === reminder.id} onClick={() => void runAction(reminder, "resume")} type="button">恢复</button> : null}<button disabled={busyId === reminder.id} onClick={() => void runAction(reminder, "complete")} type="button">完成</button>{reminder.status !== "paused" && <><button disabled={busyId === reminder.id} onClick={() => void runAction(reminder, "snooze", 60)} type="button">延后 1 小时</button><button disabled={busyId === reminder.id} onClick={() => void runAction(reminder, "snooze", 1440)} type="button">延后 1 天</button></>}<button className="danger-text" disabled={busyId === reminder.id} onClick={() => void runAction(reminder, "cancel")} type="button">取消</button></div>}
          </article>;
        })}</div> : <p className="empty-state">还没有提醒。可以先添加一个网申截止、测评或面试提醒。</p>}
      </section>

      <section className="reminder-list-section notification-history">
        <div className="reminder-section-heading"><div><h2>站内通知</h2><p>{center?.unread_count ?? 0} 条未读；最多展示最近 50 条。</p></div><button className="job-quiet-action" disabled={loading} onClick={() => void loadCenter(includeClosed)} type="button">刷新</button></div>
        {center?.notifications.length ? <ul className="notification-list">{center.notifications.map((notification) => <li className={notification.read_at ? "notification-read" : "notification-unread"} key={notification.id}>
          <div><strong>{notification.title}</strong><p>{notification.body}</p><time>{formatDate(notification.created_at, timeZone)}</time></div>
          {!notification.read_at && <button onClick={() => void markRead(notification.id)} type="button">标为已读</button>}
        </li>)}</ul> : <p className="empty-state">通知送达后会出现在这里。</p>}
      </section>
    </main>
  );
}
