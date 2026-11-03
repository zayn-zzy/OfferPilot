# OfferPilot

面向秋招求职流程的 Agent 工作台。当前已实现账户认证、个人档案、简历版本管理、岗位管理、Agent 岗位抽取、个人资料 RAG 问答、透明岗位匹配、MCP 公司研究、提醒中心，以及版本化求职 Skills 与审批保存流程；后续按 [PRD](秋招求职%20Agent%20产品需求文档.md) 分模块推进。

## 技术栈

- 前端：Next.js App Router、React、TypeScript
- 后端：FastAPI、Pydantic、SQLAlchemy、Alembic
- 数据：Compose 使用带 pgvector 扩展的 PostgreSQL 17 和 Redis 7；简历文件使用私有本地存储卷
- 本地开发：Docker Compose；前端依赖使用 Bun

## 启动

使用 Docker Compose 时，复制 `.env.example` 为 `.env`，将 `POSTGRES_PASSWORD` 和 `OFFERPILOT_SECRET_KEY` 改成自己的值，然后从本目录运行：

```bash
docker compose up --build
```

- Web：<http://localhost:3000>
- API：<http://localhost:8000>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>
- 岗位管理：<http://localhost:3000/jobs>

Compose 会启动 PostgreSQL 17（含 pgvector）、Redis 7、API 和 Web；PostgreSQL 数据及简历原文件分别保存在命名卷中，首次启动会运行 Alembic 迁移。浏览器通过 Web 同源的 `/api` 路径访问后端，再由 Next.js 服务转发到 API 容器，因此不依赖浏览器能否直接访问后端端口。账户密码使用 Argon2id 哈希；登录状态通过 HttpOnly Cookie 维护。开发环境未设置密钥时使用临时随机密钥，重启后现有会话会失效；部署环境必须设置 `OFFERPILOT_SECRET_KEY`。

没有 Docker 时，也可以直接启动 API 和 Web。API 默认使用 `backend/offerpilot.db` SQLite 数据库，并将上传文件写入 `backend/storage/`；无需安装 PostgreSQL 或 Redis。Next.js 默认将 `/api` 转发到 `http://127.0.0.1:8000`；若 API 位于其他地址，启动 Web 前设置服务端环境变量 `OFFERPILOT_API_URL`。若要改用本机 PostgreSQL，可设置 `OFFERPILOT_DATABASE_URL` 后再运行迁移。当前岗位管理也不依赖 Redis。

```bash
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

另开终端启动前端：

```bash
cd frontend
bun install
bun run dev
```

如果这些命令运行在远程服务器上，电脑浏览器中的 `localhost` 指的是电脑本身。需要先把电脑的 3000 端口转发到服务器。在**自己电脑的终端**中执行下面的命令，把 `user@server` 换成平时连接服务器时使用的 SSH 用户和地址（也可以使用 SSH 配置中的连接名），并保持该终端运行：

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:3000:127.0.0.1:3000 user@server
```

然后打开 <http://localhost:3000/>。`ExitOnForwardFailure=yes` 会在本机端口已被占用等情况下明确报错，避免误以为转发已经建立。使用 VS Code Remote-SSH 时，也可以在“端口 / Ports”面板添加服务器端口 `3000`，核对本地端口后点击“在浏览器中打开”。API 由 Next.js 的 `/api` 代理访问，正常使用网页只需转发 3000。

简历支持 PDF、DOCX 上传和文本粘贴，单文件最大 10 MB。上传文件保存在私有目录，数据库保存元信息和提取出的文本；解析结果默认待确认，只有用户确认后才能供后续匹配使用。

在岗位管理页可下载 CSV 模板，填写后上传并预览逐行校验结果；可选择校验通过的行批量导入。支持 UTF-8/GB18030 编码，最多 500 条岗位、5 MB。已有来源链接重复时，可选择把新增/CSV 信息合并到已有岗位；同一文件内重复的行可合并到首条预览行。合并会保留目标岗位已有的非空字段，只补空字段，并合并去重技能和标签；目标岗位 ID、投递记录与阶段历史不变。冲突字段保留目标值，用户可随后在岗位卡片编辑。

