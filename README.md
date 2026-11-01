# OfferPilot

面向秋招求职流程的 Agent 工作台。当前已实现账户认证、个人档案、简历版本管理、岗位管理、Agent 岗位抽取、个人资料 RAG 问答和透明的岗位匹配分析，后续按 [PRD](秋招求职%20Agent%20产品需求文档.md) 分模块推进。

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

简历支持 PDF、DOCX 上传和文本粘贴，单文件最大 10 MB。上传文件保存在私有目录，数据库保存元信息和提取出的文本；解析结果默认待确认，只有用户确认后才能供后续匹配使用。

在岗位管理页可下载 CSV 模板，填写后上传并预览逐行校验结果；可选择校验通过的行批量导入。支持 UTF-8/GB18030 编码，最多 500 条岗位、5 MB；已有或同一文件内重复的来源链接会标记为重复，导入后的岗位可在列表编辑。

岗位页默认展示一个列表，新增岗位和 CSV 导入按需展开。点击某张岗位卡片的“编辑”，会在该卡片内展开表单，保存或取消后收起；投递阶段、简历版本、备注、下一步与历史也在同一张卡片维护。手动录入的岗位不再显示“待核验/已核验”标签或核验按钮，信息不足时直接编辑补充。

岗位列表默认按最新保存时间排序。新建、CSV 导入或 AI 提取确认成功后，会清空筛选、直接显示保存接口返回的岗位并定位到卡片；成功提示提供“查看岗位”链接。重新打开已保存的 AI 任务时，可点击“查看已保存岗位”回到对应卡片。

### Agent 岗位信息提取

岗位页的“AI 提取岗位”接收用户粘贴的招聘原文（20–30,000 字符）和可选来源链接，不会自动访问网站。原文会发送到你配置的模型服务商处理，请先确认服务商符合你的隐私要求。后端通过 OpenAI 兼容的 Chat Completions 接口提取公司、职位、城市、类型、批次、截止日期、学历和技能；每个字段附置信度和原文引用。服务端会核对引用是否逐字出现在用户文本中，不成立的字段将置信度降为 0。用户逐项检查/修改后确认，岗位和原文来源依据才会保存；低置信度、缺失值或无引用的字段会标记为“需要确认”。

复制 `.env.example` 到仓库根目录 `.env` 并配置 `OFFERPILOT_LLM_BASE_URL`、`OFFERPILOT_LLM_API_KEY` 与 `OFFERPILOT_LLM_MODEL`，Compose API 会读取这些变量。直接本地启动 API 时，把相同变量放在 `backend/.env`。支持以 `/v1` 结尾的 API 根地址，或直接提供 `/v1/chat/completions` 地址。密钥只在 API 进程内读取，不通过设置接口或任务响应返回。未配置时任务会显示明确失败原因，配置完成后可重试。

提取任务会将状态、进度事件、尝试次数、模型名和安全错误摘要保存在数据库中；前端通过 SSE 读取实时进度，也会从任务 API 恢复状态。失败任务最多尝试 3 次；进程重启导致的排队/运行中任务会转为失败并可重试。当前阶段使用 FastAPI 进程内后台任务；第 6 步引入 Celery/Redis 后再将执行迁移到持久化队列。这个抽取过程没有浏览器抓取工具，也不执行外部写操作。

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

项目也通过官方 MCP Python SDK 暴露只读 `search_company_recruitment` 工具。MCP 客户端可在后端目录启动本地 stdio 服务：

```bash
cd backend
uv sync --extra dev
uv run offerpilot-research-mcp
```

该工具仅接受搜索词和最多 10 条的结果数，不提供 URL 抓取、岗位写入或其他外部动作。SDK v2 要求 Python 3.11+；Docker API 使用 Python 3.12，本地 `uv` 环境需使用 Python 3.11 或更新版本。参见 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)。

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
- `GET/PUT /api/v1/profile`：读取或保存当前用户的求职档案。
- `GET /api/v1/resumes`、`POST /api/v1/resumes/upload`、`POST /api/v1/resumes/text`：列出、上传或粘贴简历版本。
- `GET /api/v1/resumes/{id}`、`POST /api/v1/resumes/{id}/confirm`、`DELETE /api/v1/resumes/{id}`：预览、确认或删除当前用户的简历版本。
- `GET/POST /api/v1/jobs`、`GET/PUT/DELETE /api/v1/jobs/{id}`：筛选、录入、更新或删除岗位；岗位来源链接按用户去重。
- `GET /api/v1/jobs/import/template`、`POST /api/v1/jobs/import/preview`、`POST /api/v1/jobs/import`：下载岗位 CSV 模板、预览校验并原子批量保存选中的岗位。
- `POST/PUT/DELETE /api/v1/jobs/{id}/application`：创建、更新或清除岗位卡片中的投递记录。
- `GET /api/v1/jobs/{id}/application/history`：查看用户确认的阶段变更记录。
- `POST /api/v1/agent/job-extractions`：创建岗位原文抽取任务；`GET /api/v1/agent/tasks`、`GET /api/v1/agent/tasks/{id}` 查询当前用户的任务。
- `GET /api/v1/agent/tasks/{id}/events`：SSE 进度流；`POST /api/v1/agent/tasks/{id}/retry` 重试失败任务；`GET /api/v1/agent/tasks/{id}/source` 读取待确认原文。
- `DELETE /api/v1/agent/tasks/{id}`：删除未确认的失败/成功任务及其暂存原文；已确认任务需删除关联岗位。
- `GET /api/v1/jobs/{id}/match`：根据当前档案、最新已确认简历和岗位信息返回透明的条件/技能比对，不保存派生分数。
- `GET/POST /api/v1/knowledge/notes`、`PUT/DELETE /api/v1/knowledge/notes/{id}`：管理当前用户的求职笔记。
- `POST /api/v1/knowledge/reindex`：重建当前用户已确认简历与笔记的向量索引。
- `POST /api/v1/knowledge/ask`：从当前用户已索引的资料中检索片段并返回带原文引用的回答。
- `POST /api/v1/agent/tasks/{id}/confirm`：应用用户核对后的字段并保存岗位；`GET /api/v1/agent/jobs/{job_id}/evidence` 查看来源原文和字段引用。
