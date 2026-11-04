"use client";

import Link from "next/link";
import {
  Accordion,
  Alert,
  Anchor,
  Avatar,
  Badge,
  Blockquote,
  Button,
  Divider,
  Group,
  Paper,
  Select,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import {
  IconBuilding,
  IconExternalLink,
  IconSearch,
  IconRefresh,
  IconBriefcase,
  IconBook2,
  IconLink,
} from "@tabler/icons-react";
import {
  EmptyState,
  Feedback,
  LoadingState,
  PageHeader,
} from "@/components/ui";
import classes from "./page.module.css";
import { useCallback, useEffect, useState } from "react";
import { ApiError, apiRequest, type CompanyArchive } from "@/lib/api";

const APPLICATION_LABELS: Record<string, string> = {
  to_research: "待了解",
  interested: "感兴趣",
  preparing: "准备中",
  applied: "已投递",
  assessment: "测评中",
  interview: "面试中",
  offer: "Offer",
  accepted: "已接受",
  rejected: "已拒绝",
  withdrawn: "已撤回",
  closed: "已关闭",
};

function formatDate(value: string | null) {
  if (!value) return "暂无记录";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(
    new Date(value),
  );
}

export default function CompaniesPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [companies, setCompanies] = useState<CompanyArchive[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [researchingJobId, setResearchingJobId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);

  const loadArchives = useCallback(async () => {
    try {
      setCompanies(await apiRequest<CompanyArchive[]>("/api/v1/companies"));
      setHasLoaded(true);
      setError("");
      setRequiresLogin(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法载入公司档案。");
      setRequiresLogin(cause instanceof ApiError && cause.status === 401);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadArchives();
  }, [loadArchives]);

  async function researchJob(jobId: string) {
    setResearchingJobId(jobId);
    setError("");
    setNotice("");
    try {
      await apiRequest(`/api/v1/jobs/${jobId}/research?refresh=true`, {
        method: "POST",
      });
      await loadArchives();
      setNotice("研究结果已保存到对应公司档案。请留意来源日期并打开原文核验。");
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "公司研究失败，请稍后重试。",
      );
      if (cause instanceof ApiError && cause.status === 401)
        setRequiresLogin(true);
    } finally {
      setResearchingJobId(null);
    }
  }

  const selected =
    companies.find((company) => company.id === selectedId) ?? companies[0];
  const visibleCompanies = companies.filter((company) =>
    `${company.name} ${company.industry ?? ""}`
      .toLocaleLowerCase()
      .includes(search.trim().toLocaleLowerCase()),
  );

  return (
    <Stack gap="lg">
      <PageHeader
        title="公司档案"
        description="按公司整理已保存岗位、招聘批次和有来源的公开研究。"
        actions={
          <Button
            component={Link}
            href="/jobs"
            variant="light"
            leftSection={<IconBriefcase size={17} />}
          >
            管理岗位
          </Button>
        }
      />
      <Feedback error={error} notice={notice} requiresLogin={requiresLogin} />
      {loading ? (
        <LoadingState />
      ) : !hasLoaded ? (
        requiresLogin ? null : (
          <EmptyState
            title="无法载入公司档案"
            description="请重试读取已保存的公司信息。"
            action={
              <Button variant="default" onClick={() => void loadArchives()}>
                重新载入
              </Button>
            }
          />
        )
      ) : !companies.length ? (
        <EmptyState
          title="还没有公司档案"
          description="在岗位中填写公司名称后，系统会自动建立对应档案。"
          action={
            <Button component={Link} href="/jobs">
              去管理岗位
            </Button>
          }
        />
      ) : (
        <>
          <Select
            hiddenFrom="sm"
            label="选择公司"
            value={selected?.id ?? null}
            onChange={setSelectedId}
            data={companies.map((company) => ({
              value: company.id,
              label: company.name,
            }))}
            searchable
            allowDeselect={false}
          />
          <div className={classes.workspace}>
            <Paper
              withBorder
              p="md"
              radius="lg"
              className={classes.directory}
              visibleFrom="sm"
              aria-label="公司档案列表"
            >
              <TextInput
                aria-label="搜索已保存公司"
                placeholder="搜索已保存公司"
                leftSection={<IconSearch size={16} />}
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                mb="md"
              />
              <Stack gap={4}>
                {visibleCompanies.map((company) => (
                  <UnstyledButton
                    key={company.id}
                    data-active={selected?.id === company.id || undefined}
                    className={classes.companyLink}
                    onClick={() => setSelectedId(company.id)}
                  >
                    <Avatar radius="md" size={36} color="teal">
                      {company.name.slice(0, 1)}
                    </Avatar>
                    <div className={classes.companyName}>
                      <Text fw={600} size="sm" lineClamp={2}>
                        {company.name}
                      </Text>
                      <Text c="dimmed" size="xs">
                        {company.jobs.length} 个岗位
                      </Text>
                    </div>
                  </UnstyledButton>
                ))}
                {!visibleCompanies.length && (
                  <Text c="dimmed" size="sm" p="md">
                    没有找到该公司。
                  </Text>
                )}
              </Stack>
            </Paper>
            {selected && (
              <Paper
                withBorder
                p={{ base: "md", sm: "xl" }}
                radius="lg"
                className={classes.detail}
              >
                <Stack gap="lg">
                  <Group align="flex-start" wrap="nowrap">
                    <Avatar radius="lg" size={54} color="teal">
                      <IconBuilding size={28} />
                    </Avatar>
                    <div className={classes.companyName}>
                      <Title order={2}>{selected.name}</Title>
                      <Text size="sm" c="dimmed" mt={4}>
                        {selected.industry || "招聘公司"}
                      </Text>
                    </div>
                    <Badge variant="light">{selected.jobs.length} 个岗位</Badge>
                  </Group>
                  <Group gap="md">
                    {selected.website_url && (
                      <Anchor
                        size="sm"
                        href={selected.website_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        公司官网 <IconExternalLink size={13} />
                      </Anchor>
                    )}
                    {selected.recruitment_url && (
                      <Anchor
                        size="sm"
                        href={selected.recruitment_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        招聘主页 <IconExternalLink size={13} />
                      </Anchor>
                    )}
                  </Group>
                  {selected.batches.length > 0 && (
                    <Group gap="xs" aria-label="招聘批次">
                      {selected.batches.map((batch) => (
                        <Badge variant="light" color="gray" key={batch}>
                          {batch}
                        </Badge>
                      ))}
                    </Group>
                  )}
                  <Tabs defaultValue="jobs" key={selected.id}>
                    <Tabs.List mb="lg">
                      <Tabs.Tab
                        value="jobs"
                        leftSection={<IconBriefcase size={16} />}
                      >
                        已保存岗位
                      </Tabs.Tab>
                      <Tabs.Tab
                        value="research"
                        leftSection={<IconBook2 size={16} />}
                      >
                        公开研究
                      </Tabs.Tab>
                      <Tabs.Tab
                        value="sources"
                        leftSection={<IconLink size={16} />}
                      >
                        来源与备注
                      </Tabs.Tab>
                    </Tabs.List>
                    <Tabs.Panel value="jobs">
                      <Stack gap="md" aria-label={`${selected.name}的岗位`}>
                        {!selected.jobs.length ? (
                          <EmptyState title="当前没有关联岗位" />
                        ) : (
                          selected.jobs.map((job, index) => (
                            <div key={job.id}>
                              {index > 0 && <Divider mb="md" />}
                              <Group justify="space-between" align="flex-start">
                                <div className={classes.jobInfo}>
                                  <Title order={4}>
                                    {job.title || "未填写职位"}
                                  </Title>
                                  <Group gap="xs" mt="sm">
                                    {[job.city, job.job_type, job.batch]
                                      .filter(Boolean)
                                      .map((item) => (
                                        <Badge
                                          variant="light"
                                          color="gray"
                                          key={item}
                                        >
                                          {item}
                                        </Badge>
                                      ))}
                                  </Group>
                                  <Text size="sm" c="dimmed" mt="sm">
                                    截止：{job.deadline || "未填写"}
                                  </Text>
                                </div>
                                <Button
                                  size="sm"
                                  variant="light"
                                  loading={researchingJobId === job.id}
                                  disabled={
                                    researchingJobId !== null &&
                                    researchingJobId !== job.id
                                  }
                                  leftSection={<IconRefresh size={15} />}
                                  onClick={() => void researchJob(job.id)}
                                >
                                  {job.researched_at ? "重新研究" : "开始研究"}
                                </Button>
                              </Group>
                              {job.application_status && (
                                <Badge variant="outline" color="gray" mt="sm">
                                  {APPLICATION_LABELS[job.application_status] ||
                                    job.application_status}
                                </Badge>
                              )}
                              {job.research_summary && (
                                <Text
                                  size="sm"
                                  mt="md"
                                  className={classes.sourceText}
                                >
                                  {job.research_summary}
                                  {job.research_is_stale ? "（可能过期）" : ""}
                                </Text>
                              )}
                              {job.source_url && (
                                <Anchor
                                  size="sm"
                                  display="inline-block"
                                  mt="sm"
                                  href={job.source_url}
                                  rel="noreferrer"
                                  target="_blank"
                                >
                                  招聘原始来源 <IconExternalLink size={13} />
                                </Anchor>
                              )}
                            </div>
                          ))
                        )}
                      </Stack>
                    </Tabs.Panel>
                    <Tabs.Panel value="research">
                      <Stack gap="lg" aria-label={`${selected.name}的研究归档`}>
                        <Group gap="xs">
                          <Badge variant="light">
                            {selected.research_count} 份研究
                          </Badge>
                          <Badge variant="light" color="gray">
                            {selected.finding_count} 条引用事实
                          </Badge>
                          <Badge variant="light" color="gray">
                            {selected.source_count} 个来源
                          </Badge>
                        </Group>
                        <Text size="sm" className={classes.sourceText}>
                          {selected.research_summary}
                        </Text>
                        {selected.stale_research_count > 0 && (
                          <Alert color="yellow" variant="light">
                            {selected.stale_research_count} 份研究超过 7
                            天，招聘信息可能已变化，请重新研究或核对官网。
                          </Alert>
                        )}
                        {selected.no_evidence &&
                          selected.research_count > 0 && (
                            <Alert color="yellow" variant="light">
                              当前研究没有可支持事实摘要的证据。来源仍可查看，请勿把无证据结果当作公司事实。
                            </Alert>
                          )}
                        {selected.findings.map((finding, index) => (
                          <div
                            key={`${finding.job_id}-${finding.source_url}-${index}`}
                          >
                            <Text fw={600} size="sm">
                              {finding.claim}
                            </Text>
                            <Text c="dimmed" size="xs" mt={4}>
                              {finding.job_title || "公司公开信息"}，
                              {formatDate(finding.researched_at)}
                              {finding.is_stale ? "，可能过期" : ""}
                            </Text>
                            <Blockquote
                              color="teal"
                              mt="sm"
                              mb="sm"
                              className={classes.quote}
                            >
                              {finding.quote}
                            </Blockquote>
                            <Anchor
                              size="sm"
                              href={finding.source_url}
                              rel="noreferrer"
                              target="_blank"
                            >
                              来源：{finding.source_title}{" "}
                              <IconExternalLink size={13} />
                            </Anchor>
                          </div>
                        ))}
                      </Stack>
                    </Tabs.Panel>
                    <Tabs.Panel value="sources">
                      <Stack gap="lg">
                        {selected.notes && (
                          <div>
                            <Title order={4} mb="sm">
                              我保存的公司备注
                            </Title>
                            <Text size="sm" className={classes.sourceText}>
                              {selected.notes}
                            </Text>
                          </div>
                        )}
                        <div>
                          <Title order={4} mb="md">
                            保存的来源链接（{selected.sources.length}）
                          </Title>
                          {!selected.sources.length ? (
                            <Text c="dimmed" size="sm">
                              研究完成后，可在这里核对来源。
                            </Text>
                          ) : (
                            <Accordion variant="separated">
                              {selected.sources.map((source) => (
                                <Accordion.Item
                                  key={`${source.research_run_id}-${source.source_id}`}
                                  value={`${source.research_run_id}-${source.source_id}`}
                                >
                                  <Accordion.Control>
                                    {source.title}
                                  </Accordion.Control>
                                  <Accordion.Panel>
                                    <Stack gap="sm">
                                      <Text size="xs" c="dimmed">
                                        {source.job_title || "公司公开信息"}，
                                        {formatDate(source.researched_at)}
                                        {source.is_stale ? "，可能过期" : ""}
                                      </Text>
                                      <Text
                                        size="sm"
                                        className={classes.sourceText}
                                      >
                                        {source.excerpt}
                                      </Text>
                                      <Anchor
                                        href={source.url}
                                        target="_blank"
                                        rel="noreferrer"
                                        size="sm"
                                      >
                                        打开来源 <IconExternalLink size={13} />
                                      </Anchor>
                                    </Stack>
                                  </Accordion.Panel>
                                </Accordion.Item>
                              ))}
                            </Accordion>
                          )}
                        </div>
                      </Stack>
                    </Tabs.Panel>
                  </Tabs>
                </Stack>
              </Paper>
            )}
          </div>
          <Text c="dimmed" size="xs">
            公开研究来自只读搜索；搜索片段可能不完整。日期、招聘状态和要求请以招聘官网原文为准。
          </Text>
        </>
      )}
    </Stack>
  );
}
