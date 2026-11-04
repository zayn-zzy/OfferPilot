"use client";

import { type FormEvent, useEffect, useState } from "react";
import { Accordion, Alert, Badge, Blockquote, Button, Divider, Group, Modal, Paper, Stack, Text, Textarea, TextInput, ThemeIcon, Title } from "@mantine/core";
import { IconBook2, IconDatabase, IconPlus, IconSearch, IconTrash } from "@tabler/icons-react";
import { ApiError, apiRequest, type KnowledgeAnswer, type KnowledgeNote, type KnowledgeReindex } from "@/lib/api";
import { EmptyState, Feedback, LoadingState, PageHeader } from "@/components/ui";
import { useConfirm } from "@/lib/use-confirm";
import classes from "./page.module.css";

export default function KnowledgePage() {
  const confirm = useConfirm();
  const [noteModal, setNoteModal] = useState(false);
  const [indexDirty, setIndexDirty] = useState(false);
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
      setNoteModal(false);
      setIndexDirty(true);
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
    if (!await confirm({ title: "删除个人笔记", message: `删除笔记“${note.title}”？它的检索片段也会被删除。`, confirmLabel: "删除笔记", danger: true })) return;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      await apiRequest("/api/v1/knowledge/notes/" + note.id, { method: "DELETE" });
      setNotes((current) => current.filter((item) => item.id !== note.id));
      setAnswer(null);
      setIndexDirty(true);
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
      setIndexDirty(false);
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
    <Stack gap="lg">
      <PageHeader title="资料问答" description="从已确认简历和个人笔记中检索答案，并核对原文依据。" actions={<Button leftSection={<IconPlus size={17} />} onClick={() => setNoteModal(true)}>新增笔记</Button>} />
      <Feedback error={error} notice={notice} requiresLogin={requiresLogin} />
      {loading ? <LoadingState /> : <div className={classes.workspace}>
        <Stack gap="lg">
          <Paper withBorder p="lg" radius="lg">
            <Group gap="sm" mb="md"><ThemeIcon variant="light" radius="md"><IconDatabase size={18} /></ThemeIcon><Title order={3}>资料索引</Title></Group>
            <Text c="dimmed" size="sm" mb="md">索引包含已确认简历与求职笔记。资料变更后，请更新索引。</Text>
            {indexSummary ? <Group gap="xs" mb="md"><Badge variant="light">{indexSummary.indexed_documents} 份资料</Badge><Badge variant="light" color="gray">{indexSummary.indexed_chunks} 个片段</Badge></Group> : <Text size="xs" c="dimmed" mb="md">当前页面尚未建立索引；已有索引可直接用于提问。</Text>}
            {indexDirty && <Alert color="yellow" variant="light" mb="md">资料有变化，请重新建立索引。</Alert>}
            <Button fullWidth variant="light" leftSection={<IconDatabase size={16} />} disabled={working} onClick={() => void reindex()}>建立 / 更新索引</Button>
            {indexSummary && <Text c="dimmed" size="xs" mt="sm">向量模型：{indexSummary.embedding_model}</Text>}
          </Paper>
          <Paper withBorder p="lg" radius="lg">
            <Group justify="space-between" mb="md"><Title order={3}>个人笔记</Title><Badge variant="light" color="gray">{notes.length}</Badge></Group>
            {!notes.length ? <EmptyState title="还没有个人笔记" description="记录项目职责、技术方案和成果，作为回答的真实依据。" action={<Button variant="subtle" size="compact-sm" onClick={() => setNoteModal(true)}>创建笔记</Button>} /> : <Accordion variant="separated" chevronPosition="right">{notes.map((note) => <Accordion.Item key={note.id} value={note.id}>
              <Accordion.Control icon={<IconBook2 size={17} />}>{note.title}</Accordion.Control>
              <Accordion.Panel><Text size="sm" className={classes.sourceText}>{note.content}</Text><Group justify="flex-end" mt="sm"><Button variant="subtle" color="red" size="compact-sm" disabled={working} leftSection={<IconTrash size={14} />} onClick={() => void deleteNote(note)}>删除</Button></Group></Accordion.Panel>
            </Accordion.Item>)}</Accordion>}
          </Paper>
        </Stack>
        <Paper withBorder radius="lg" p={{ base: "md", sm: "xl" }} className={classes.answerPane}>
          <Stack gap="lg">
            <div><Group gap="sm"><ThemeIcon variant="light" radius="md"><IconSearch size={18} /></ThemeIcon><Title order={3}>询问自己的求职资料</Title></Group><Text size="sm" c="dimmed" mt="sm">系统检索相关片段后整理回答；资料不足时会明确说明。</Text></div>
            <form onSubmit={ask}><Textarea id="knowledge-question" label="问题" maxLength={2000} minLength={3} required minRows={4} autosize maxRows={8} value={question} onChange={(event) => setQuestion(event.currentTarget.value)} placeholder="例如：我的校园项目中用了哪些数据库？" /><Group justify="flex-end" mt="md"><Button type="submit" loading={working} disabled={question.trim().length < 3} leftSection={<IconSearch size={16} />}>查询资料</Button></Group></form>
            <Divider />
            {answer ? <Stack gap="md" aria-live="polite">
              <Group><Badge color={answer.no_evidence ? "yellow" : "teal"} variant="light">{answer.no_evidence ? "没有找到足够依据" : "回答"}</Badge>{answer.citations.length > 0 && <Text c="dimmed" size="xs">{answer.citations.length} 条原文引用</Text>}</Group>
              <Text className={classes.answerText}>{answer.answer}</Text>
              {answer.citations.length > 0 && <><Text fw={600} size="sm">引用资料</Text>{answer.citations.map((citation) => <Blockquote key={citation.chunk_id} color="teal" cite={`${citation.source_type === "resume" ? "简历" : "笔记"}：${citation.source_name}`} className={classes.quote}>{citation.quote}</Blockquote>)}</>}
            </Stack> : <EmptyState title="答案将附上资料来源" description="提出一个与项目或求职经历有关的问题，查看回答和对应原文。" />}
            <Text c="dimmed" size="xs">索引原文会发送到已配置的 Embeddings 服务；回答所需资料片段会发送到 Chat Completions 服务。</Text>
          </Stack>
        </Paper>
      </div>}
      <Modal opened={noteModal} onClose={() => setNoteModal(false)} title="保存项目经历或求职笔记" size="lg">
        <form onSubmit={createNote}><Stack gap="md">
          {error && <Alert color="red">{error}</Alert>}
          <TextInput label="标题" maxLength={200} required value={title} onChange={(event) => setTitle(event.currentTarget.value)} placeholder="例如：校园交易平台项目" />
          <Textarea label="内容" maxLength={50000} minLength={20} required minRows={8} autosize maxRows={15} value={content} onChange={(event) => setContent(event.currentTarget.value)} placeholder="记录项目背景、你的职责、技术方案和结果，至少 20 个字符。" />
          <Text c="dimmed" size="xs">只记录真实经历。保存后需要重新建立索引。</Text>
          <Group justify="flex-end"><Button variant="default" onClick={() => setNoteModal(false)}>取消</Button><Button loading={working} disabled={content.trim().length < 20 || !title.trim()} type="submit">保存笔记</Button></Group>
        </Stack></form>
      </Modal>
    </Stack>
  );
}
