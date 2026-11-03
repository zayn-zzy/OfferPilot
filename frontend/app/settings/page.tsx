"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  apiRequest,
  type User,
  type UserModelSettings,
  type UserModelSettingsWrite,
} from "@/lib/api";

export default function SettingsPage() {
  const [user, setUser] = useState<User | null>(null);
  const [modelSettings, setModelSettings] = useState<UserModelSettings | null>(null);
  const [llmApiKey, setLlmApiKey] = useState("");
  const [embeddingApiKey, setEmbeddingApiKey] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [clearLlmKey, setClearLlmKey] = useState(false);
  const [clearEmbeddingKey, setClearEmbeddingKey] = useState(false);
  const [savingModels, setSavingModels] = useState(false);
  const [emailConfirmation, setEmailConfirmation] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);

  useEffect(() => {
    Promise.all([
      apiRequest<User>("/api/v1/auth/me"),
      apiRequest<UserModelSettings>("/api/v1/settings/models"),
    ])
      .then(([currentUser, configuredModels]) => {
        setUser(currentUser);
        setModelSettings(configuredModels);
        setLlmModel(configuredModels.chat_completions.model_override ?? "");
        setEmbeddingModel(configuredModels.embeddings.model_override ?? "");
      })
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "无法载入账户设置。");
        setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      })
      .finally(() => setLoading(false));
  }, []);

  async function saveModelSettings(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!modelSettings) return;
    setSavingModels(true);
    setError("");
    setNotice("");

    const update: UserModelSettingsWrite = {};
    if (llmApiKey.trim()) update.llm_api_key = llmApiKey;
    if (embeddingApiKey.trim()) update.embedding_api_key = embeddingApiKey;
    if (clearLlmKey) update.clear_llm_api_key = true;
    if (clearEmbeddingKey) update.clear_embedding_api_key = true;

    const previousLlmModel = modelSettings.chat_completions.model_override ?? "";
    if (llmModel.trim() && llmModel.trim() !== previousLlmModel) {
      update.llm_model = llmModel.trim();
    } else if (!llmModel.trim() && previousLlmModel) {
      update.clear_llm_model = true;
    }
    const previousEmbeddingModel = modelSettings.embeddings.model_override ?? "";
    if (embeddingModel.trim() && embeddingModel.trim() !== previousEmbeddingModel) {
      update.embedding_model = embeddingModel.trim();
    } else if (!embeddingModel.trim() && previousEmbeddingModel) {
      update.clear_embedding_model = true;
    }

    try {
      const saved = await apiRequest<UserModelSettings>("/api/v1/settings/models", {
        method: "PUT",
        body: JSON.stringify(update),
      });
      setModelSettings(saved);
      setLlmApiKey("");
      setEmbeddingApiKey("");
      setLlmModel(saved.chat_completions.model_override ?? "");
      setEmbeddingModel(saved.embeddings.model_override ?? "");
      setClearLlmKey(false);
      setClearEmbeddingKey(false);
      setNotice("模型设置已保存。API Key 只在服务端加密保存，不会再次显示。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "模型设置保存失败，请稍后重试。");
      if (cause instanceof ApiError && cause.status === 401) setRequiresLogin(true);
    } finally {
      setSavingModels(false);
    }
  }

  function credentialStatus(provider: "chat_completions" | "embeddings") {
    const source = modelSettings?.[provider].credential_source;
    if (source === "account") return "已保存账户 API Key";
    if (source === "deployment") return "使用部署者提供的默认 API Key";
    if (source === "unavailable") return "已保存的 Key 无法解密，请重新输入";
    return "未配置 API Key";
  }

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
            <p>你可以为当前账户设置 Chat Completions 和 Embeddings API Key。密钥只提交到后端并加密保存；页面和 API 都不会回显密钥。留空表示保持现有密钥，或继续使用部署默认密钥。</p>
            <p className="settings-subtle">服务地址由部署者在后端配置。Tavily 搜索和 SMTP 仍使用部署级配置。</p>
            {modelSettings && (
              <form className="settings-model-form" onSubmit={(event) => void saveModelSettings(event)}>
                <div className="settings-model-provider">
                  <div className="settings-model-heading">
                    <div>
                      <h3>Chat Completions</h3>
                      <p>{modelSettings.chat_completions.ready ? "可用于岗位抽取、Agent 与问答" : "尚未完整配置"}</p>
                    </div>
                    <span className="settings-model-state">{credentialStatus("chat_completions")}</span>
                  </div>
                  <dl className="settings-model-data">
                    <div><dt>服务地址</dt><dd>{modelSettings.chat_completions.endpoint_configured ? "已由部署者配置" : "部署者尚未配置"}</dd></div>
                    <div><dt>当前模型</dt><dd>{modelSettings.chat_completions.effective_model || "部署者尚未配置"}</dd></div>
                  </dl>
                  <label htmlFor="settings-llm-key">替换账户 API Key</label>
                  <input
                    id="settings-llm-key"
                    autoComplete="new-password"
                    type="password"
                    value={llmApiKey}
                    placeholder={modelSettings.chat_completions.credential_source === "account" ? "已保存；输入新 Key 可替换" : "粘贴服务商 API Key"}
                    onChange={(event) => { setLlmApiKey(event.target.value); setClearLlmKey(false); }}
                  />
                  <label htmlFor="settings-llm-model">模型名称覆盖（可选）</label>
                  <input
                    id="settings-llm-model"
                    value={llmModel}
                    placeholder={`使用部署默认：${modelSettings.chat_completions.default_model || "未配置"}`}
                    onChange={(event) => setLlmModel(event.target.value)}
                  />
                  {modelSettings.chat_completions.credential_source === "account" && (
                    <button className="settings-clear-secret" type="button" onClick={() => { setClearLlmKey(true); setLlmApiKey(""); }}>
                      移除账户 Key，改用部署默认值
                    </button>
                  )}
                </div>

                <div className="settings-model-provider">
                  <div className="settings-model-heading">
                    <div>
                      <h3>Embeddings</h3>
                      <p>{modelSettings.embeddings.ready ? "可用于资料索引和检索" : "尚未完整配置"}</p>
                    </div>
                    <span className="settings-model-state">{credentialStatus("embeddings")}</span>
                  </div>
                  <dl className="settings-model-data">
                    <div><dt>服务地址</dt><dd>{modelSettings.embeddings.endpoint_configured ? "已由部署者配置" : "部署者尚未配置"}</dd></div>
                    <div><dt>当前模型</dt><dd>{modelSettings.embeddings.effective_model || "部署者尚未配置"}</dd></div>
                  </dl>
                  <label htmlFor="settings-embedding-key">替换账户 API Key</label>
                  <input
                    id="settings-embedding-key"
                    autoComplete="new-password"
                    type="password"
                    value={embeddingApiKey}
                    placeholder={modelSettings.embeddings.credential_source === "account" ? "已保存；输入新 Key 可替换" : "粘贴服务商 API Key"}
                    onChange={(event) => { setEmbeddingApiKey(event.target.value); setClearEmbeddingKey(false); }}
                  />
                  <label htmlFor="settings-embedding-model">模型名称覆盖（可选）</label>
                  <input
                    id="settings-embedding-model"
                    value={embeddingModel}
                    placeholder={`使用部署默认：${modelSettings.embeddings.default_model || "未配置"}`}
                    onChange={(event) => setEmbeddingModel(event.target.value)}
                  />
                  {modelSettings.embeddings.credential_source === "account" && (
                    <button className="settings-clear-secret" type="button" onClick={() => { setClearEmbeddingKey(true); setEmbeddingApiKey(""); }}>
                      移除账户 Key，改用部署默认值
                    </button>
                  )}
                </div>
                <button className="button button-primary" disabled={savingModels} type="submit">
                  {savingModels ? "正在保存…" : "保存模型设置"}
                </button>
              </form>
            )}
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