岗位页默认展示一个列表，新增岗位和 CSV 导入按需展开。点击某张岗位卡片的“编辑”，会在该卡片内展开表单，保存或取消后收起；投递阶段、简历版本、备注、下一步与历史也在同一张卡片维护。手动录入的岗位不再显示“待核验/已核验”标签或核验按钮，信息不足时直接编辑补充。

岗位列表默认按最新保存时间排序。新建、CSV 导入或 AI 提取确认成功后，会清空筛选、直接显示保存接口返回的岗位并定位到卡片；成功提示提供“查看岗位”链接。重新打开已保存的 AI 任务时，可点击“查看已保存岗位”回到对应卡片。

### Agent 岗位信息提取

岗位页的“AI 提取岗位”接收用户粘贴的招聘原文（20–30,000 字符）和可选来源链接，不会自动访问网站。原文会发送到你配置的模型服务商处理，请先确认服务商符合你的隐私要求。后端通过 OpenAI 兼容的 Chat Completions 接口提取公司、职位、城市、类型、批次、截止日期、学历和技能；每个字段附置信度和原文引用。服务端会核对引用是否逐字出现在用户文本中，不成立的字段将置信度降为 0。用户逐项检查/修改后确认，岗位和原文来源依据才会保存；低置信度、缺失值或无引用的字段会标记为“需要确认”。

复制 `.env.example` 到仓库根目录 `.env` 并配置 `OFFERPILOT_LLM_BASE_URL`、`OFFERPILOT_LLM_API_KEY` 与 `OFFERPILOT_LLM_MODEL`，Compose API 会读取这些变量。直接本地启动 API 时，把相同变量放在 `backend/.env`。支持以 `/v1` 结尾的 API 根地址，或直接提供 `/v1/chat/completions` 地址。密钥只在 API 进程内读取，不通过设置接口或任务响应返回。未配置时任务会显示明确失败原因，配置完成后可重试。

提取任务会将状态、进度事件、尝试次数、模型名和安全错误摘要保存在数据库中；前端通过 SSE 读取实时进度，也会从任务 API 恢复状态。排队任务可立即取消；运行中的任务会等待当前模型请求返回后丢弃结果并完成取消。失败任务最多尝试 3 次；进程重启导致的排队/运行中任务会转为失败并可重试，正在取消的任务会转为已取消。当前阶段使用 FastAPI 进程内后台任务；第 6 步引入 Celery/Redis 后再将执行迁移到持久化队列。这个抽取过程没有浏览器抓取工具，也不执行外部写操作。

岗位提取、提醒计划和求职 Skills 这三类后台工作流共用每账户最多 3 个活动任务和每任务最多 3 次尝试的限制。创建支持幂等键；重复提交同一键与同一内容会返回原任务，复用键提交不同内容会返回冲突。三类任务的取消语义一致：排队时立即取消，运行中先显示“取消中”，等待当前模型请求返回后丢弃草稿并收敛为“已取消”。

### 第 4 步：个人资料 RAG 与岗位匹配

在“岗位管理”卡片中点击“匹配分析”，系统将岗位学历要求与个人档案学历比较，将岗位城市/职位/行业与已保存偏好比较，并检查岗位要求技能是否在最新一份已确认简历或技能档案中出现。每项显示“符合 / 不符合 / 待确认”；“未找到”只表示资料中没有写出，不代表用户不具备。此规则分析不生成录用概率。

“资料问答”页允许添加项目/求职笔记，并检索已确认的简历与笔记回答问题。点击“建立 / 更新索引”后，资料按 900 字符片段（有重叠）切分并生成向量；问题检索当前账户的相似片段，模型只能依据这些片段作答。系统只保留模型引用中确实出现在检索片段里的原文；没有支持性引用时返回无证据结果。简历删除、笔记编辑/删除会同步删除相关索引片段；新资料需重新建立索引。

