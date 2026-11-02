"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, apiRequest, type User } from "@/lib/api";

export default function SettingsPage() {
  const [user, setUser] = useState<User | null>(null);
  const [emailConfirmation, setEmailConfirmation] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);

  useEffect(() => {
    apiRequest<User>("/api/v1/auth/me")
      .then(setUser)
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "无法载入账户设置。");
        setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      })
      .finally(() => setLoading(false));
  }, []);

  async function exportData() {
    setExporting(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/v1/account/export", { credentials: "include" });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
        if (response.status === 401) setRequiresLogin(true);
        throw new Error(typeof body?.detail === "string" ? body.detail : "导出失败，请稍后重试。");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "offerpilot-data-export.zip";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("导出文件已生成，包含账户业务数据和仍保存在服务器上的简历原文件。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导出失败，请稍后重试。");
      if (cause instanceof ApiError && cause.status === 401) setRequiresLogin(true);
    } finally {
      setExporting(false);
    }
  }

  async function deleteAccount(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!user || emailConfirmation.trim().toLowerCase() !== user.email.toLowerCase()) {
      setError("请输入与当前账户完全一致的邮箱地址。");
      return;
    }
    if (!window.confirm("确定永久删除账户和全部求职数据吗？此操作无法撤销。")) return;

    setDeleting(true);
    setError("");
    try {
      await apiRequest("/api/v1/account/me", {
        method: "DELETE",
        body: JSON.stringify({ current_password: password, confirmation_email: emailConfirmation.trim() }),
      });
      window.location.assign("/login?account=deleted");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "账户删除失败，请稍后重试。");
      if (cause instanceof ApiError && cause.status === 401) setRequiresLogin(true);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <main className="settings-shell">
      <header className="dashboard-topbar settings-topbar">
        <Link className="brand" href="/dashboard"><span className="brand-mark">O</span> OfferPilot</Link>
        <nav className="dashboard-actions" aria-label="主导航">
          <Link className="text-link" href="/dashboard">工作台</Link>
          <Link className="text-link" href="/profile">个人档案</Link>
          <Link className="text-link" href="/reminders">提醒中心</Link>
        </nav>
      </header>

      <section className="settings-heading">
        <p className="eyebrow">账户设置</p>
        <h1>设置与数据控制</h1>
        <p>查看账户运行设置，导出你保存的求职资料，或删除账户及其数据。</p>
      </section>

      {error && <div className="profile-message profile-error" role="alert">{error}{requiresLogin && <> <Link href="/login">去登录</Link></>}</div>}
      {notice && <div className="profile-message profile-success" role="status">{notice}</div>}
      {loading ? <p className="profile-loading">正在载入账户设置…</p> : user && (
        <>
          <section className="profile-panel settings-panel">
            <p className="eyebrow">账户</p>
            <h2>当前账户</h2>
            <dl className="settings-account-data">
              <div><dt>邮箱</dt><dd>{user.email}</dd></div>
              <div><dt>账户时区</dt><dd>{user.timezone} · 在<Link href="/reminders">提醒中心</Link>修改</dd></div>
              <div><dt>通知渠道</dt><dd>站内通知 · 在提醒中心查看</dd></div>
            </dl>
          </section>

          <section className="profile-panel settings-panel">
            <p className="eyebrow">服务配置</p>
            <h2>模型与搜索服务</h2>
            <p>LLM、Embedding 和 Tavily 等服务由部署者在后端环境变量中配置。网页不会读取或显示 API 密钥，也不会把密钥放入个人数据导出包。</p>
            <p className="settings-subtle">本地部署可在 <code>backend/.env</code> 管理配置；修改后按 README 重启 API。</p>
          </section>

          <section className="profile-panel settings-panel">
            <p className="eyebrow">数据导出</p>
            <h2>下载账户数据</h2>
            <p>导出包包含账户资料、简历解析文本、岗位与投递记录、提醒、笔记、Agent 任务和检索片段；仍存在服务器上的 PDF/DOCX 简历原件也会一起打包。向量数值和服务密钥不导出。</p>
            <button className="button button-secondary" disabled={exporting} onClick={() => void exportData()} type="button">
              {exporting ? "正在准备导出…" : "下载数据 ZIP"}
            </button>
          </section>

          <section className="profile-panel settings-panel settings-danger-panel">
            <p className="eyebrow">不可撤销</p>
            <h2>删除账户和全部数据</h2>
            <p>此操作会删除账户、业务记录、简历文件、Agent 运行记录、提醒、通知和 RAG 检索索引，并退出登录。</p>
            <form className="settings-delete-form" onSubmit={(event) => void deleteAccount(event)}>
              <label htmlFor="settings-confirm-email">输入账户邮箱以确认</label>
              <input id="settings-confirm-email" autoComplete="email" required type="email" value={emailConfirmation} onChange={(event) => setEmailConfirmation(event.target.value)} />
              <label htmlFor="settings-confirm-password">当前密码</label>
              <input id="settings-confirm-password" autoComplete="current-password" required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
              <button className="button settings-delete-button" disabled={deleting || !password || !emailConfirmation} type="submit">
                {deleting ? "正在删除账户…" : "永久删除账户"}
              </button>
            </form>
          </section>
        </>
      )}
    </main>
  );
}
