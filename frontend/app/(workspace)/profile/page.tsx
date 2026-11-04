"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Drawer, Group, NumberInput, Paper, ScrollArea, Stack, Tabs, TagsInput, Text, Textarea, TextInput, ThemeIcon, Title, UnstyledButton } from "@mantine/core";
import { Dropzone } from "@mantine/dropzone";
import { IconCheck, IconFileText, IconUpload, IconUser, IconFiles, IconTrash } from "@tabler/icons-react";
import { ApiError, apiRequest } from "@/lib/api";
import { EmptyState, Feedback, LoadingState, PageHeader } from "@/components/ui";
import { useConfirm } from "@/lib/use-confirm";
import classes from "./page.module.css";

type Profile = {
  graduation_year: number | null;
  education: string | null;
  major: string | null;
  target_roles: string[];
  target_cities: string[];
  industries: string[];
  skills: string[];
};

type ProfileDraft = {
  graduationYear: string;
  education: string;
  major: string;
  targetRoles: string;
  targetCities: string;
  industries: string;
  skills: string;
};

type ResumeSummary = {
  id: string;
  filename: string;
  source_type: "upload" | "paste";
  content_type: string;
  created_at: string;
  confirmed_at: string | null;
  extracted_char_count: number;
};

type ResumeDetail = ResumeSummary & { extracted_text: string };

const emptyDraft: ProfileDraft = {
  graduationYear: "",
  education: "",
  major: "",
  targetRoles: "",
  targetCities: "",
  industries: "",
  skills: "",
};

function joinValues(values: string[]) {
  return values.join(", ");
}

function splitValues(value: string) {
  return value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean);
}

function toDraft(profile: Profile): ProfileDraft {
  return {
    graduationYear: profile.graduation_year?.toString() ?? "",
    education: profile.education ?? "",
    major: profile.major ?? "",
    targetRoles: joinValues(profile.target_roles),
    targetCities: joinValues(profile.target_cities),
    industries: joinValues(profile.industries),
    skills: joinValues(profile.skills),
  };
}