向量生成使用独立的 OpenAI 兼容 Embeddings API，使用服务返回的原生维度；问答复用已配置的 Chat Completions API。两项服务可以使用不同的供应商和模型。需要在仓库根 `.env`（Compose）或 `backend/.env`（本地 API）设置：

```dotenv
OFFERPILOT_EMBEDDING_BASE_URL=https://your-provider.example/v1
OFFERPILOT_EMBEDDING_API_KEY=your-embedding-key
OFFERPILOT_EMBEDDING_MODEL=your-embedding-model
```

向量接口必须兼容 `POST /embeddings`，同一模型需稳定返回相同维度。SQLite 将向量保存在 JSON 列并在应用中计算余弦相似度；Compose PostgreSQL 使用无固定维度的 pgvector 列执行账户范围内的精确余弦检索。模型或维度变更后需重新建立索引。升级数据库后才可使用新增接口。已有简历不需要重新上传，但须先确认，然后进入 `/knowledge` 建立索引。

### 公司公开信息研究与 MCP 搜索工具

岗位卡片中的“公司研究”通过 Tavily Search API 查找公开网页，并让配置的 Chat Completions 模型按字段生成摘要。每个研究结论都要引用搜索结果片段，后端会检查来源 ID 和引用原文；搜索结果、查询词、模型名和执行状态会留在当前用户对应的 Agent 任务记录中。点击来源链接可以打开原网页核验。相同岗位 30 分钟内复用搜索结果，每个账户每小时最多发起 10 次新研究；结果超过 7 天会标记为可能过期。搜索失败会显示明确错误，不会伪装成“没有结果”。MVP 不会自动抓取链接指向的页面，也不访问登录后内容。

在仓库根 `.env`（Compose）或 `backend/.env`（本地 API）配置 `OFFERPILOT_TAVILY_API_KEY`。密钥仅由后端读取，不要提交 `.env` 或把 Key 放到前端；没有密钥时公司研究会提示配置问题，其他模块仍可使用。公开搜索片段会发送给已配置的 Chat Completions 服务生成摘要。Tavily 使用 Bearer Token 认证，搜索请求发送至 `https://api.tavily.com/search`；参见 [Tavily Search API 说明](https://help.tavily.com/articles/4840311948-tavily-search-api)。

### 提醒中心与后台任务

提醒中心支持开放日、截止时间、测评、面试、跟进和自定义提醒。创建时可选关联岗位、事件时区和提前时间；MVP 只提供站内通知。通知计划由数据库中的提醒记录决定，Celery Beat 每分钟触发一次扫描，Celery Worker 将到期提醒原子地变成通知记录。数据库幂等键以“提醒 ID + 排期版本”唯一约束防止重复通知；延期会更新触发时间并增加排期版本，完成/取消后不再投递。数据库错误会由 Celery 指数退避重试，最多 5 次。

Docker Compose 会启动 Redis、Worker 和 Beat。无 Docker 本地运行需自行启动 Redis，再从 `backend` 目录分别运行 `uv run celery -A app.celery_app:celery_app worker --loglevel=INFO` 和 `uv run celery -A app.celery_app:celery_app beat --loglevel=INFO --schedule=/tmp/offerpilot-celerybeat-schedule`；仅启动 FastAPI 不会触发定时通知。使用 `OFFERPILOT_CELERY_BROKER_URL` 指定 Redis Broker。

项目也通过官方 MCP Python SDK 暴露只读 `search_company_recruitment` 工具。MCP 客户端可在后端目录启动本地 stdio 服务：

```bash
cd backend
uv sync --extra dev
uv run offerpilot-research-mcp
```

该工具仅接受搜索词和最多 10 条的结果数，不提供 URL 抓取、岗位写入或其他外部动作。SDK v2 要求 Python 3.11+；Docker API 使用 Python 3.12，本地 `uv` 环境需使用 Python 3.11 或更新版本。参见 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)。

### 求职 Skills、申请准备包与审批

