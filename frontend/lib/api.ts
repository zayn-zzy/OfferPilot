export type User = {
  id: string;
  email: string;
  timezone: string;
  created_at: string;
};

export type UserTimezoneUpdate = { user: User; recalculated_reminders: number };

export class ApiError extends Error {
  constructor(message: string, readonly status: number | null, readonly detail: unknown = null) {
    super(message);
    this.name = "ApiError";
  }
}

export function duplicateJobIdFromError(cause: unknown): string | null {
  if (!(cause instanceof ApiError) || cause.status !== 409) return null;
  if (typeof cause.detail !== "object" || cause.detail === null) return null;
  const detail = cause.detail as { code?: unknown; existing_job_id?: unknown };
  return detail.code === "duplicate_job_source" && typeof detail.existing_job_id === "string"
    ? detail.existing_job_id
    : null;
}

export const APPLICATION_STAGES = [
  "to_research",
  "interested",
  "preparing",
  "applied",
  "assessment",
  "interview",
  "offer",
  "accepted",
  "rejected",
  "withdrawn",
  "closed",
] as const;

export type ApplicationStage = (typeof APPLICATION_STAGES)[number];

export const APPLICATION_STAGE_LABELS: Record<ApplicationStage, string> = {
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

export type DashboardSummary = {
  email: string;
  timezone: string;
  today: string;
  current_stage: {
    status: ApplicationStage;
    job_id: string;
    job_label: string;
    updated_at: string;
  } | null;
  stage_counts: { status: ApplicationStage; count: number }[];
  upcoming_tasks: {
    id: string;
    kind: "reminder" | "application_follow_up";
    title: string;
    due_at: string | null;
    due_date: string | null;
    timezone: string;
    status: string;
    job_id: string | null;
    job_label: string | null;
  }[];
  approaching_deadlines: {
    job_id: string;
    job_label: string;
    deadline: string;
    days_remaining: number;
    application_status: ApplicationStage | null;
  }[];
  recent_agent_runs: {
    id: string;
    task_type: string;
    status: string;
    created_at: string;
    finished_at: string | null;
    job_id: string | null;
    job_label: string | null;
  }[];
};

export type Application = {
  id: string;
  status: ApplicationStage;
  applied_at: string | null;
  resume_version_id: string | null;
  notes: string | null;
  next_action: string | null;
  next_action_due: string | null;
  created_at: string;
  updated_at: string;
};

export type JobPosting = {
  id: string;
  company_id: string | null;
  company_name: string | null;
  company_website_url: string | null;
  recruitment_url: string | null;
  industry: string | null;
  company_notes: string | null;
  title: string | null;
  city: string | null;
  job_type: string | null;
  batch: string | null;
  deadline: string | null;
  education_requirement: string | null;
  required_skills: string[];
  description: string | null;
  source_url: string | null;
  source_type: "manual" | "paste" | "link" | "agent";
  source_captured_at: string;
  tags: string[];
  review_status: "needs_review" | "verified";
  created_at: string;
  updated_at: string;
  application: Application | null;
};

export type JobPostingWrite = {
  company_name: string | null;
  company_website_url: string | null;
  recruitment_url: string | null;
  industry: string | null;
  company_notes: string | null;
  title: string | null;
  city: string | null;
  job_type: string | null;
  batch: string | null;
  deadline: string | null;
  education_requirement: string | null;
  required_skills: string[];
  description: string | null;
  source_url: string | null;
  source_type: "manual" | "paste" | "link" | "agent";
  tags: string[];
};

export type JobCsvPreviewRow = {
  row_number: number;
  status: "ready" | "duplicate" | "invalid";
  company_name: string | null;
  title: string | null;
  city: string | null;
  deadline: string | null;
  source_url: string | null;
  data: JobPostingWrite | null;
  errors: string[];
  duplicate_detail: string | null;
  duplicate_job_id: string | null;
  duplicate_job_company_name: string | null;
  duplicate_job_title: string | null;
  duplicate_of_row_number: number | null;
};

export type JobCsvPreview = {
  rows: JobCsvPreviewRow[];
  ready_count: number;
  duplicate_count: number;
  invalid_count: number;
};

export type ApplicationStatusEvent = {
  id: string;
  from_status: ApplicationStage | null;
  to_status: ApplicationStage;
  created_at: string;
};

export type ResumeVersionSummary = {
  id: string;
  filename: string;
  source_type: "upload" | "paste";
  content_type: string;
  created_at: string;
  confirmed_at: string | null;
  extracted_char_count: number;
};

export type KnowledgeNote = {
  id: string;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
};

export type KnowledgeAnswer = {
  answer: string;
  citations: {
    chunk_id: string;
    source_type: "resume" | "note";
    source_id: string;
    source_name: string;
    quote: string;
    relevance: number;
  }[];
  no_evidence: boolean;
};

export type KnowledgeReindex = {
  indexed_documents: number;
  indexed_chunks: number;
  embedding_model: string;
};

export type JobMatch = {
  job_id: string;
  resume_id: string;
  resume_filename: string;
  criteria: {
    key: string;
    label: string;
    category: "hard_requirement" | "preference";
    status: "meets" | "does_not_meet" | "unknown";
    requirement: string | null;
    candidate_value: string | null;
    explanation: string;
  }[];
  skills: { skill: string; status: "evidenced" | "not_found"; evidence: string | null }[];
  disclaimer: string;
};

export type CompanyResearch = {
  run_id: string;
  job_id: string;
  company_name: string;
  job_title: string | null;
  query: string;
  researched_at: string;
  is_stale: boolean;
  summary: string;
  findings: { claim: string; source_id: string; quote: string }[];
  sources: {
    source_id: string;
    title: string;
    url: string;
    excerpt: string;
    age: string | null;
  }[];
  no_evidence: boolean;
  warning: string | null;
};

export type CompanyArchive = {
  id: string;
  name: string;
  industry: string | null;
  website_url: string | null;
  recruitment_url: string | null;
  notes: string | null;
  batches: string[];
  jobs: {
    id: string;
    title: string | null;
    city: string | null;
    job_type: string | null;
    batch: string | null;
    deadline: string | null;
    application_status: string | null;
    source_url: string | null;
    source_captured_at: string;
    research_summary: string | null;
    research_is_stale: boolean | null;
    research_no_evidence: boolean | null;
    researched_at: string | null;
  }[];
  research_summary: string;
  research_count: number;
  finding_count: number;
  source_count: number;
  last_researched_at: string | null;
  stale_research_count: number;
  no_evidence: boolean;
  findings: {
    job_id: string;
    job_title: string | null;
    claim: string;
    quote: string;
    source_title: string;
    source_url: string;
    researched_at: string;
    is_stale: boolean;
  }[];
  sources: {
    research_run_id: string;
    job_id: string;
    job_title: string | null;
    source_id: string;
    title: string;
    url: string;
    excerpt: string;
    age: string | null;
    researched_at: string;
    is_stale: boolean;
  }[];
};

export type ReminderKind = "opening" | "deadline" | "assessment" | "interview" | "follow_up" | "other";
export type ReminderStatus = "scheduled" | "paused" | "notified" | "completed" | "cancelled" | "failed";

export type Reminder = {
  id: string;
  job_id: string | null;
  job_label: string | null;
  title: string;
  details: string | null;
  kind: ReminderKind;
  event_at: string;
  notify_at: string;
  timezone: string;
  lead_minutes: number;
  channel: "in_app";
  status: ReminderStatus;
  schedule_revision: number;
  delivery_attempts: number;
  last_delivery_error: string | null;
  created_at: string;
  updated_at: string;
};

export type ReminderNotification = {
  id: string;
  reminder_id: string;
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
};

export type ReminderCenter = {
  reminders: Reminder[];
  notifications: ReminderNotification[];
  unread_count: number;
};

export type ExtractedJobField = {
  value: string | string[] | null;
  confidence: number;
  evidence: string | null;
};

export type AgentTaskEvent = {
  id: number;
  event: "progress" | "completed" | "failed" | "confirmed" | "cancelled" | "telemetry";
  message: string;
  step?: string;
  code?: string;
  needs_review_count?: number;
  created_at: string;
  metrics?: {
    run_id: string;
    request_id: string | null;
    attempt: number;
    duration_ms: number;
    provider_call_count: number;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    total_tokens: number | null;
    token_usage_complete: boolean;
    estimated_cost_usd: number | null;
    cost_estimate_complete: boolean;
    calls: {
      provider: string;
      operation: string;
      model: string | null;
      duration_ms: number;
      outcome: string;
      prompt_tokens: number | null;
      completion_tokens: number | null;
      total_tokens: number | null;
      estimated_cost_usd: number | null;
    }[];
  };
};

export type AgentTask = {
  id: string;
  task_type: "job_extraction";
  status: "queued" | "running" | "cancelling" | "cancelled" | "succeeded" | "failed" | "confirmed";
  source_url: string | null;
  result: {
    fields: Record<string, ExtractedJobField>;
    needs_review_fields: string[];
  } | null;
  events: AgentTaskEvent[];
  error_code: string | null;
  error_message: string | null;
  model_name: string | null;
  attempt_count: number;
  job_id: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
};

export type AgentTaskPlan = {
  id: string;
  task_type: "task_plan";
  status:
    | "queued"
    | "running"
    | "awaiting_confirmation"
    | "needs_clarification"
    | "confirmed"
    | "cancelled"
    | "failed";
  preview: {
    title: string | null;
    details: string | null;
    kind: ReminderKind;
    event_at: string | null;
    timezone: string;
    job_id: string | null;
    job_label: string | null;
    clarification_question: string | null;
  } | null;
  reminder_id: string | null;
  events: { id: number; event: string; message: string; created_at: string }[];
  error_code: string | null;
  error_message: string | null;
  model_name: string | null;
  attempt_count: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
};

export type AgentWorkspaceCapability = {
  id: "reminder_plan" | "job_extraction" | "job_match" | "company_research" | "knowledge_qa" | "career_materials";
  title: string;
  description: string;
  action_label: string;
  href: string;
  action_level: "read_only" | "local_draft";
  confirmation_required: boolean;
};

export type AgentWorkspaceRun = {
  id: string;
  task_type: string;
  skill_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  job_id: string | null;
  job_label: string | null;
  duration_ms: number | null;
  total_tokens: number | null;
  estimated_cost_usd: number | null;
};

export type AgentWorkspace = {
  timezone: string;
  capabilities: AgentWorkspaceCapability[];
  recent_runs: AgentWorkspaceRun[];
};

export type JobSourceEvidence = {
  id: string;
  job_id: string;
  source_url: string | null;
  source_text: string;
  field_evidence: Record<string, ExtractedJobField>;
  captured_at: string;
};

export type SkillId =
  | "job_analysis"
  | "resume_targeting"
  | "application_answers"
  | "company_research"
  | "interview_prep"
  | "application_prep_pack";

export type SkillCatalogItem = {
  id: SkillId;
  version: string;
  name: string;
  description: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  boundaries: string[];
  example_input: Record<string, unknown>;
  example_output: Record<string, unknown>;
};

export type SkillCitation = {
  source_id: string;
  source_label: string;
  source_url: string | null;
  quote: string;
};

export type SkillDraft = {
  summary: string;
  checklist: { title: string; reason: string; needs_user_confirmation: boolean }[];
  sections: {
    title: string;
    content: string;
    citations: SkillCitation[];
    needs_user_input: boolean;
  }[];
  open_questions: string[];
  warnings: string[];
};

export type SkillRun = {
  id: string;
  skill_id: SkillId;
  skill_version: string;
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  result: SkillDraft | null;
  events: { id: number; event: string; message: string; created_at: string; step?: string }[];
  error_code: string | null;
  error_message: string | null;
  model_name: string | null;
  attempt_count: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
};

export type SkillApproval = {
  id: string;
  agent_run_id: string;
  job_id: string;
  action_type: string;
  summary: string;
  status: "pending" | "approved" | "rejected" | "expired" | "executed" | "invalidated";
  expires_at: string;
  approved_at: string | null;
  executed_at: string | null;
  created_at: string;
};

export type ApplicationPrepPack = {
  id: string;
  job_id: string;
  agent_run_id: string;
  skill_id: SkillId;
  skill_version: string;
  content: SkillDraft;
  created_at: string;
};

export type SkillAuditEvent = {
  id: string;
  approval_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  details: Record<string, unknown>;
  created_at: string;
};

export async function apiRequest<T = void>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (typeof options.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, {
      ...options,
      credentials: "include",
      headers,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError("无法连接后端服务，请确认服务已启动后重试。", null);
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      code?: unknown;
      detail?: unknown;
    } | null;
    const detail = body?.detail;
    const detailMessage = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => {
            if (typeof item === "object" && item !== null && "msg" in item) {
              return String(item.msg);
            }
            return "输入内容无效";
          }).join("；")
        : typeof detail === "object" && detail !== null && "message" in detail
          ? String(detail.message)
          : null;
    const hasMigrationHint = response.status === 503
      && body?.code === "database_schema_outdated"
      && detailMessage;
    const providerCode = typeof detail === "object" && detail !== null && "code" in detail
      ? String(detail.code)
      : "";
    const safeProviderFailure = response.status === 503
      && (
        providerCode.startsWith("embedding_")
        || providerCode.startsWith("answer_")
        || providerCode.startsWith("research_")
      || providerCode.startsWith("skill_")
      );
    const message = response.status >= 500 && !hasMigrationHint && !safeProviderFailure
      ? `后端返回 HTTP ${response.status}，请检查 API 服务日志。`
      : detailMessage ?? `请求失败（HTTP ${response.status}）。`;
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
