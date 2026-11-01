"use client";

import Link from "next/link";
import { type ChangeEvent, type FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, apiRequest } from "@/lib/api";

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

  async function uploadFile(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = "";
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
    if (!preview || !window.confirm(`删除“${preview.filename}”？`)) return;
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
    <main className="profile-shell">
      <header className="dashboard-topbar profile-topbar">
        <Link className="brand" href="/">
          <span className="brand-mark">O</span> OfferPilot
        </Link>
        <div className="dashboard-actions">
          <Link className="text-link" href="/knowledge">资料问答</Link>
          <Link className="text-link" href="/dashboard">返回工作台</Link>
        </div>
      </header>

      <section className="profile-heading">
        <p className="eyebrow">个人档案</p>
        <h1>先把求职基础资料整理好。</h1>
        <p>信息只属于你的账户。简历解析后会先进入预览，只有你确认的版本才会用于后续匹配。</p>
      </section>

      {error ? <div className="profile-message profile-error" role="alert">{error}{requiresLogin ? <> <Link href="/login">去登录</Link></> : null}</div> : null}
      {notice ? <div className="profile-message profile-success" role="status">{notice}</div> : null}
      {loading ? <p className="profile-loading">正在载入个人档案…</p> : null}

      <section className="profile-panel">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">基础信息</p><h2>求职偏好与教育背景</h2></div>
        </div>
        <form className="profile-form" onSubmit={saveProfile}>
          <label>毕业年份<input max="2100" min="1980" onChange={(event) => updateDraft("graduationYear", event.target.value)} placeholder="例如：2027" type="number" value={draft.graduationYear} /></label>
          <label>学历<input maxLength={100} onChange={(event) => updateDraft("education", event.target.value)} placeholder="例如：硕士" value={draft.education} /></label>
          <label>专业<input maxLength={120} onChange={(event) => updateDraft("major", event.target.value)} placeholder="例如：计算机科学与技术" value={draft.major} /></label>
          <label>目标岗位 <span>用逗号分隔</span><textarea onChange={(event) => updateDraft("targetRoles", event.target.value)} placeholder="例如：后端开发、算法工程师" rows={2} value={draft.targetRoles} /></label>
          <label>目标城市 <span>用逗号分隔</span><textarea onChange={(event) => updateDraft("targetCities", event.target.value)} placeholder="例如：上海、杭州、深圳" rows={2} value={draft.targetCities} /></label>
          <label>目标行业 <span>用逗号分隔</span><textarea onChange={(event) => updateDraft("industries", event.target.value)} placeholder="例如：互联网、金融科技" rows={2} value={draft.industries} /></label>
          <label className="profile-full-width">技能 <span>用逗号分隔</span><textarea onChange={(event) => updateDraft("skills", event.target.value)} placeholder="例如：Python、SQL、机器学习" rows={3} value={draft.skills} /></label>
          <div className="profile-full-width profile-form-actions">
            <button className="button button-primary" disabled={savingProfile} type="submit">{savingProfile ? "保存中…" : "保存档案"}</button>
          </div>
        </form>
      </section>

      <section className="profile-panel">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">简历版本</p><h2>导入并检查简历</h2></div>
          <label className="button button-secondary upload-button">
            {uploadingResume ? "上传并解析中…" : "上传 PDF / DOCX"}
            <input accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={uploadingResume} onChange={uploadFile} type="file" />
          </label>
        </div>
        <form className="paste-form" onSubmit={savePastedText}>
          <label htmlFor="resume-text">也可以直接粘贴简历文本</label>
          <textarea id="resume-text" maxLength={100000} onChange={(event) => setPasteText(event.target.value)} placeholder="粘贴简历内容，最多 100,000 字符" rows={5} value={pasteText} />
          <button className="button button-secondary" disabled={!pasteText.trim() || savingResumeText} type="submit">{savingResumeText ? "保存中…" : "保存为新版本"}</button>
        </form>

        <div className="resume-version-list">
          {resumes.length === 0 ? <p className="empty-state">还没有简历版本。上传文件或粘贴文本来创建第一版。</p> : null}
          {resumes.map((resume) => (
            <button className={`resume-version-row ${preview?.id === resume.id ? "resume-version-active" : ""}`} key={resume.id} onClick={() => showResume(resume.id)} type="button">
              <span className="resume-version-icon">CV</span>
              <span className="resume-version-info"><strong>{resume.filename}</strong><small>{resume.source_type === "upload" ? "文件上传" : "粘贴文本"} · {resume.extracted_char_count.toLocaleString()} 字 · {new Date(resume.created_at).toLocaleDateString("zh-CN")}</small></span>
              <span className={`status-pill ${resume.confirmed_at ? "resume-confirmed" : "resume-unconfirmed"}`}>{resume.confirmed_at ? "已确认" : "待确认"}</span>
            </button>
          ))}
        </div>

        {preview ? (
          <div className="resume-preview">
            <div className="resume-preview-heading">
              <div><p className="eyebrow">解析预览</p><h3>{preview.filename}</h3><small>{preview.extracted_char_count.toLocaleString()} 个字符</small></div>
              <button aria-label="关闭预览" className="preview-close" onClick={() => setPreview(null)} type="button">×</button>
            </div>
            <pre>{preview.extracted_text}</pre>
            <div className="profile-form-actions">
              {!preview.confirmed_at ? <button className="button button-primary" onClick={confirmResume} type="button">确认这份简历</button> : <span className="resume-confirmed-copy">已由你确认</span>}
              <button className="button button-secondary" onClick={deleteResume} type="button">删除版本</button>
            </div>
          </div>
        ) : null}
      </section>
    </main>
  );
}
