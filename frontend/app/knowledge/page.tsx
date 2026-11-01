"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";
import { ApiError, apiRequest, type KnowledgeAnswer, type KnowledgeNote, type KnowledgeReindex } from "@/lib/api";

export default function KnowledgePage() {
  const [notes, setNotes] = useState<KnowledgeNote[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<KnowledgeAnswer | null>(null);
  const [indexSummary, setIndexSummary] = useState<KnowledgeReindex | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);

  async function loadNotes() {
    setNotes(await apiRequest<KnowledgeNote[]>("/api/v1/knowledge/notes"));
  }

  useEffect(() => {
    loadNotes()
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "无法载入个人笔记。");
        setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      })
      .finally(() => setLoading(false));
  }, []);

  async function createNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setWorking(true);
    setError("");
    setNotice("");
    try {
      await apiRequest<KnowledgeNote>("/api/v1/knowledge/notes", {
        method: "POST",
        body: JSON.stringify({ title, content }),
      });
      setTitle("");
      setContent("");
      await loadNotes();
      setNotice("笔记已保存。重新建立索引后即可用于问答。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存笔记失败。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setWorking(false);
    }
  }

  async function deleteNote(note: KnowledgeNote) {
    if (!window.confirm("删除笔记“" + note.title + "”？")) return;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      await apiRequest("/api/v1/knowledge/notes/" + note.id, { method: "DELETE" });
      setNotes((current) => current.filter((item) => item.id !== note.id));
      setAnswer(null);
      setNotice("笔记和它的检索片段已删除。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除笔记失败。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setWorking(false);
    }
  }

  async function reindex() {
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const summary = await apiRequest<KnowledgeReindex>("/api/v1/knowledge/reindex", { method: "POST" });
      setIndexSummary(summary);
      setNotice("索引已更新：" + summary.indexed_documents + " 份资料，" + summary.indexed_chunks + " 个片段。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "建立检索索引失败。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setWorking(false);
    }
  }

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setWorking(true);
    setError("");
    setAnswer(null);
    try {
      const result = await apiRequest<KnowledgeAnswer>("/api/v1/knowledge/ask", {
        method: "POST",
        body: JSON.stringify({ question, top_k: 5 }),
      });
      setAnswer(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "资料问答失败。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="knowledge-shell">
      <header className="dashboard-topbar profile-topbar">
        <Link className="brand" href="/"><span className="brand-mark">O</span> OfferPilot</Link>
        <nav className="dashboard-actions" aria-label="主导航">
          <Link className="text-link" href="/dashboard">工作台</Link>
          <Link className="text-link" href="/profile">个人档案</Link>
          <Link className="text-link" href="/jobs">岗位管理</Link>
        </nav>
      </header>

      <section className="profile-heading">
        <p className="eyebrow">个人资料 RAG</p>
        <h1>从简历和笔记中查找有依据的答案。</h1>
        <p>只检索你已确认的简历和自己保存的求职笔记。答案附原文片段；找不到依据时会明确说明。</p>
      </section>

      {error && <div className="profile-message profile-error" role="alert">{error}{requiresLogin && <> <Link href="/login">去登录</Link></>}</div>}
      {notice && <div className="profile-message profile-success" role="status">{notice}</div>}
      {loading && <p className="profile-loading">正在载入个人笔记…</p>}

      <section className="profile-panel">
        <div className="profile-panel-heading">
          <div><p className="eyebrow">资料索引</p><h2>更新简历与笔记索引</h2></div>
          <button className="button button-primary" disabled={working} onClick={() => void reindex()} type="button">
            {working ? "处理中…" : "建立 / 更新索引"}
          </button>
        </div>
        <p className="knowledge-hint">只有在个人档案确认过的简历会被索引。添加、修改或删除笔记后，请重新建立索引。原文会发送到你配置的 Embeddings 服务；回答会发送到 Chat Completions 服务。</p>
        {indexSummary && <p className="knowledge-index-summary">当前索引记录：{indexSummary.indexed_documents} 份资料 · {indexSummary.indexed_chunks} 个片段 · {indexSummary.embedding_model}</p>}
      </section>

      <section className="profile-panel">
        <div className="profile-panel-heading"><div><p className="eyebrow">个人笔记</p><h2>保存项目经历或求职笔记</h2></div></div>
        <form className="knowledge-note-form" onSubmit={createNote}>
          <label>标题<input maxLength={200} required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：校园交易平台项目" /></label>
          <label>内容<textarea maxLength={50_000} minLength={20} required rows={5} value={content} onChange={(event) => setContent(event.target.value)} placeholder="记录项目背景、你的职责、技术方案和结果，至少 20 个字符。" /></label>
          <button className="button button-secondary" disabled={working || content.trim().length < 20 || !title.trim()} type="submit">{working ? "保存中…" : "保存笔记"}</button>
        </form>
        <div className="knowledge-note-list">
          {notes.length === 0 && <p className="empty-state">还没有个人笔记。你也可以先在个人档案中确认一份简历。</p>}
          {notes.map((note) => <article className="knowledge-note" key={note.id}>
            <div><h3>{note.title}</h3><p>{note.content}</p></div>
            <button className="job-quiet-action danger-text" disabled={working} onClick={() => void deleteNote(note)} type="button">删除</button>
          </article>)}
        </div>
      </section>

      <section className="profile-panel">
        <div className="profile-panel-heading"><div><p className="eyebrow">有来源的问答</p><h2>询问自己的求职资料</h2></div></div>
        <form className="knowledge-ask-form" onSubmit={ask}>
          <label htmlFor="knowledge-question">问题</label>
          <textarea id="knowledge-question" maxLength={2000} minLength={3} required rows={3} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：我的校园项目中用了哪些数据库？" />
          <button className="button button-primary" disabled={working || question.trim().length < 3} type="submit">{working ? "检索并整理中…" : "查询资料"}</button>
        </form>
        {answer && <section className="knowledge-answer" aria-live="polite">
          <h3>{answer.no_evidence ? "没有找到足够依据" : "回答"}</h3>
          <p>{answer.answer}</p>
          {answer.citations.length > 0 && <div className="knowledge-citations"><h4>引用资料</h4>
            {answer.citations.map((citation) => <blockquote key={citation.chunk_id}>
              <strong>{citation.source_type === "resume" ? "简历" : "笔记"} · {citation.source_name}</strong>
              <span>{citation.quote}</span>
            </blockquote>)}
          </div>}
        </section>}
      </section>
    </main>
  );
}