`/skills` 提供岗位分析、简历针对性建议、申请问答草稿、公司调研整理、面试准备和申请准备包六个版本化模板。每次运行会记录 Skill ID/版本、状态、步骤、模型及失败原因；任务最多尝试 3 次，可取消，失败可重试。申请问答草稿必须由用户提供真实问题。公司调研 Skill 复用该岗位已保存的 Tavily 研究来源，不会在此处重新搜索。

简历相关 Skills 会读取最新一份已确认简历；岗位描述、个人档案、简历和研究片段会发送到当前配置的 Chat Completions 服务。系统把这些资料作为不可信输入，不执行其中的指令；模型引用必须逐字出现在对应资料中，否则移除引用并标记需要人工核对。没有证据支持的个人经历必须留作待补充项。

申请准备包可以先预览。用户请求保存后会生成有效期 30 分钟的审批；“批准”和“执行”是两个独立 API 阶段。执行前服务端会重新计算准备包内容与目标岗位的哈希；发生变化或审批过期时拒绝执行。MVP 的 allowlist 只有“保存准备包到 OfferPilot 本地工作台”，所有审批和保存均记录在审计列表；不登录招聘网站、不自动投递、不发送邮件或同步外部日历。API / 页面首次启用前需要运行数据库迁移：

```bash
cd backend
uv run alembic upgrade head
```

岗位提取、岗位匹配、提醒计划、公司研究、个人资料问答和 Skills 的持久化任务由 `app.services.agent_workflow` 的统一 LangGraph 路由分发；路由会核对 `AgentRun` 的任务类型与状态。岗位匹配复用确定性规则，对硬性条件、偏好和简历原文证据逐项比较，不调用模型，也不生成录用概率；公司研究在执行前再次校验岗位和公司归属，继续通过 MCP 调用只读搜索并保留可核验引用；个人资料问答按账户检索已索引的简历和笔记，并校验返回引用确实来自检索片段；Skills 审批恢复还会校验审批记录、运行记录、账户和决定是否一致。路由图状态只放任务 ID、任务类型、操作类型和审批 ID/决定，不放原文或模型草稿正文。各专属流程仍负责自身的处理步骤和业务写入；例如 Skill 由 API 进程内后台任务触发，并由内部 `StateGraph` 编排“上下文校验 → 草稿生成 → 引用校验 → 人工审批 → 本地保存”。`AgentRun` 保存面向产品的状态、步骤、结果和错误；LangGraph checkpointer 保存暂停/恢复所需的图状态。PostgreSQL 使用 LangGraph PostgreSQL checkpointer；SQLite 本地模式将检查点放在 `storage/langgraph-checkpoints.sqlite3`，与业务库分开。图调用使用 LangGraph v2 异步结果格式；Skill 适配层会保留现有审批中断返回结构。

`application_prep_pack` 在人工审批节点暂停；用户批准后，执行 API 使用同一 `thread_id` 恢复图，再次校验审批有效期、岗位归属和草稿哈希后才保存。API 重启时，尚未完成的 `queued/running` 任务会标记失败并允许手动重试；审批暂停状态和检查点可留存以供恢复。FastAPI `BackgroundTasks` 仍不是持久任务队列，提醒投递仍由独立 Celery Worker/Beat 负责。

统一 Agent 路由会在每次执行后将请求 ID、总耗时、外部模型/搜索调用耗时、服务返回的 token 用量和费用估算写入 `AgentRun` 事件；API 响应也包含 `X-Request-ID`，Agent 工作区汇总显示可确认的耗时、token 和费用。统计只记录 Provider、模型、操作、状态与计量值，不保存 HTTP 请求/响应正文。要估算费用，需按当前服务商价格配置 `OFFERPILOT_LLM_INPUT_USD_PER_MILLION_TOKENS`、`OFFERPILOT_LLM_OUTPUT_USD_PER_MILLION_TOKENS`、`OFFERPILOT_EMBEDDING_INPUT_USD_PER_MILLION_TOKENS` 和 `OFFERPILOT_TAVILY_USD_PER_SEARCH`；未配置费率或服务未返回 token 用量时会显示估算不完整，不会把未知成本显示为零。

