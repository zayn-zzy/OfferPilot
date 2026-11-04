"use client";

import {
  Anchor,
  Badge,
  Button,
  Checkbox,
  Collapse,
  Divider,
  Drawer,
  FileInput,
  Group,
  Menu,
  Paper,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { DateInput } from "@mantine/dates";
import {
  IconAdjustmentsHorizontal,
  IconDownload,
  IconFileImport,
  IconPlus,
  IconSearch,
  IconSparkles,
} from "@tabler/icons-react";
import {
  EmptyState,
  Feedback,
  LoadingState,
  PageHeader,
} from "@/components/ui";
import classes from "./jobs.module.css";
import { FormEvent, useEffect, useRef, useState } from "react";
import {
  APPLICATION_STAGES,
  APPLICATION_STAGE_LABELS,
  ApiError,
  apiRequest,
  type JobCsvPreview,
  type JobCsvPreviewRow,
  type ApplicationStatusEvent,
  type JobPosting,
  type JobPostingWrite,
  type ResumeVersionSummary,
} from "@/lib/api";
import JobCard from "./job-card";
import JobEditor from "./job-editor";
import JobExtractionPanel from "./job-extraction-panel";

type Filters = {
  search: string;
  city: string;
  status: string;
  deadline_before: string;
  tag: string;
};
const DEFAULT_FILTERS: Filters = {
  search: "",
  city: "",
  status: "",
  deadline_before: "",
  tag: "",
};
const JOB_MERGE_LABELS: Partial<Record<keyof JobPostingWrite, string>> = {
  company_name: "公司",
  company_website_url: "公司官网",
  recruitment_url: "招聘主页",
  industry: "行业",
  company_notes: "公司备注",
  title: "职位",
  city: "城市",
  job_type: "岗位类型",
  batch: "招聘批次",
  deadline: "截止日期",
  education_requirement: "学历要求",
  description: "岗位描述",
};

function mergeCsvPayload(
  existing: JobPostingWrite,
  incoming: JobPostingWrite,
): { payload: JobPostingWrite; conflicts: string[] } {
  const payload: JobPostingWrite = { ...existing };
  const conflicts: string[] = [];
  for (const field of Object.keys(
    JOB_MERGE_LABELS,
  ) as (keyof JobPostingWrite)[]) {
    const current = payload[field];
    const next = incoming[field];
    if (
      (current === null || current === "") &&
      typeof next === "string" &&
      next
    ) {
      (payload as unknown as Record<string, unknown>)[field] = next;
    } else if (current && next && current !== next) {
      conflicts.push(JOB_MERGE_LABELS[field] ?? field);
    }
  }
  const appendUnique = (left: string[], right: string[]) => {
    const result = [...left];
    const seen = new Set(left.map((item) => item.toLocaleLowerCase()));
    for (const item of right) {
      if (!seen.has(item.toLocaleLowerCase())) {
        result.push(item);
        seen.add(item.toLocaleLowerCase());
      }
    }
    return result;
  };
  payload.required_skills = appendUnique(
    existing.required_skills,
    incoming.required_skills,
  );
  payload.tags = appendUnique(existing.tags, incoming.tags);
  return { payload, conflicts };
}

function apiMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : "操作失败，请稍后重试。";
}

