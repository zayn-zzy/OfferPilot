import { randomUUID } from "node:crypto";
import type { Page } from "@playwright/test";
import type {
  AgentTask,
  AgentTaskPlan,
  AgentWorkspace,
  ApplicationPrepPack,
  CompanyArchive,
  CompanyResearch,
  DashboardSummary,
  ExternalAction,
  JobCsvPreview,
  JobPosting,
  KnowledgeAnswer,
  KnowledgeNote,
  Reminder,
  ReminderCenter,
  ResumeVersionSummary,
  SkillApproval,
  SkillAuditEvent,
  SkillCatalogItem,
  SkillDraft,
  SkillRun,
  User,
  UserModelSettings,
} from "../../lib/api";

export const NOW = "2030-06-03T08:00:00Z";
export const JOB_ID = "11111111-1111-4111-8111-111111111111";
export const RESUME_ID = "22222222-2222-4222-8222-222222222222";
export const SOURCE =
  "星河科技招聘后端工程师（AI 导入岗位），工作地点上海，校招，2031 届秋招，截止日期2030-06-20，要求本科及以上，熟悉 Python 和 SQL。";
export const user: User = {
  id: "99999999-9999-4999-8999-999999999999",
  email: "ui-demo@example.com",
  timezone: "Asia/Shanghai",
  created_at: NOW,
};
export const job: JobPosting = {
  id: JOB_ID,
  company_id: "company-1",
  company_name: "星河科技",
  company_website_url: "https://example.com",
  recruitment_url: "https://example.com/careers",
  industry: "互联网",
  company_notes: "关注研发团队与工作地点。",
  title: "后端工程师",
  city: "上海",
  job_type: "校招",
  batch: "2031 届秋招",
  deadline: "2030-06-20",
  education_requirement: "本科及以上",
  required_skills: ["Python", "SQL"],
  description: SOURCE,
  source_url: "https://example.com/careers/backend",
  source_type: "agent",
  source_captured_at: NOW,
  tags: ["优先申请"],
  review_status: "verified",
  created_at: NOW,
  updated_at: NOW,
  application: {
    id: "application-1",
    status: "preparing",
    applied_at: null,
    resume_version_id: RESUME_ID,
    notes: "准备项目介绍",
    next_action: "完成在线测评",
    next_action_due: "2030-06-10",
    created_at: NOW,
    updated_at: NOW,
  },
};
export const resume: ResumeVersionSummary & { extracted_text: string } = {
  id: RESUME_ID,
  filename: "后端求职简历.pdf",
  source_type: "upload" as const,
  content_type: "application/pdf",
  created_at: NOW,
  confirmed_at: NOW,
  extracted_char_count:
    "使用 Python 和 SQL 开发岗位管理项目，完成检索与权限隔离。".length,
  extracted_text: "使用 Python 和 SQL 开发岗位管理项目，完成检索与权限隔离。",
};
export const skillDraft: SkillDraft = {
  summary: "已根据岗位与已确认简历整理申请准备草稿。",
  checklist: [
    {
      title: "核对项目介绍",
      reason: "突出真实的 Python 和 SQL 实践",
      needs_user_confirmation: true,
    },
  ],
  sections: [
    {
      title: "项目经验草稿",
      content: "我使用 Python 和 SQL 开发岗位管理项目。",
      needs_user_input: false,
      citations: [
        {
          source_id: "resume-1",
          source_label: resume.filename,
          source_url: null,
          quote: "使用 Python 和 SQL 开发岗位管理项目",
        },
      ],
    },
  ],
  open_questions: ["请补充真实项目规模。"],
  warnings: ["草稿需要人工核对。"],
};
export const catalogs: SkillCatalogItem[] = [
  ["job_analysis", "岗位分析"],
  ["resume_targeting", "简历针对性建议"],
  ["application_answers", "申请问答草稿"],
  ["company_research", "公司调研整理"],
  ["interview_prep", "面试准备"],
  ["application_prep_pack", "申请准备包"],
].map(([id, name]) => ({
  id: id as SkillCatalogItem["id"],
  version: "1.0.0",
  name,
  description: "根据真实资料生成可核验的求职草稿。",
  inputs: { job_id: "已保存岗位" },
  outputs: { sections: "带引用的草稿" },
  boundaries: ["草稿不会自动提交招聘网站。"],
  example_input: { job_title: "后端工程师" },
  example_output: { summary: "待核对草稿" },
}));
export const research: CompanyResearch = {
  run_id: "research-1",
  job_id: JOB_ID,
  company_name: job.company_name!,
  job_title: job.title,
  query: "星河科技 后端工程师 校招",
  researched_at: NOW,
  is_stale: false,
  summary: "公司公开招聘页列出了后端工程师岗位。",
  findings: [
    {
      claim: "公开招聘页列出后端工程师岗位。",
      source_id: "web-1",
      quote: "招聘后端工程师",
    },
  ],
  sources: [
    {
      source_id: "web-1",
      title: "星河科技招聘",
      url: "https://example.com/careers",
      excerpt: SOURCE,
      age: null,
    },
  ],
  no_evidence: false,
  warning: null,
};
export const company: CompanyArchive = {
  id: "company-1",
  name: job.company_name!,
  industry: job.industry,
  website_url: job.company_website_url,
  recruitment_url: job.recruitment_url,
  notes: job.company_notes,
  batches: [job.batch!],
  jobs: [
    {
      id: JOB_ID,
      title: job.title,
      city: job.city,
      job_type: job.job_type,
      batch: job.batch,
      deadline: job.deadline,
      application_status: "preparing",
      source_url: job.source_url,
      source_captured_at: NOW,
      research_summary: research.summary,
      research_is_stale: false,
      research_no_evidence: false,
      researched_at: NOW,
    },
  ],
  research_summary: research.summary,
  research_count: 1,
  finding_count: 1,
  source_count: 1,
  last_researched_at: NOW,
  stale_research_count: 0,
  no_evidence: false,
  findings: [
    {
      job_id: JOB_ID,
      job_title: job.title,
      claim: research.findings[0].claim,
      quote: research.findings[0].quote,
      source_title: research.sources[0].title,
      source_url: research.sources[0].url,
      researched_at: NOW,
      is_stale: false,
    },
  ],
  sources: [
    {
      research_run_id: research.run_id,
      job_id: JOB_ID,
      job_title: job.title,
      ...research.sources[0],
      researched_at: NOW,
      is_stale: false,
    },
  ],
};
export function makePlan(id = "plan-1"): AgentTaskPlan {
  return {
    id,
    task_type: "task_plan",
    status: "awaiting_confirmation",
    preview: {
      title: "跟进在线测评",
      details: "检查测评邮件与准备事项。",
      kind: "assessment",
      event_at: "2030-06-10T01:00:00Z",
      timezone: user.timezone,
      job_id: JOB_ID,
      job_label: "星河科技 / 后端工程师",
      clarification_question: null,
    },
    reminder_id: null,
    events: [
      {
        id: 1,
        event: "completed",
        message: "提醒草稿已生成，请确认。",
        created_at: NOW,
      },
    ],
    error_code: null,
    error_message: null,
    model_name: "fixture-no-model-call",
    attempt_count: 1,
    created_at: NOW,
    updated_at: NOW,
    finished_at: NOW,
  };
}
export function makeExtraction(
  status: AgentTask["status"] = "succeeded",
): AgentTask {
  const names = {
    company_name: "星河科技",
    title: "AI 导入岗位",
    city: "上海",
    job_type: "校招",
    batch: "2031 届秋招",
    deadline: "2030-06-20",
    education_requirement: "本科及以上",
    required_skills: ["Python", "SQL"],
  };
  return {
    id: "extraction-1",
    task_type: "job_extraction",
    status,
    source_url: "https://example.com/new-ai-job",
    result:
      status === "succeeded" || status === "confirmed"
        ? {
            fields: Object.fromEntries(
              Object.entries(names).map(([key, value]) => [
                key,
                { value, confidence: 0.95, evidence: SOURCE },
              ]),
            ),
            needs_review_fields: [],
          }
        : null,
    events: [
      {
        id: 1,
        event: status === "failed" ? "failed" : "progress",
        message:
          status === "failed"
            ? "模型服务暂时不可用，请重试。"
            : "岗位信息已整理。",
        created_at: NOW,
      },
    ],
    error_code: status === "failed" ? "provider_unavailable" : null,
    error_message: status === "failed" ? "模型服务暂时不可用，请重试。" : null,
    model_name: "fixture-no-model-call",
    attempt_count: 1,
    job_id: null,
    created_at: NOW,
    updated_at: NOW,
    finished_at: status === "running" ? null : NOW,
  };
}
export const reminder: Reminder = {
  id: "reminder-1",
  job_id: JOB_ID,
  job_label: "星河科技 / 后端工程师",
  title: "完成在线测评",
  details: "准备证件与项目介绍。",
  kind: "assessment",
  event_at: "2030-06-10T01:00:00Z",
  notify_at: "2030-06-10T00:00:00Z",
  timezone: user.timezone,
  lead_minutes: 60,
  channel: "in_app",
  status: "scheduled",
  schedule_revision: 1,
  delivery_attempts: 0,
  last_delivery_error: null,
  created_at: NOW,
  updated_at: NOW,
};
export const skillRun: SkillRun = {
  id: "skill-run-1",
  skill_id: "application_prep_pack",
  skill_version: "1.0.0",
  job_id: JOB_ID,
  status: "succeeded",
  result: skillDraft,
  events: [
    {
      id: 1,
      event: "completed",
      message: "草稿已生成并核验引用。",
      created_at: NOW,
    },
  ],
  error_code: null,
  error_message: null,
  model_name: "fixture-no-model-call",
  attempt_count: 1,
  created_at: NOW,
  updated_at: NOW,
  finished_at: NOW,
};
export const approval: SkillApproval = {
  id: "approval-1",
  agent_run_id: skillRun.id,
  job_id: JOB_ID,
  action_type: "save_application_prep_pack",
  summary: "将已核对的申请准备包保存到本地工作台。",
  status: "pending",
  expires_at: "2030-06-03T08:30:00Z",
  approved_at: null,
  executed_at: null,
  created_at: NOW,
};
export const emailAction: ExternalAction = {
  id: "email-1",
  job_id: JOB_ID,
  action_type: "send_email",
  target: "recruiter@example.com",
  summary: "发送一封经用户确认的求职邮件。",
  payload: {
    subject: "后端工程师申请材料",
    body: "您好，这是我核对后的求职材料，请查收。",
  },
  status: "pending",
  result: null,
  expires_at: "2030-06-03T08:15:00Z",
  approved_at: null,
  started_at: null,
  executed_at: null,
  created_at: NOW,
  updated_at: NOW,
};
const modelSettings: UserModelSettings = {
  chat_completions: {
    endpoint_configured: true,
    default_model: "demo-chat",
    model_override: null,
    effective_model: "demo-chat",
    credential_configured: true,
    credential_available: true,
    credential_source: "account",
    ready: true,
  },
  embeddings: {
    endpoint_configured: true,
    default_model: "demo-embedding",
    model_override: null,
    effective_model: "demo-embedding",
    credential_configured: true,
    credential_available: true,
    credential_source: "account",
    ready: true,
  },
};
const workspace: AgentWorkspace = {
  timezone: user.timezone,
  capabilities: [
    {
      id: "job_extraction",
      title: "提取岗位信息",
      description: "从原文整理字段和引用。",
      action_label: "粘贴招聘原文",
      href: "/jobs?task=extract",
      action_level: "local_draft",
      confirmation_required: true,
    },
    {
      id: "job_match",
      title: "查看岗位匹配",
      description: "比较档案、简历和岗位要求。",
      action_label: "选择岗位",
      href: "/jobs",
      action_level: "read_only",
      confirmation_required: false,
    },
    {
      id: "company_research",
      title: "研究招聘公司",
      description: "查阅公开来源并保留引用。",
      action_label: "查看公司档案",
      href: "/companies",
      action_level: "read_only",
      confirmation_required: false,
    },
    {
      id: "knowledge_qa",
      title: "询问个人求职资料",
      description: "根据已确认资料回答。",
      action_label: "提问并查看引用",
      href: "/knowledge",
      action_level: "read_only",
      confirmation_required: false,
    },
    {
      id: "career_materials",
      title: "准备求职材料",
      description: "生成有依据的材料草稿。",
      action_label: "选择 Skill 与岗位",
      href: "/skills",
      action_level: "local_draft",
      confirmation_required: true,
    },
  ],
  recent_runs: [
    {
      id: research.run_id,
      task_type: "company_research",
      skill_id: null,
      status: "succeeded",
      created_at: NOW,
      updated_at: NOW,
      finished_at: NOW,
      job_id: JOB_ID,
      job_label: "星河科技 / 后端工程师",
      duration_ms: 1200,
      total_tokens: 340,
      estimated_cost_usd: 0.001,
    },
  ],
};