### 公司档案

登录后访问 `/companies` 可按公司查看已保存岗位、招聘批次、个人公司备注和每个岗位最新一次成功的公开研究。研究结论保留引用片段与来源链接；超过 7 天的结果会标出可能过期，缺少支持证据时会说明。可在公司档案中对具体岗位发起或刷新研究；搜索服务沿用 `OFFERPILOT_TAVILY_API_KEY`，摘要沿用现有 Chat Completions 配置。该页面读取按账户隔离的公司、岗位和 `AgentRun` 研究记录，不新增数据库表；公司备注是个人记录，公开结论仍需通过来源链接核验。

### Agent 评测烟雾集

`backend/evals/` 提供 50 条岗位抽取和 30 条 RAG/公司研究合成样本，覆盖缺失字段、冲突来源、旧资料、无答案，以及 4 条不可信指令文本安全探针。样本明确标记为 `synthetic_smoke_v1`，只用于验证评测代码和发现回归，不是 PRD 要求的人工标注验收集，也不能用来宣称模型达到验收门槛。当前 Provider Adapter 不暴露 token 用量，报告中的 token 与费用保持空值。

不调用模型的本地数据检查：

```bash
cd backend
uv run python -m app.evals.runner --task job_extraction
uv run python -m app.evals.runner --task rag_company_research
```

明确添加 `--live` 才会调用配置的服务商；这可能产生 API 用量和费用。结果默认写入被 Git 忽略的 `backend/artifacts/agent-eval/`：

```bash
cd backend
uv run python -m app.evals.runner --task job_extraction --live --limit 3
uv run python -m app.evals.runner --task rag_company_research --live --limit 3
```

评测设计、指标含义和当前限制见 [backend/evals/README.md](backend/evals/README.md)。

## 后端开发与测试

```bash
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
uv run pytest
```

测试使用隔离的 SQLite 内存数据库及临时文件数据库，不需要启动 PostgreSQL。直接本地启动时默认使用 SQLite；Compose 会通过环境变量连接 Compose 网络内的 PostgreSQL。

本地开发服务器的 `--reload` 只会重载 Python 代码，不会升级数据库。每次更新包含数据库迁移的代码后，需在 `backend/` 目录执行 `uv run alembic upgrade head`，再刷新页面。若尚未迁移，相关接口会返回明确的数据库升级提示（HTTP 503）。Compose 每次启动 API 时都会先运行迁移。

## 前端开发与检查

```bash
cd frontend
bun install
bun run dev
bun run typecheck
bun run build
```

真实服务浏览器回归需先启动本地 API 与 Web，并让 API 使用与 `backend/.env` 相同的数据库。在仓库根目录运行：

```bash
uv run --with playwright==1.58.0 playwright install chromium
uv run scripts/check_agent_job_visibility.py
```

脚本创建独立临时账号和 12 条合成岗位，预置一条成功的提取任务，再通过真实页面/API 验证确认保存、首张卡片可见、刷新保留、旧响应不覆盖新列表及已保存任务定位。提取阶段不调用模型；结束后只清理该临时账号的数据。

## 当前 API

