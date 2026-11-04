"use client";

import Link from "next/link";
import { Alert, Anchor, Avatar, Badge, Button, Divider, Group, Paper, PasswordInput, Stack, Tabs, Text, TextInput, ThemeIcon, Title } from "@mantine/core";
import { IconCloudDownload, IconCpu, IconDatabase, IconKey, IconShieldLock, IconTrash, IconUser } from "@tabler/icons-react";
import { Feedback, LoadingState, PageHeader } from "@/components/ui";
import { useConfirm } from "@/lib/use-confirm";
import classes from "./page.module.css";
import { useEffect, useState } from "react";
import {
  ApiError,
  apiRequest,
  type User,
  type UserModelSettings,
  type UserModelSettingsWrite,
} from "@/lib/api";

export default function SettingsPage() {
  const confirm = useConfirm();
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
    if (!await confirm({ title: "永久删除账户", message: "确定永久删除账户和全部求职数据吗？此操作会删除简历原文件、业务记录、Agent 运行记录、提醒、通知与 RAG 索引，且无法撤销。", confirmLabel: "永久删除账户", danger: true })) return;

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
    <Stack gap="lg">
      <PageHeader title="设置与数据控制" description="管理账户模型服务、查看偏好，并控制自己的求职数据。" />
      <Feedback error={error} notice={notice} requiresLogin={requiresLogin} />
      {loading ? <LoadingState /> : user && <Tabs defaultValue="models" keepMounted>
        <Tabs.List mb="lg"><Tabs.Tab value="models" leftSection={<IconCpu size={17} />}>模型与集成</Tabs.Tab><Tabs.Tab value="account" leftSection={<IconUser size={17} />}>账户信息</Tabs.Tab><Tabs.Tab value="data" leftSection={<IconDatabase size={17} />}>数据控制</Tabs.Tab></Tabs.List>
        <Tabs.Panel value="models"><Stack gap="lg">
          <Alert icon={<IconShieldLock size={20} />} variant="light" title="密钥仅在服务端加密保存">API Key 不会回显。输入框留空会保留现有密钥；服务地址由部署者配置。Tavily 搜索和 SMTP 使用部署级配置。</Alert>
          {modelSettings && <form onSubmit={(event) => void saveModelSettings(event)}>
            <div className={classes.providerGrid}>
              <Paper withBorder radius="lg" p="lg" aria-label="Chat Completions 设置"><Stack gap="md">
                <Group justify="space-between"><Group gap="sm"><ThemeIcon variant="light" radius="md"><IconCpu size={19} /></ThemeIcon><Title order={3}>Chat Completions</Title></Group><Badge color={modelSettings.chat_completions.ready ? "teal" : "yellow"} variant="light">{modelSettings.chat_completions.ready ? "可用" : "待配置"}</Badge></Group>
                <Text c="dimmed" size="sm">用于岗位提取、任务计划、问答与求职材料草稿。</Text>
                <div className={classes.modelStatus}><Text size="xs" c="dimmed">服务地址</Text><Text size="sm">{modelSettings.chat_completions.endpoint_configured ? "已由部署者配置" : "部署者尚未配置"}</Text><Text size="xs" c="dimmed" mt="sm">当前模型</Text><Text size="sm" className={classes.modelName}>{modelSettings.chat_completions.effective_model || "部署者尚未配置"}</Text><Text size="xs" c="dimmed" mt="sm">凭据来源</Text><Text size="sm">{credentialStatus("chat_completions")}</Text></div>
                <PasswordInput id="settings-llm-key" label="替换账户 API Key" autoComplete="new-password" value={llmApiKey} placeholder={modelSettings.chat_completions.credential_source === "account" ? "已保存；输入新 Key 可替换" : "粘贴服务商 API Key"} onChange={(event) => { setLlmApiKey(event.currentTarget.value); setClearLlmKey(false); }} />
                <TextInput id="settings-llm-model" label="模型名称覆盖（可选）" value={llmModel} placeholder={`使用部署默认：${modelSettings.chat_completions.default_model || "未配置"}`} onChange={(event) => setLlmModel(event.currentTarget.value)} />
                {clearLlmKey ? <Alert color="yellow">保存后将移除账户 Key。<Button variant="subtle" size="compact-xs" onClick={() => setClearLlmKey(false)}>撤销移除</Button></Alert> : modelSettings.chat_completions.credential_source === "account" && <Button variant="subtle" color="red" size="compact-sm" onClick={() => { setClearLlmKey(true); setLlmApiKey(""); }}>移除账户 Key，改用部署默认值</Button>}
              </Stack></Paper>
              <Paper withBorder radius="lg" p="lg" aria-label="Embeddings 设置"><Stack gap="md">
                <Group justify="space-between"><Group gap="sm"><ThemeIcon variant="light" radius="md"><IconDatabase size={19} /></ThemeIcon><Title order={3}>Embeddings</Title></Group><Badge color={modelSettings.embeddings.ready ? "teal" : "yellow"} variant="light">{modelSettings.embeddings.ready ? "可用" : "待配置"}</Badge></Group>
                <Text c="dimmed" size="sm">用于简历和求职笔记的向量索引与语义检索。</Text>
                <div className={classes.modelStatus}><Text size="xs" c="dimmed">服务地址</Text><Text size="sm">{modelSettings.embeddings.endpoint_configured ? "已由部署者配置" : "部署者尚未配置"}</Text><Text size="xs" c="dimmed" mt="sm">当前模型</Text><Text size="sm" className={classes.modelName}>{modelSettings.embeddings.effective_model || "部署者尚未配置"}</Text><Text size="xs" c="dimmed" mt="sm">凭据来源</Text><Text size="sm">{credentialStatus("embeddings")}</Text></div>
                <PasswordInput id="settings-embedding-key" label="替换账户 API Key" autoComplete="new-password" value={embeddingApiKey} placeholder={modelSettings.embeddings.credential_source === "account" ? "已保存；输入新 Key 可替换" : "粘贴服务商 API Key"} onChange={(event) => { setEmbeddingApiKey(event.currentTarget.value); setClearEmbeddingKey(false); }} />
                <TextInput id="settings-embedding-model" label="模型名称覆盖（可选）" value={embeddingModel} placeholder={`使用部署默认：${modelSettings.embeddings.default_model || "未配置"}`} onChange={(event) => setEmbeddingModel(event.currentTarget.value)} />
                {clearEmbeddingKey ? <Alert color="yellow">保存后将移除账户 Key。<Button variant="subtle" size="compact-xs" onClick={() => setClearEmbeddingKey(false)}>撤销移除</Button></Alert> : modelSettings.embeddings.credential_source === "account" && <Button variant="subtle" color="red" size="compact-sm" onClick={() => { setClearEmbeddingKey(true); setEmbeddingApiKey(""); }}>移除账户 Key，改用部署默认值</Button>}
              </Stack></Paper>
            </div>
            <Group justify="flex-end" mt="lg"><Button type="submit" loading={savingModels} leftSection={<IconKey size={17} />}>保存模型设置</Button></Group>
          </form>}
        </Stack></Tabs.Panel>
        <Tabs.Panel value="account"><Paper withBorder radius="lg" p={{ base: "md", sm: "xl" }} className={classes.accountPanel}>
          <Group mb="xl"><Avatar size={54} radius="xl" color="teal">{user.email.slice(0, 1).toUpperCase()}</Avatar><div><Title order={3}>当前账户</Title><Text c="dimmed" size="sm" mt={4}>{user.email}</Text></div></Group>
          <Stack gap="lg"><div><Text c="dimmed" size="sm">账户时区</Text><Text mt={4}>{user.timezone}</Text><Anchor component={Link} href="/reminders" size="sm">在提醒中心修改时区</Anchor></div><Divider /><div><Text c="dimmed" size="sm">通知渠道</Text><Text mt={4}>站内通知</Text><Anchor component={Link} href="/reminders" size="sm">前往提醒中心</Anchor></div><Divider /><div><Text c="dimmed" size="sm">注册时间</Text><Text mt={4}>{new Date(user.created_at).toLocaleDateString("zh-CN")}</Text></div></Stack>
        </Paper></Tabs.Panel>
        <Tabs.Panel value="data"><Stack gap="lg" className={classes.dataPanel}>
          <Paper withBorder radius="lg" p="xl"><Group gap="sm" mb="md"><ThemeIcon variant="light" radius="md"><IconCloudDownload size={20} /></ThemeIcon><Title order={3}>下载账户数据</Title></Group><Text size="sm" c="dimmed" mb="lg">导出包包含账户资料、简历解析文本、岗位与投递记录、提醒、笔记、Agent 任务和检索片段；仍保存在服务器的 PDF/DOCX 原件也会打包。向量数值和服务密钥不会导出。</Text><Button variant="light" loading={exporting} leftSection={<IconCloudDownload size={17} />} onClick={() => void exportData()}>下载数据 ZIP</Button></Paper>
          <Paper withBorder radius="lg" p="xl" className={classes.dangerPanel}><Group gap="sm" mb="md"><ThemeIcon color="red" variant="light" radius="md"><IconTrash size={20} /></ThemeIcon><Title order={3}>删除账户和全部数据</Title></Group><Text size="sm" c="dimmed" mb="lg">此操作会删除账户、业务记录、简历文件、Agent 运行记录、提醒、通知和 RAG 检索索引，并退出登录。删除后无法恢复。</Text><form onSubmit={(event) => void deleteAccount(event)}><Stack gap="md"><TextInput id="settings-confirm-email" label="输入账户邮箱以确认" autoComplete="email" required type="email" value={emailConfirmation} onChange={(event) => setEmailConfirmation(event.currentTarget.value)} /><PasswordInput id="settings-confirm-password" label="当前密码" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.currentTarget.value)} /><Group justify="flex-end"><Button color="red" variant="light" loading={deleting} disabled={!password || !emailConfirmation} leftSection={<IconTrash size={16} />} type="submit">永久删除账户</Button></Group></Stack></form></Paper>
        </Stack></Tabs.Panel>
      </Tabs>}
    </Stack>
  );
}