export type MockCall = {
  method: string;
  path: string;
  body: Record<string, unknown>;
};
export type MockOptions = {
  unauthorized?: boolean;
  empty?: boolean;
  extractionStatus?: AgentTask["status"];
  failures?: Record<string, { status: number; detail: string }>;
};

/** Browser-only fixtures. Every /api/v1 request is intercepted; no provider or SMTP request leaves the test. */
export async function installApi(page: Page, options: MockOptions = {}) {
  const state = {
    user: structuredClone(user),
    jobs: options.empty ? [] : [structuredClone(job)],
    profile: {
      graduation_year: 2031,
      education: "本科",
      major: "计算机科学",
      target_roles: ["后端开发"],
      target_cities: ["上海"],
      industries: ["互联网"],
      skills: ["Python", "SQL"],
    },
    resumes: options.empty ? [] : [structuredClone(resume)],
    notes: options.empty
      ? []
      : [
          {
            id: "note-1",
            title: "项目经历",
            content: resume.extracted_text,
            created_at: NOW,
            updated_at: NOW,
          } as KnowledgeNote,
        ],
    plans: options.empty ? [] : [makePlan()],
    extraction: makeExtraction(options.extractionStatus),
    reminders: options.empty ? [] : [structuredClone(reminder)],
    notifications: options.empty
      ? []
      : [
          {
            id: "notification-1",
            reminder_id: reminder.id,
            title: "测评即将开始",
            body: "请准备好在线测评材料。",
            created_at: NOW,
            read_at: null as string | null,
          },
        ],
    skillRuns: options.empty ? [] : [structuredClone(skillRun)],
    approvals: options.empty ? [] : [structuredClone(approval)],
    packs: [] as ApplicationPrepPack[],
    audit: [] as SkillAuditEvent[],
    actions: options.empty ? [] : [structuredClone(emailAction)],
    calls: [] as MockCall[],
    unhandled: [] as string[],
  };
  const center = (): ReminderCenter => ({
    reminders: state.reminders,
    notifications: state.notifications,
    unread_count: state.notifications.filter((item) => !item.read_at).length,
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    const method = request.method();
    let body: Record<string, unknown> = {};
    try {
      body = (request.postDataJSON() as Record<string, unknown>) ?? {};
    } catch {
      /* multipart file bodies are not JSON */
    }
    state.calls.push({ method, path, body });
    const failure = options.failures?.[path];
    if (failure)
      return route.fulfill({
        status: failure.status,
        json: { detail: failure.detail },
      });
    if (
      options.unauthorized &&
      !["/auth/login", "/auth/register"].includes(path)
    )
      return route.fulfill({
        status: 401,
        json: { detail: "Authentication required" },
      });
    const reply = (json: unknown, status = 200) =>
      route.fulfill({ status, json });
    if (["/auth/me", "/auth/login", "/auth/register"].includes(path))
      return reply(state.user, path === "/auth/register" ? 201 : 200);
    if (path === "/auth/logout") return route.fulfill({ status: 204 });
    if (path === "/auth/me/timezone") {
      state.user.timezone = String(body.timezone);
      return reply({
        user: state.user,
        recalculated_reminders: state.reminders.length,
      });
    }
    if (path === "/dashboard") {
      const dashboard: DashboardSummary = {
        email: state.user.email,
        timezone: state.user.timezone,
        today: "2030-06-03",
        current_stage: state.jobs.length
          ? {
              status: "preparing",
              job_id: JOB_ID,
              job_label: "星河科技 / 后端工程师",
              updated_at: NOW,
            }
          : null,
        stage_counts: state.jobs.length
          ? [{ status: "preparing", count: state.jobs.length }]
          : [],
        upcoming_tasks: state.reminders.map((item) => ({
          id: item.id,
          kind: "reminder",
          title: item.title,
          due_at: item.event_at,
          due_date: null,
          timezone: item.timezone,
          status: item.status,
          job_id: item.job_id,
          job_label: item.job_label,
        })),
        approaching_deadlines: state.jobs.map((item) => ({
          job_id: item.id,
          job_label: `${item.company_name} / ${item.title}`,
          deadline: item.deadline!,
          days_remaining: 17,
          application_status: item.application?.status ?? null,
        })),
        recent_agent_runs: [],
      };
      return reply(dashboard);
    }
    if (path === "/profile") {
      if (method === "PUT") Object.assign(state.profile, body);
      return reply(state.profile);
    }
    if (path === "/resumes") return reply(state.resumes);
    if (path === "/resumes/upload" || path === "/resumes/text") {
      const created = {
        ...resume,
        id: randomUUID(),
        filename: path.endsWith("upload") ? "upload.pdf" : "粘贴简历",
        confirmed_at: null as string | null,
        extracted_text: String(body.text ?? resume.extracted_text),
      };
      state.resumes.unshift(created as typeof resume);
      return reply(created, 201);
    }
    if (path.startsWith("/resumes/")) {
      const entry = state.resumes.find(
        (item) => item.id === path.split("/")[2],
      );
      if (!entry) return reply({ detail: "简历不存在" }, 404);
      if (path.endsWith("/confirm")) entry.confirmed_at = NOW;
      if (method === "DELETE") {
        state.resumes = state.resumes.filter((item) => item.id !== entry.id);
        return route.fulfill({ status: 204 });
      }
      return reply(entry);
    }
    if (path === "/jobs/import/preview") {
      const row = {
        ...job,
        title: "CSV 导入岗位",
        source_url: "https://example.com/csv",
      };
      const preview: JobCsvPreview = {
        ready_count: 1,
        duplicate_count: 0,
        invalid_count: 0,
        rows: [
          {
            row_number: 2,
            status: "ready",
            company_name: row.company_name,
            title: row.title,
            city: row.city,
            deadline: row.deadline,
            source_url: row.source_url,
            data: row,
            errors: [],
            duplicate_detail: null,
            duplicate_job_id: null,
            duplicate_job_company_name: null,
            duplicate_job_title: null,
            duplicate_of_row_number: null,
          },
        ],
      };
      return reply(preview);
    }
    if (path === "/jobs/import") {
      const rows = body.jobs as JobPosting[];
      const imported = rows.map((item) => ({
        ...job,
        ...item,
        id: randomUUID(),
      }));
      state.jobs.unshift(...imported);
      return reply(imported, 201);
    }
    if (path === "/jobs") {
      if (method === "POST") {
        const created = {
          ...job,
          ...body,
          id: randomUUID(),
          source_type: "manual",
          application: null,
        } as JobPosting;
        state.jobs.unshift(created);
        return reply(created, 201);
      }
      const search = url.searchParams.get("search")?.toLowerCase();
      return reply(
        search
          ? state.jobs.filter((item) =>
              `${item.company_name} ${item.title}`
                .toLowerCase()
                .includes(search),
            )
          : state.jobs,
      );
    }
    if (path.startsWith("/jobs/")) {
      const item = state.jobs.find((entry) => entry.id === path.split("/")[2]);
      if (!item) return reply({ detail: "岗位不存在" }, 404);
      if (path.endsWith("/application/history"))
        return reply([
          {
            id: "history-1",
            from_status: "interested",
            to_status: item.application?.status ?? "preparing",
            created_at: NOW,
          },
        ]);
      if (path.endsWith("/application")) {
        item.application = {
          id: "application-new",
          status: "preparing",
          applied_at: null,
          resume_version_id: null,
          notes: null,
          next_action: null,
          next_action_due: null,
          created_at: NOW,
          updated_at: NOW,
          ...item.application,
          ...body,
        } as JobPosting["application"];
        return reply(item);
      }
      if (path.endsWith("/match"))
        return reply({
          job_id: item.id,
          resume_id: RESUME_ID,
          resume_filename: resume.filename,
          criteria: [
            {
              key: "education",
              label: "学历",
              category: "hard_requirement",
              status: "meets",
              requirement: "本科",
              candidate_value: "本科",
              explanation: "与已保存学历一致。",
            },
          ],
          skills: [
            {
              skill: "Python",
              status: "evidenced",
              evidence: "使用 Python 和 SQL 开发岗位管理项目",
            },
          ],
          disclaimer: "匹配分析不代表录用概率。",
        });
      if (path.endsWith("/research")) return reply(research);
      if (path.endsWith("/merge")) {
        item.tags = Array.from(
          new Set([...item.tags, ...((body.tags as string[]) ?? [])]),
        );
        return reply(item);
      }
      if (method === "PUT") Object.assign(item, body);
      if (method === "DELETE") {
        state.jobs = state.jobs.filter((entry) => entry.id !== item.id);
        return route.fulfill({ status: 204 });
      }
      return reply(item);
    }
    if (path === "/agent/workspace")
      return reply({
        ...workspace,
        recent_runs: options.empty ? [] : workspace.recent_runs,
      });
    if (path === "/agent/task-plans") {
      if (method === "POST") {
        const plan = makePlan(randomUUID());
        state.plans.unshift(plan);
        return reply(plan, 202);
      }
      return reply(state.plans);
    }
    if (path.startsWith("/agent/task-plans/")) {
      const plan = state.plans.find((item) => item.id === path.split("/")[3]);
      if (!plan) return reply({ detail: "任务不存在" }, 404);
      if (path.endsWith("/confirm")) {
        plan.status = "confirmed";
        plan.reminder_id = randomUUID();
        state.reminders.unshift({
          ...reminder,
          id: plan.reminder_id,
          title: plan.preview!.title!,
        });
      } else if (path.endsWith("/cancel")) plan.status = "cancelled";
      else if (path.endsWith("/retry")) plan.status = "awaiting_confirmation";
      return reply(plan);
    }
    if (path === "/agent/tasks") return reply([state.extraction]);
    if (path === "/agent/job-extractions") {
      state.extraction = makeExtraction();
      return reply(state.extraction, 202);
    }
    if (path.startsWith("/agent/tasks/")) {
      if (path.endsWith("/source")) return reply({ source_text: SOURCE });
      if (path.endsWith("/events"))
        return route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body: `id: 1\nevent: progress\ndata: ${JSON.stringify(state.extraction.events[0])}\n\n`,
        });
      if (path.endsWith("/retry")) state.extraction = makeExtraction();
      if (path.endsWith("/cancel")) state.extraction.status = "cancelled";
      if (path.endsWith("/confirm")) {
        const created = {
          ...job,
          ...body,
          id: randomUUID(),
          title: String(body.title ?? "AI 导入岗位"),
          source_url: state.extraction.source_url,
          application: null,
        } as JobPosting;
        state.jobs.unshift(created);
        state.extraction.status = "confirmed";
        state.extraction.job_id = created.id;
        return reply(created, 201);
      }
      if (method === "DELETE") return route.fulfill({ status: 204 });
      return reply(state.extraction);
    }
    if (/^\/agent\/jobs\/[^/]+\/evidence$/.test(path))
      return reply({
        id: "evidence-1",
        job_id: JOB_ID,
        source_url: job.source_url,
        source_text: SOURCE,
        field_evidence: makeExtraction().result!.fields,
        captured_at: NOW,
      });
    if (path === "/companies") return reply(options.empty ? [] : [company]);
    if (path === "/reminders") {
      if (method === "POST") {
        const created = { ...reminder, ...body, id: randomUUID() } as Reminder;
        state.reminders.unshift(created);
        return reply(created, 201);
      }
      return reply(center());
    }
    if (path.startsWith("/reminders/")) {
      const item = state.reminders.find(
        (entry) => entry.id === path.split("/")[2],
      );
      if (!item) return reply({ detail: "提醒不存在" }, 404);
      const operation = path.split("/")[3];
      item.status =
        operation === "complete"
          ? "completed"
          : operation === "cancel"
            ? "cancelled"
            : operation === "pause"
              ? "paused"
              : "scheduled";
      return reply(item);
    }
    if (path.startsWith("/notifications/")) {
      const item = state.notifications.find(
        (entry) => entry.id === path.split("/")[2],
      );
      if (item) item.read_at = NOW;
      return reply(item);
    }
    if (path === "/knowledge/notes") {
      if (method === "POST") {
        const note = {
          id: randomUUID(),
          title: String(body.title),
          content: String(body.content),
          created_at: NOW,
          updated_at: NOW,
        };
        state.notes.unshift(note);
        return reply(note, 201);
      }
      return reply(state.notes);
    }
    if (path.startsWith("/knowledge/notes/")) {
      state.notes = state.notes.filter(
        (item) => item.id !== path.split("/")[3],
      );
      return route.fulfill({ status: 204 });
    }
    if (path === "/knowledge/reindex")
      return reply({
        indexed_documents: state.notes.length + state.resumes.length,
        indexed_chunks: 4,
        embedding_model: "demo-embedding",
      });
    if (path === "/knowledge/ask") {
      const answer: KnowledgeAnswer = {
        answer: "你的项目经历包含 Python 和 SQL 实践。",
        no_evidence: false,
        citations: [
          {
            chunk_id: "chunk-1",
            source_type: "resume",
            source_id: RESUME_ID,
            source_name: resume.filename,
            quote: resume.extracted_text,
            relevance: 0.9,
          },
        ],
      };
      return reply(answer);
    }
    if (path === "/settings/models") return reply(modelSettings);
    if (path === "/skills") return reply(catalogs);
    if (path === "/skills/runs") {
      if (method === "POST") {
        const created = {
          ...skillRun,
          id: randomUUID(),
          skill_id: body.skill_id as SkillRun["skill_id"],
          job_id: String(body.job_id),
        };
        state.skillRuns.unshift(created);
        return reply(created, 202);
      }
      return reply(state.skillRuns);
    }
    if (/^\/skills\/runs\/[^/]+\/approval$/.test(path)) {
      const created = {
        ...approval,
        id: randomUUID(),
        agent_run_id: path.split("/")[3],
      };
      state.approvals.unshift(created);
      return reply(created, 201);
    }
    if (/^\/skills\/runs\/[^/]+\/(retry|cancel)$/.test(path)) {
      const item = state.skillRuns.find(
        (entry) => entry.id === path.split("/")[3],
      )!;
      item.status = path.endsWith("cancel") ? "cancelled" : "succeeded";
      return reply(item);
    }
    if (path === "/skills/approvals") return reply(state.approvals);
    if (path.startsWith("/skills/approvals/")) {
      const item = state.approvals.find(
        (entry) => entry.id === path.split("/")[3],
      )!;
      if (path.endsWith("/approve")) {
        item.status = "approved";
        item.approved_at = NOW;
      } else if (path.endsWith("/reject")) item.status = "rejected";
      else if (path.endsWith("/execute")) {
        item.status = "executed";
        item.executed_at = NOW;
        const pack: ApplicationPrepPack = {
          id: randomUUID(),
          job_id: item.job_id,
          agent_run_id: item.agent_run_id,
          skill_id: "application_prep_pack",
          skill_version: "1.0.0",
          content: skillDraft,
          created_at: NOW,
        };
        state.packs.unshift(pack);
        return reply(pack);
      }
      return reply(item);
    }
    if (path === "/skills/packs") return reply(state.packs);
    if (path === "/skills/audit") return reply(state.audit);
    if (path === "/external-actions/capabilities")
      return reply({
        email_send_enabled: true,
        email_send_requires_approval: true,
        recruitment_submission_enabled: false,
      });
    if (path === "/external-actions") {
      if (method === "POST") {
        const created: ExternalAction = {
          ...emailAction,
          id: randomUUID(),
          target: String(body.recipient),
          payload: { subject: String(body.subject), body: String(body.body) },
          job_id: body.job_id as string | null,
        };
        state.actions.unshift(created);
        return reply(created, 201);
      }
      return reply(state.actions);
    }
    if (path.startsWith("/external-actions/")) {
      const item = state.actions.find(
        (entry) => entry.id === path.split("/")[2],
      )!;
      if (path.endsWith("/approve")) {
        item.status = "approved";
        item.approved_at = NOW;
      } else if (path.endsWith("/reject")) item.status = "rejected";
      else if (path.endsWith("/execute")) {
        item.status = "executed";
        item.executed_at = NOW;
        item.result = { message_id: "fixture-message-id" };
      }
      return reply(item);
    }
    state.unhandled.push(`${method} ${path}`);
    return reply({ detail: "Mock endpoint not implemented" }, 404);
  });
  return state;
}

export const installApiFixtures = installApi;
export const ALL_ROUTES = [
  "/",
  "/login",
  "/register",
  "/dashboard",
  "/jobs",
  "/profile",
  "/knowledge",
  "/companies",
  "/reminders",
  "/agent",
  "/skills",
  "/actions",
  "/settings",
] as const;