- `GET /health`：API 与数据库连通性。
- `POST /api/v1/auth/register`：注册并建立会话。
- `POST /api/v1/auth/login`：登录。
- `POST /api/v1/auth/logout`：退出并清理会话。
- `GET /api/v1/auth/me`：获取当前账户。
- `GET /api/v1/dashboard`：按当前账户汇总投递阶段、未来 7 天提醒/跟进、未来 14 天岗位截止日期和最近 5 条 Agent 运行记录。
- `GET /api/v1/agent/workspace`：返回受支持的 Agent 任务类型、对应入口和最近的岗位提取/岗位匹配/公司研究/个人资料问答/Skills 等运行摘要；不返回任务原文或模型结果。
- `PUT /api/v1/auth/me/timezone`：更新账户 IANA 时区；必须显式确认重新计算所有未来提醒。
- `GET /api/v1/account/export`：下载当前账户的 ZIP 数据包，包含账户资料、业务记录、解析后的简历文本和服务器仍保存的简历原件；不包含密码哈希、服务 API 密钥或派生向量数值。
- `DELETE /api/v1/account/me`：永久删除当前账户及其业务记录、向量索引和账户文件；需要再次提交当前密码和账户邮箱。
- `GET/PUT /api/v1/profile`：读取或保存当前用户的求职档案。
- `GET /api/v1/resumes`、`POST /api/v1/resumes/upload`、`POST /api/v1/resumes/text`：列出、上传或粘贴简历版本。
- `GET /api/v1/resumes/{id}`、`POST /api/v1/resumes/{id}/confirm`、`DELETE /api/v1/resumes/{id}`：预览、确认或删除当前用户的简历版本。
- `GET/POST /api/v1/jobs`、`GET/PUT/DELETE /api/v1/jobs/{id}`：筛选、录入、更新或删除岗位；岗位来源链接按用户去重。
- `GET /api/v1/jobs/import/template`、`POST /api/v1/jobs/import/preview`、`POST /api/v1/jobs/import`：下载岗位 CSV 模板、预览校验并原子批量保存选中的岗位。
- `POST /api/v1/jobs/{id}/merge`：把来源链接相同的岗位字段补充到当前用户已有岗位；不会覆盖其非空字段或投递记录。
- `POST/PUT/DELETE /api/v1/jobs/{id}/application`：创建、更新或清除岗位卡片中的投递记录。
- `GET /api/v1/jobs/{id}/application/history`：查看用户确认的阶段变更记录。
- `POST /api/v1/agent/job-extractions`：创建岗位原文抽取任务；`GET /api/v1/agent/tasks`、`GET /api/v1/agent/tasks/{id}` 查询当前用户的任务。
- `GET /api/v1/agent/tasks/{id}/events`：SSE 进度流；`POST /api/v1/agent/tasks/{id}/retry` 重试失败任务，`POST /api/v1/agent/tasks/{id}/cancel` 取消排队或运行中的提取任务；`GET /api/v1/agent/tasks/{id}/source` 读取待确认原文。
- `DELETE /api/v1/agent/tasks/{id}`：删除未确认的失败/成功/已取消任务及其暂存原文；排队、运行或取消中的任务不可删除；已确认任务需删除关联岗位。
- `GET /api/v1/jobs/{id}/match`：只读地根据当前档案、最新已确认简历和岗位信息返回透明的条件/技能比对。
- `POST /api/v1/jobs/{id}/match`：经统一 Agent 路由运行同一规则匹配，将状态、证据结果和失败原因保存到当前用户的运行记录；匹配仍不调用模型或计算录用概率。
- `GET/POST /api/v1/knowledge/notes`、`PUT/DELETE /api/v1/knowledge/notes/{id}`：管理当前用户的求职笔记。
- `POST /api/v1/knowledge/reindex`：重建当前用户已确认简历与笔记的向量索引。
- `POST /api/v1/knowledge/ask`：从当前用户已索引的资料中检索片段并返回带原文引用的回答。
- `GET/POST /api/v1/reminders`：读取提醒中心或创建岗位开放、截止、测评、面试及跟进提醒；创建请求支持幂等键。
- `POST /api/v1/reminders/{id}/complete`、`/cancel`、`/pause`、`/resume`、`/snooze`、`/retry`：完成、取消、暂停/恢复、延期或重试提醒。
- `POST /api/v1/notifications/{id}/read`：将当前用户的站内通知标为已读。
- `POST /api/v1/agent/tasks/{id}/confirm`：应用用户核对后的字段并保存岗位；如来源重复，可在确认请求中提供 `merge_into_job_id`，将字段和原文引用并入已有岗位。`GET /api/v1/agent/jobs/{job_id}/evidence` 查看来源原文和字段引用。
