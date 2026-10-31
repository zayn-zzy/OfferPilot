export type User = {
  id: string;
  email: string;
  created_at: string;
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number | null) {
    super(message);
    this.name = "ApiError";
  }
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
  source_type: "manual" | "paste" | "link";
  source_captured_at: string;
  tags: string[];
  review_status: "needs_review" | "verified";
  created_at: string;
  updated_at: string;
  application: Application | null;
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
    const message = response.status >= 500 && !hasMigrationHint
      ? `后端返回 HTTP ${response.status}，请检查 API 服务日志。`
      : detailMessage ?? `请求失败（HTTP ${response.status}）。`;
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