export default function ProfilePage() {
  const confirm = useConfirm();
  const [draft, setDraft] = useState<ProfileDraft>(emptyDraft);
  const [resumes, setResumes] = useState<ResumeSummary[]>([]);
  const [preview, setPreview] = useState<ResumeDetail | null>(null);
  const [pasteText, setPasteText] = useState("");
  const [error, setError] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingResumeText, setSavingResumeText] = useState(false);
  const [uploadingResume, setUploadingResume] = useState(false);

  const loadData = useCallback(async () => {
    const [profile, versions] = await Promise.all([
      apiRequest<Profile>("/api/v1/profile"),
      apiRequest<ResumeSummary[]>("/api/v1/resumes"),
    ]);
    setDraft(toDraft(profile));
    setResumes(versions);
  }, []);

  useEffect(() => {
    loadData()
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "无法载入个人档案。");
        setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      })
      .finally(() => setLoading(false));
  }, [loadData]);

  function updateDraft(field: keyof ProfileDraft, value: string) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setRequiresLogin(false);
    setNotice("");
    setSavingProfile(true);
    const year = draft.graduationYear.trim();
    const payload = {
      graduation_year: year ? Number(year) : null,
      education: draft.education || null,
      major: draft.major || null,
      target_roles: splitValues(draft.targetRoles),
      target_cities: splitValues(draft.targetCities),
      industries: splitValues(draft.industries),
      skills: splitValues(draft.skills),
    };
    try {
      const saved = await apiRequest<Profile>("/api/v1/profile", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      setDraft(toDraft(saved));
      setNotice("个人档案已保存。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败，请重试。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setSavingProfile(false);
    }
  }

  async function uploadFile(file: File | null) {
    if (!file) return;

    setError("");
    setRequiresLogin(false);
    setNotice("");
    setUploadingResume(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const resume = await apiRequest<ResumeDetail>("/api/v1/resumes/upload", {
        method: "POST",
        body: formData,
      });
      setPreview(resume);
      await loadData();
      setNotice("简历已解析。检查预览后再确认使用。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "简历上传失败。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setUploadingResume(false);
    }
  }

  async function savePastedText(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setRequiresLogin(false);
    setNotice("");
    setSavingResumeText(true);
    try {
      const resume = await apiRequest<ResumeDetail>("/api/v1/resumes/text", {
        method: "POST",
        body: JSON.stringify({ text: pasteText }),
      });
      setPreview(resume);
      setPasteText("");
      await loadData();
      setNotice("简历文本已保存。检查预览后再确认使用。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "简历文本保存失败。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setSavingResumeText(false);
    }
  }

  async function showResume(id: string) {
    setError("");
    setRequiresLogin(false);
    try {
      setPreview(await apiRequest<ResumeDetail>(`/api/v1/resumes/${id}`));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法载入简历预览。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    }
  }

  async function confirmResume() {
    if (!preview) return;
    setError("");
    setRequiresLogin(false);
    try {
      setPreview(await apiRequest<ResumeDetail>(`/api/v1/resumes/${preview.id}/confirm`, { method: "POST" }));
      await loadData();
      setNotice("这份简历已由你确认，可在后续匹配功能中使用。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "确认失败，请重试。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    }
  }

  async function deleteResume() {
    if (!preview || !await confirm({ title: "删除简历版本", message: `删除“${preview.filename}”？相关检索片段也会一并删除。`, confirmLabel: "删除版本", danger: true })) return;
    setError("");
    setRequiresLogin(false);
    try {
      await apiRequest(`/api/v1/resumes/${preview.id}`, { method: "DELETE" });
      setPreview(null);
      await loadData();
      setNotice("简历版本已删除。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除失败，请重试。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    }
  }

  return (
    <Stack gap="lg">
      <PageHeader title="个人档案" description="管理求职偏好和简历。已确认的资料才会用于岗位匹配与材料准备。" />
      <Feedback error={error} notice={notice} requiresLogin={requiresLogin} />
      {loading ? <LoadingState /> : (
        <Tabs defaultValue="profile" keepMounted>
          <Tabs.List mb="lg">
            <Tabs.Tab value="profile" leftSection={<IconUser size={17} />}>基础资料</Tabs.Tab>
            <Tabs.Tab value="resumes" leftSection={<IconFiles size={17} />} rightSection={<Badge size="sm" variant="light">{resumes.length}</Badge>}>简历版本</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="profile">
            <Paper withBorder p={{ base: "md", sm: "xl" }} radius="lg">
              <form onSubmit={saveProfile}><Stack gap="lg">
                <div><Title order={3}>求职偏好与教育背景</Title><Text c="dimmed" size="sm" mt={5}>完善这些信息，让匹配分析更贴近你的选择。</Text></div>
                <div className={classes.formGrid}>
                  <NumberInput label="毕业年份" min={1980} max={2100} allowDecimal={false} allowNegative={false} value={draft.graduationYear} onChange={(value) => updateDraft("graduationYear", String(value))} placeholder="例如：2027" />
                  <TextInput label="学历" maxLength={100} value={draft.education} onChange={(event) => updateDraft("education", event.currentTarget.value)} placeholder="例如：硕士" />
                  <TextInput label="专业" maxLength={120} value={draft.major} onChange={(event) => updateDraft("major", event.currentTarget.value)} placeholder="例如：计算机科学与技术" />
                  <TagsInput label="目标岗位" description="输入后按回车，或使用逗号分隔" value={splitValues(draft.targetRoles)} onChange={(values) => updateDraft("targetRoles", values.join(", "))} splitChars={[",", "，"]} placeholder="例如：后端开发" />
                  <TagsInput label="目标城市" value={splitValues(draft.targetCities)} onChange={(values) => updateDraft("targetCities", values.join(", "))} splitChars={[",", "，"]} placeholder="例如：上海、杭州" />
                  <TagsInput label="目标行业" value={splitValues(draft.industries)} onChange={(values) => updateDraft("industries", values.join(", "))} splitChars={[",", "，"]} placeholder="例如：互联网、金融科技" />
                  <TagsInput className={classes.fullWidth} label="技能" description="记录你能在简历中提供依据的技能" value={splitValues(draft.skills)} onChange={(values) => updateDraft("skills", values.join(", "))} splitChars={[",", "，"]} placeholder="例如：Python、SQL、机器学习" />
                </div>
                <Group justify="flex-end"><Button type="submit" loading={savingProfile} leftSection={<IconCheck size={17} />}>保存档案</Button></Group>
              </Stack></form>
            </Paper>
          </Tabs.Panel>
          <Tabs.Panel value="resumes">
            <div className={classes.resumeGrid}>
              <Stack gap="lg">
                <Paper withBorder p="lg" radius="lg">
                  <Title order={3} mb="md">导入并检查简历</Title>
                  <Dropzone onDrop={(files) => void uploadFile(files[0] ?? null)} onReject={() => setError("请选择不超过 10 MB 的 PDF 或 DOCX 文件。")} accept={{ "application/pdf": [".pdf"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"] }} maxSize={10 * 1024 * 1024} maxFiles={1} loading={uploadingResume} aria-label="上传 PDF / DOCX">
                    <Stack align="center" gap="sm" py="xl" style={{ pointerEvents: "none" }}>
                      <ThemeIcon variant="light" size={46} radius="md"><IconUpload size={23} /></ThemeIcon>
                      <Text fw={600}>上传 PDF / DOCX</Text>
                      <Text c="dimmed" size="sm" ta="center">拖动文件到这里，或点击选择文件。最大 10 MB。</Text>
                    </Stack>
                  </Dropzone>
                  <Text c="dimmed" size="xs" mt="sm">解析后先检查预览，再确认使用。文件仅保存在当前账户。</Text>
                </Paper>
                <Paper withBorder p="lg" radius="lg" component="form" onSubmit={savePastedText}>
                  <Textarea label="也可以直接粘贴简历文本" id="resume-text" maxLength={100000} minRows={6} autosize maxRows={12} value={pasteText} onChange={(event) => setPasteText(event.currentTarget.value)} placeholder="粘贴简历内容，最多 100,000 字符" />
                  <Group justify="flex-end" mt="md"><Button variant="light" disabled={!pasteText.trim()} loading={savingResumeText} type="submit">保存为新版本</Button></Group>
                </Paper>
              </Stack>
              <Paper withBorder p="lg" radius="lg">
                <Group justify="space-between" mb="md"><Title order={3}>我的简历版本</Title><Badge variant="light">{resumes.length} 份</Badge></Group>
                {!resumes.length ? <EmptyState title="还没有简历版本" description="上传文件或粘贴文本，创建第一份简历。" /> : <Stack gap="xs">{resumes.map((resume) => <UnstyledButton key={resume.id} className={classes.version} onClick={() => void showResume(resume.id)} aria-label={`预览简历 ${resume.filename}`}>
                  <ThemeIcon variant="light" color="gray" size={38} radius="md"><IconFileText size={20} /></ThemeIcon>
                  <div className={classes.versionText}><Text fw={600} size="sm" lineClamp={2}>{resume.filename}</Text><Text size="xs" c="dimmed">{resume.source_type === "upload" ? "文件上传" : "粘贴文本"}，{resume.extracted_char_count.toLocaleString()} 字</Text><Text size="xs" c="dimmed">{new Date(resume.created_at).toLocaleDateString("zh-CN")}</Text></div>
                  <Badge variant="light" color={resume.confirmed_at ? "teal" : "yellow"} size="sm">{resume.confirmed_at ? "已确认" : "待确认"}</Badge>
                </UnstyledButton>)}</Stack>}
              </Paper>
            </div>
          </Tabs.Panel>
        </Tabs>
      )}
      <Drawer opened={preview !== null} onClose={() => setPreview(null)} position="right" size="lg" title="简历解析预览" closeButtonProps={{ "aria-label": "关闭预览" }}>
        {preview && <Stack gap="lg">
          <div><Title order={3}>{preview.filename}</Title><Text c="dimmed" size="sm" mt={5}>{preview.extracted_char_count.toLocaleString()} 个字符</Text></div>
          {error && <Alert color="red" title="操作未完成">{error}</Alert>}
          <Alert variant="light" color={preview.confirmed_at ? "teal" : "yellow"}>{preview.confirmed_at ? "已由你确认，可用于后续匹配。" : "请检查解析内容是否完整。确认前不会用于匹配和材料生成。"}</Alert>
          <ScrollArea.Autosize mah="60vh"><Text component="pre" className={classes.preview}>{preview.extracted_text}</Text></ScrollArea.Autosize>
          <Group justify="space-between"><Button color="red" variant="subtle" leftSection={<IconTrash size={16} />} onClick={() => void deleteResume()}>删除版本</Button>{!preview.confirmed_at && <Button leftSection={<IconCheck size={16} />} onClick={() => void confirmResume()}>确认这份简历</Button>}</Group>
        </Stack>}
      </Drawer>
    </Stack>
  );
}