export default function JobsPage() {
  const [filterOpened, setFilterOpened] = useState(false);
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [resumes, setResumes] = useState<ResumeVersionSummary[]>([]);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<JobCsvPreview | null>(null);
  const [selectedCsvRows, setSelectedCsvRows] = useState<number[]>([]);
  const [mergedCsvRows, setMergedCsvRows] = useState<number[]>([]);
  const [mergingCsvRow, setMergingCsvRow] = useState<number | null>(null);
  const [previewingCsv, setPreviewingCsv] = useState(false);
  const [importingCsv, setImportingCsv] = useState(false);
  const [createPanel, setCreatePanel] = useState<
    "new" | "csv" | "extract" | null
  >(null);
  const [filters, setFilters] = useState<Filters>({ ...DEFAULT_FILTERS });
  const [draftFilters, setDraftFilters] = useState(filters);
  const [loading, setLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const [savedJobId, setSavedJobId] = useState<string | null>(null);
  const listRequestVersion = useRef(0);
  const pendingSavedJobFocus = useRef<string | null>(null);

  async function loadJobs(
    nextFilters: Filters = filters,
    visibleJob?: JobPosting,
  ) {
    const requestVersion = ++listRequestVersion.current;
    setError("");
    const params = new URLSearchParams();
    if (nextFilters.search.trim())
      params.set("search", nextFilters.search.trim());
    if (nextFilters.city.trim()) params.set("city", nextFilters.city.trim());
    if (nextFilters.status) params.set("status", nextFilters.status);
    if (nextFilters.deadline_before)
      params.set("deadline_before", nextFilters.deadline_before);
    if (nextFilters.tag.trim()) params.set("tag", nextFilters.tag.trim());
    try {
      const query = params.toString();
      const result = await apiRequest<JobPosting[]>(
        `/api/v1/jobs${query ? `?${query}` : ""}`,
      );
      if (requestVersion !== listRequestVersion.current) return;
      if (visibleJob) {
        const current =
          result.find((job) => job.id === visibleJob.id) ?? visibleJob;
        pendingSavedJobFocus.current = current.id;
        setJobs([current, ...result.filter((job) => job.id !== current.id)]);
      } else {
        setJobs(result);
      }
      setRequiresLogin(false);
      setHasLoaded(true);
    } catch (cause) {
      if (requestVersion !== listRequestVersion.current) return;
      setError(apiMessage(cause));
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      if (requestVersion === listRequestVersion.current) setLoading(false);
    }
  }

  async function showSavedJobs(saved: JobPosting[], message: string) {
    // A pre-save list response must not replace the newly confirmed records.
    listRequestVersion.current += 1;
    const nextFilters = { ...DEFAULT_FILTERS };
    const latestFirst = [...saved].sort(
      (a, b) =>
        b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id),
    );
    const savedIds = new Set(latestFirst.map((job) => job.id));
    pendingSavedJobFocus.current = latestFirst[0]?.id ?? null;
    setSavedJobId(latestFirst[0]?.id ?? null);
    setFilters(nextFilters);
    setDraftFilters(nextFilters);
    setJobs((current) => [
      ...latestFirst,
      ...current.filter((job) => !savedIds.has(job.id)),
    ]);
    setHasLoaded(true);
    setLoading(false);
    setRequiresLogin(false);
    setError("");
    setSuccess(message);
    await loadJobs(nextFilters, latestFirst[0]);
  }

  useEffect(() => {
    const jobId = pendingSavedJobFocus.current;
    if (createPanel) return;
    if (!jobId) return;
    const card = document.getElementById(`job-${jobId}`);
    if (!card) return;
    pendingSavedJobFocus.current = null;
    card.scrollIntoView({ block: "center" });
    card.focus({ preventScroll: true });
  }, [jobs, createPanel]);

  async function previewCsv(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!csvFile) {
      setError("请先选择岗位 CSV 文件。");
      return;
    }
    setError("");
    setSuccess("");
    setPreviewingCsv(true);
    const formData = new FormData();
    formData.append("file", csvFile);
    try {
      const result = await apiRequest<JobCsvPreview>(
        "/api/v1/jobs/import/preview",
        {
          method: "POST",
          body: formData,
        },
      );
      setCsvPreview(result);
      setSelectedCsvRows(
        result.rows
          .filter((row) => row.status === "ready")
          .map((row) => row.row_number),
      );
      setMergedCsvRows([]);
    } catch (cause) {
      setError(apiMessage(cause));
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
      setCsvPreview(null);
    } finally {
      setPreviewingCsv(false);
    }
  }

  async function importSelectedCsvRows() {
    const jobsToImport =
      csvPreview?.rows
        .filter(
          (row) =>
            selectedCsvRows.includes(row.row_number) && row.status === "ready",
        )
        .flatMap((row) => (row.data ? [row.data] : [])) ?? [];
    if (jobsToImport.length === 0) {
      setError("请选择至少一条校验通过的岗位。");
      return;
    }
    setError("");
    setSuccess("");
    setImportingCsv(true);
    try {
      const imported = await apiRequest<JobPosting[]>("/api/v1/jobs/import", {
        method: "POST",
        body: JSON.stringify({ jobs: jobsToImport }),
      });
      setCsvFile(null);
      setCsvPreview(null);
      setSelectedCsvRows([]);
      setMergedCsvRows([]);
      setCreatePanel(null);
      await showSavedJobs(
        imported,
        `已导入 ${imported.length} 条岗位。可以在岗位列表中继续编辑。`,
      );
    } catch (cause) {
      setError(apiMessage(cause));
    } finally {
      setImportingCsv(false);
    }
  }

  function toggleCsvRow(row: JobCsvPreviewRow, checked: boolean) {
    setSelectedCsvRows((current) =>
      checked
        ? [...current, row.row_number]
        : current.filter((number) => number !== row.row_number),
    );
  }

  function toggleAllCsvRows(checked: boolean) {
    setSelectedCsvRows(
      checked
        ? (csvPreview?.rows
            .filter((row) => row.status === "ready")
            .map((row) => row.row_number) ?? [])
        : [],
    );
  }

  function mergeCsvDuplicateIntoRow(row: JobCsvPreviewRow) {
    if (!csvPreview || !row.data || !row.duplicate_of_row_number) return;
    const target = csvPreview.rows.find(
      (item) => item.row_number === row.duplicate_of_row_number,
    );
    if (!target?.data) return;
    const { payload, conflicts } = mergeCsvPayload(target.data, row.data);
    const detail = conflicts.length
      ? `已补充空字段并合并技能/标签；冲突字段保留第 ${target.row_number} 行的值：${conflicts.join("、")}`
      : `已补充第 ${target.row_number} 行的空字段，并合并技能和标签。`;
    setCsvPreview({
      ...csvPreview,
      rows: csvPreview.rows.map((item) => {
        if (item.row_number === target.row_number) {
          return {
            ...item,
            data: payload,
            company_name: payload.company_name,
            title: payload.title,
            city: payload.city,
            deadline: payload.deadline,
          };
        }
        if (item.row_number === row.row_number) {
          return { ...item, duplicate_detail: detail };
        }
        return item;
      }),
    });
    setSelectedCsvRows((current) =>
      current.includes(target.row_number)
        ? current
        : [...current, target.row_number],
    );
    setMergedCsvRows((current) =>
      current.includes(row.row_number) ? current : [...current, row.row_number],
    );
  }

  async function mergeIntoExistingJob(
    targetJobId: string,
    payload: JobPostingWrite,
  ) {
    return apiRequest<JobPosting>(`/api/v1/jobs/${targetJobId}/merge`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async function mergeCsvDuplicate(row: JobCsvPreviewRow) {
    if (!row.data || !row.duplicate_job_id) return;
    setMergingCsvRow(row.row_number);
    setError("");
    try {
      const merged = await mergeIntoExistingJob(row.duplicate_job_id, row.data);
      setMergedCsvRows((current) => [...current, row.row_number]);
      await showSavedJobs(
        [merged],
        `CSV 第 ${row.row_number} 行的信息已合并到已有岗位；投递记录已保留。`,
      );
    } catch (cause) {
      setError(apiMessage(cause));
    } finally {
      setMergingCsvRow(null);
    }
  }

  useEffect(() => {
    void loadJobs();
  }, []);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("task") === "extract") {
      setCreatePanel("extract");
    }
  }, []);

  useEffect(() => {
    if (createPanel !== "extract") return;
    document
      .getElementById("job-extraction-panel")
      ?.scrollIntoView({ block: "start" });
  }, [createPanel]);

  useEffect(() => {
    apiRequest<ResumeVersionSummary[]>("/api/v1/resumes")
      .then(setResumes)
      .catch(() => setResumes([]));
  }, []);

  async function createJob(payload: JobPostingWrite) {
    setSuccess("");
    const saved = await apiRequest<JobPosting>("/api/v1/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setCreatePanel(null);
    await showSavedJobs([saved], "岗位已保存。");
  }

  async function mergeJob(targetJobId: string, payload: JobPostingWrite) {
    const merged = await mergeIntoExistingJob(targetJobId, payload);
    setCreatePanel(null);
    await showSavedJobs(
      [merged],
      "岗位信息已合并到已有记录；投递状态和阶段历史保持不变。",
    );
  }

  async function saveJob(job: JobPosting, payload: JobPostingWrite) {
    const saved = await apiRequest<JobPosting>(`/api/v1/jobs/${job.id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    setJobs((current) =>
      current.map((item) => (item.id === saved.id ? saved : item)),
    );
    await loadJobs();
  }

  async function deleteJob(job: JobPosting) {
    await apiRequest(`/api/v1/jobs/${job.id}`, { method: "DELETE" });
    setJobs((current) => current.filter((item) => item.id !== job.id));
    setSavedJobId(null);
    setSuccess("岗位已删除。");
  }

  async function updateApplication(
    job: JobPosting,
    update: Record<string, unknown>,
  ) {
    const saved = await apiRequest<JobPosting>(
      `/api/v1/jobs/${job.id}/application`,
      {
        method: "PUT",
        body: JSON.stringify(update),
      },
    );
    setJobs((current) =>
      current.map((item) => (item.id === saved.id ? saved : item)),
    );
    await loadJobs();
  }

  async function readHistory(
    job: JobPosting,
  ): Promise<ApplicationStatusEvent[]> {
    return apiRequest<ApplicationStatusEvent[]>(
      `/api/v1/jobs/${job.id}/application/history`,
    );
  }

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSuccess("");
    setSavedJobId(null);
    setFilters(draftFilters);
    void loadJobs(draftFilters);
  }

  const activeFilters = Object.entries(filters).filter(([, value]) => value);

  return (
    <Stack gap="lg">
      <PageHeader
        title="岗位管理"
        description="从发现机会到拿到 Offer，在同一处推进每一个岗位。"
        actions={
          <Group gap="sm">
            <Button
              variant="light"
              leftSection={<IconSparkles size={17} />}
              onClick={() => setCreatePanel("extract")}
            >
              AI 提取岗位
            </Button>
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <Button leftSection={<IconPlus size={17} />}>添加岗位</Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item
                  leftSection={<IconPlus size={16} />}
                  onClick={() => setCreatePanel("new")}
                >
                  新增岗位
                </Menu.Item>
                <Menu.Item
                  leftSection={<IconFileImport size={16} />}
                  onClick={() => setCreatePanel("csv")}
                >
                  导入 CSV
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        }
      />
      <Feedback error={error} requiresLogin={requiresLogin} notice={success} />
      {savedJobId && success && (
        <Anchor href={`#job-${savedJobId}`} size="sm">
          查看岗位
        </Anchor>
      )}
      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" wrap="wrap">
          <Group gap="sm">
            <Title order={2} size="h4">
              我的岗位
            </Title>
            <Badge variant="light" color="gray">
              {jobs.length} 条
            </Badge>
          </Group>
          <Button
            variant={filterOpened ? "light" : "default"}
            leftSection={<IconAdjustmentsHorizontal size={16} />}
            onClick={() => setFilterOpened((opened) => !opened)}
            aria-expanded={filterOpened}
          >
            筛选岗位
          </Button>
        </Group>
        <form onSubmit={applyFilters}>
          <Group mt="md" align="flex-end" wrap="wrap">
            <TextInput
              className={classes.search}
              label="公司 / 职位 / 行业"
              leftSection={<IconSearch size={16} />}
              value={draftFilters.search}
              onChange={(event) =>
                setDraftFilters({
                  ...draftFilters,
                  search: event.currentTarget.value,
                })
              }
              placeholder="搜索公司、职位、城市或行业"
            />
            <Button type="submit">筛选</Button>
            {activeFilters.length > 0 && (
              <Button
                variant="subtle"
                onClick={() => {
                  const reset = { ...DEFAULT_FILTERS };
                  setFilters(reset);
                  setDraftFilters(reset);
                  setSavedJobId(null);
                  void loadJobs(reset);
                }}
              >
                重置筛选
              </Button>
            )}
          </Group>
          <Collapse
            transitionDuration={0}
            keepMounted={false}
            in={filterOpened}
          >
            <SimpleGrid mt="md" cols={{ base: 1, sm: 2, lg: 4 }}>
              <TextInput
                label="城市"
                value={draftFilters.city}
                onChange={(event) =>
                  setDraftFilters({
                    ...draftFilters,
                    city: event.currentTarget.value,
                  })
                }
                placeholder="筛选城市"
              />
              <Select
                label="投递状态"
                clearable
                value={draftFilters.status || null}
                onChange={(value) =>
                  setDraftFilters({ ...draftFilters, status: value ?? "" })
                }
                placeholder="全部状态"
                data={[
                  { value: "untracked", label: "未记录投递" },
                  ...APPLICATION_STAGES.map((stage) => ({
                    value: stage,
                    label: APPLICATION_STAGE_LABELS[stage],
                  })),
                ]}
              />
              <DateInput
                label="截止日期不晚于"
                clearable
                value={draftFilters.deadline_before || null}
                onChange={(value) =>
                  setDraftFilters({
                    ...draftFilters,
                    deadline_before: value ?? "",
                  })
                }
                valueFormat="YYYY-MM-DD"
              />
              <TextInput
                label="标签"
                value={draftFilters.tag}
                onChange={(event) =>
                  setDraftFilters({
                    ...draftFilters,
                    tag: event.currentTarget.value,
                  })
                }
                placeholder="筛选标签"
              />
            </SimpleGrid>
          </Collapse>
        </form>
        {activeFilters.length > 0 && (
          <Group gap="xs" mt="md" aria-label="已应用筛选">
            {activeFilters.map(([key, value]) => (
              <Badge key={key} variant="outline">
                {
                  (
                    {
                      search: "关键词",
                      city: "城市",
                      status: "状态",
                      deadline_before: "截止日期",
                      tag: "标签",
                    } as Record<string, string>
                  )[key]
                }
                ：
                {key === "status"
                  ? value === "untracked"
                    ? "未记录投递"
                    : APPLICATION_STAGE_LABELS[
                        value as keyof typeof APPLICATION_STAGE_LABELS
                      ]
                  : value}
              </Badge>
            ))}
          </Group>
        )}
      </Paper>
      {loading ? (
        <LoadingState />
      ) : !hasLoaded && !requiresLogin ? (
        <EmptyState
          title="无法载入岗位列表"
          description="请重试读取已保存的岗位。"
          action={
            <Button variant="default" onClick={() => void loadJobs()}>
              重新载入
            </Button>
          }
        />
      ) : jobs.length === 0 ? (
        <EmptyState
          title={
            requiresLogin
              ? "请先登录后管理岗位"
              : activeFilters.length
                ? "没有符合条件的岗位"
                : "还没有保存岗位"
          }
          description={
            requiresLogin
              ? "登录后，岗位和申请记录会保存在你的账户中。"
              : activeFilters.length
                ? "尝试调整或重置筛选。"
                : "手动添加、批量导入或使用 AI 整理第一条招聘信息。"
          }
          action={
            !requiresLogin && (
              <Button
                onClick={() => setCreatePanel("new")}
                leftSection={<IconPlus size={16} />}
              >
                新增岗位
              </Button>
            )
          }
        />
      ) : (
        <Stack gap="md" className={classes.list}>
          {jobs.map((job) => (
            <JobCard
              key={job.id}
              job={job}
              onSave={saveJob}
              onDelete={deleteJob}
              onUpdateApplication={updateApplication}
              onHistory={readHistory}
              resumes={resumes}
            />
          ))}
        </Stack>
      )}
      <Drawer
        opened={createPanel !== null}
        onClose={() => setCreatePanel(null)}
        position="right"
        size={createPanel === "csv" ? "xl" : "lg"}
        title={
          createPanel === "new"
            ? "新增岗位"
            : createPanel === "csv"
              ? "从 CSV 添加岗位"
              : "从招聘原文提取岗位字段"
        }
        transitionProps={{ duration: 0 }}
      >
        <Stack>
          <Feedback
            error={error}
            notice={success}
            requiresLogin={requiresLogin}
          />
          {createPanel === "new" && (
            <JobEditor
              onSave={createJob}
              onMerge={mergeJob}
              onCancel={() => setCreatePanel(null)}
            />
          )}
          {createPanel === "extract" && (
            <section id="job-extraction-panel">
              <JobExtractionPanel
                onCancel={() => setCreatePanel(null)}
                onJobCreated={(saved) => {
                  setCreatePanel(null);
                  void showSavedJobs(
                    [saved],
                    "AI 提取的岗位已保存，原文和字段依据已关联。",
                  );
                }}
              />
            </section>
          )}
          {createPanel === "csv" && (
            <Stack>
              <Text size="sm" c="dimmed">
                支持 UTF-8 或 GB18030 编码，最多 500 条、5
                MB。先检查，合并重复来源，再选择需要保存的岗位。
              </Text>
              <Button
                component="a"
                href="/api/v1/jobs/import/template"
                variant="default"
                leftSection={<IconDownload size={16} />}
              >
                下载 CSV 模板
              </Button>
              <form onSubmit={previewCsv}>
                <Stack>
                  <FileInput
                    label="选择 CSV 文件"
                    placeholder="上传 .csv 文件"
                    accept=".csv,text/csv"
                    value={csvFile}
                    onChange={(file) => {
                      setCsvFile(file);
                      setCsvPreview(null);
                      setSelectedCsvRows([]);
                      setMergedCsvRows([]);
                    }}
                    leftSection={<IconFileImport size={16} />}
                  />
                  <Button
                    disabled={!csvFile}
                    loading={previewingCsv}
                    type="submit"
                  >
                    预览并检查
                  </Button>
                </Stack>
              </form>
              {csvPreview && (
                <>
                  <Group gap="xs">
                    <Badge color="teal">
                      可导入 {csvPreview.ready_count} 条
                    </Badge>
                    <Badge color="yellow">
                      重复 {csvPreview.duplicate_count} 条
                    </Badge>
                    <Badge color="red">
                      有错误 {csvPreview.invalid_count} 条
                    </Badge>
                  </Group>
                  <ScrollArea>
                    <Table
                      striped
                      highlightOnHover
                      withTableBorder
                      miw={850}
                      className="csv-preview-table"
                    >
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>
                            <Checkbox
                              aria-label="选择全部可导入岗位"
                              checked={
                                csvPreview.ready_count > 0 &&
                                selectedCsvRows.length ===
                                  csvPreview.ready_count
                              }
                              onChange={(event) =>
                                toggleAllCsvRows(event.currentTarget.checked)
                              }
                            />
                          </Table.Th>
                          <Table.Th>行</Table.Th>
                          <Table.Th>公司</Table.Th>
                          <Table.Th>职位</Table.Th>
                          <Table.Th>城市</Table.Th>
                          <Table.Th>截止日期</Table.Th>
                          <Table.Th>来源</Table.Th>
                          <Table.Th>检查结果</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {csvPreview.rows.map((row) => (
                          <Table.Tr key={row.row_number}>
                            <Table.Td>
                              <Checkbox
                                aria-label={`选择 CSV 第 ${row.row_number} 行`}
                                checked={selectedCsvRows.includes(
                                  row.row_number,
                                )}
                                disabled={row.status !== "ready"}
                                onChange={(event) =>
                                  toggleCsvRow(row, event.currentTarget.checked)
                                }
                              />
                            </Table.Td>
                            <Table.Td>{row.row_number}</Table.Td>
                            <Table.Td>{row.company_name || "—"}</Table.Td>
                            <Table.Td>{row.title || "—"}</Table.Td>
                            <Table.Td>{row.city || "—"}</Table.Td>
                            <Table.Td>{row.deadline || "—"}</Table.Td>
                            <Table.Td>
                              {row.source_url ? (
                                <Anchor
                                  href={row.source_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  size="sm"
                                >
                                  打开来源
                                </Anchor>
                              ) : (
                                "—"
                              )}
                            </Table.Td>
                            <Table.Td>
                              <Stack gap="xs">
                                <Badge
                                  color={
                                    row.status === "ready"
                                      ? "teal"
                                      : row.status === "duplicate"
                                        ? "yellow"
                                        : "red"
                                  }
                                >
                                  {row.status === "ready"
                                    ? "可导入"
                                    : row.status === "duplicate"
                                      ? "重复来源"
                                      : "需要修正"}
                                </Badge>
                                {row.duplicate_detail && (
                                  <Text size="xs">{row.duplicate_detail}</Text>
                                )}
                                {row.duplicate_job_id && (
                                  <>
                                    <Text size="xs">
                                      目标岗位：
                                      {row.duplicate_job_company_name ||
                                        "未填写公司"}{" "}
                                      /{" "}
                                      {row.duplicate_job_title || "未填写职位"}
                                    </Text>
                                    <Button
                                      size="compact-xs"
                                      variant="light"
                                      disabled={mergedCsvRows.includes(
                                        row.row_number,
                                      )}
                                      loading={mergingCsvRow === row.row_number}
                                      onClick={() =>
                                        void mergeCsvDuplicate(row)
                                      }
                                    >
                                      {mergedCsvRows.includes(row.row_number)
                                        ? "已合并"
                                        : "合并到已有岗位"}
                                    </Button>
                                  </>
                                )}
                                {row.duplicate_of_row_number && (
                                  <Button
                                    size="compact-xs"
                                    variant="light"
                                    disabled={mergedCsvRows.includes(
                                      row.row_number,
                                    )}
                                    onClick={() =>
                                      mergeCsvDuplicateIntoRow(row)
                                    }
                                  >
                                    {mergedCsvRows.includes(row.row_number)
                                      ? `已并入第 ${row.duplicate_of_row_number} 行`
                                      : `合并到第 ${row.duplicate_of_row_number} 行`}
                                  </Button>
                                )}
                                {row.errors.map((message) => (
                                  <Text size="xs" c="red" key={message}>
                                    {message}
                                  </Text>
                                ))}
                              </Stack>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </ScrollArea>
                  <Divider />
                  <Group>
                    <Button
                      disabled={selectedCsvRows.length === 0}
                      loading={importingCsv}
                      onClick={() => void importSelectedCsvRows()}
                    >
                      导入选中的 {selectedCsvRows.length} 条
                    </Button>
                    <Button
                      variant="default"
                      onClick={() => setCsvPreview(null)}
                    >
                      取消预览
                    </Button>
                  </Group>
                </>
              )}
            </Stack>
          )}
        </Stack>
      </Drawer>
    </Stack>
  );
}
