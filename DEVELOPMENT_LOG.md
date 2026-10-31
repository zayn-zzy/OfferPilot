# OfferPilot 开发记录

本文记录每次已完成并提交的模块、技术选择和验证结果。项目需求以 [PRD](秋招求职%20Agent%20产品需求文档.md) 为准，按阶段逐步实现。

## 第 1 次实现：工程基础与账户认证

### 完成内容

- 建立 `frontend/` 与 `backend/` 结构，并添加环境变量模板、`.gitignore`、README 和 Docker Compose 开发环境。
- 创建 Next.js/React/TypeScript 首页、注册页、登录页和账户工作区页面。
- 创建 FastAPI API：健康检查、注册、登录、退出和当前账户接口。
- 添加 PostgreSQL 数据模型及 Alembic 初始迁移；Compose 同时启动 PostgreSQL 和 Redis，为后续任务队列做准备。
- 使用 Argon2id 哈希密码、短期签名会话和 HttpOnly/SameSite Cookie；后端校验浏览器请求来源，不向前端暴露密码哈希或会话令牌。
- 为后续用户数据隔离预留 UUID 用户主键。

### 技术

Next.js App Router、TypeScript、FastAPI、Pydantic Settings、SQLAlchemy、Alembic、PostgreSQL、Redis、Bun、Docker Compose。

### 与上一版本相比

上一版本只有 PRD；本次新增了可以继续扩展的前后端代码、账户认证、数据库迁移、容器编排和最小可运行界面。尚未实现岗位资料、投递看板、RAG、MCP、Agent 工作流或提醒功能，这些保持在 PRD 后续阶段。

### 验证

- 后端 `uv run pytest -vv`：7 项通过（认证、Cookie、Origin 校验、健康检查）。
- `alembic upgrade head`：在 SQLite 验证库迁移成功；PostgreSQL 容器运行验证因本机没有 Docker 未执行。
- `bun run typecheck`：通过。
- `bun run build`：通过，静态生成首页、登录、注册和账户工作区页面。
- `compose.yaml`：YAML 结构解析通过；Docker Compose 服务启动未执行（本机未安装 Docker）。

## 第 2 次实现：个人档案与简历版本管理

### 完成内容

- 实现当前用户的求职档案读取与保存：毕业年份、学历、专业、目标岗位、城市、行业和技能；输入会去除首尾空白、空项和不区分大小写的重复值。
- 实现 PDF、DOCX 上传及简历文本粘贴；解析文本进入预览状态，不会自动视为已确认材料。用户可以确认、查看版本列表或删除版本。
- 增加文件大小、扩展名和文档内容校验；原文件以随机生成的路径保存在用户隔离目录，目录权限为 `0700`、文件权限为 `0600`。接口按当前用户过滤记录，不能读取其他用户的档案或简历。
- 新增档案与简历数据模型和 Alembic 迁移；Compose 增加持久化的 `resume_storage` 卷。更新工作台入口、档案/简历管理页面、API 客户端的 multipart 上传处理和 README。

### 技术

FastAPI、Pydantic、SQLAlchemy、Alembic、SQLite/PostgreSQL JSON 字段、pypdf、python-docx、Next.js App Router、React、TypeScript、Docker Compose named volume。

### 与上一版本相比

上一版本完成工程骨架和账户认证；本次增加与账户关联的候选人档案和简历版本管理，前端提供导入、预览、确认与删除流程。尚未实现岗位管理、投递看板、RAG、Agent、MCP 或提醒任务，继续按 PRD 后续阶段实现。

### 验证

- 后端 `uv run pytest -vv`：13 项通过，覆盖档案隔离与校验、PDF/DOCX/文本导入、预览确认、删除、文件权限和上传限制。
- `uv run alembic upgrade head`：全新 SQLite 数据库成功执行两条迁移。
- `python3 -m compileall -q app migrations tests`：通过。
- `bun run typecheck`：通过。
- `bun run build`：通过，静态生成首页、登录、注册、工作台和个人档案页面。
- PostgreSQL/Redis Compose 实际启动未验证（本机没有 Docker）。

## 第 2 模块联调修复：API 同源代理

### 问题与修复

- 浏览器原先直接请求 `http://localhost:8000`。在端口转发、容器或远程开发环境里，这个地址可能指向浏览器所在机器，导致 `Failed to fetch`，表单也无法保存。
- 前端现改为请求同源 `/api/...`，Next.js 服务端再按 `OFFERPILOT_API_URL` 转发到后端；Compose 默认使用容器网络地址 `http://api:8000`，本地直跑默认使用 `http://127.0.0.1:8000`。
- API 错误现在保留 HTTP 状态码；档案页只在后端明确返回 401 时显示登录入口，网络连接失败会给出服务连接提示。GET 请求也不再额外添加 JSON Content-Type，避免无谓预检。

### 验证

- 同源 `/api/v1/profile` 代理返回后端的 401 JSON（未登录时），证明请求已到达 API，而不是浏览器网络层失败。
- 使用临时 SQLite 数据库和独立 Web/API 实例，经 Next.js 代理走通注册与 Cookie、档案保存/读取、文本与 DOCX 简历导入、确认、列表、删除和退出流程。
- 后端 `uv run pytest -q`：13 项通过；前端 `bun run typecheck` 和临时副本中的 `bun run build` 均通过。

## 第 2 模块故障修复：数据库迁移与页面反馈

- 查明本地 `backend/offerpilot.db` 仍处于迁移 `20261030_0001`，缺少档案和简历表；旧健康检查只执行 `SELECT 1`，因此数据库连通却无法使用新接口。
- 已对该 SQLite 数据库执行 `20261030_0002`，迁移只新增档案/简历表和索引，保留原账户数据。健康检查现会核对 ORM 所需表，缺表时返回明确的迁移命令，而不再报告健康。
- 首页求职计划卡片现明确标记为静态演示数据，不属于用户账户；简历文本保存和文件上传增加处理中状态，5xx 错误显示 HTTP 状态码。

### 验证

- 本地数据库 `alembic current`：`20261030_0002 (head)`；API `/health` 返回 200，未登录档案请求返回明确的 401。
- 后端 `uv run pytest -q`：14 项通过，新增“业务表缺失时健康检查返回迁移提示”的测试。
- 前端 `bun run typecheck` 与临时副本中的 `bun run build`：通过；通过当前 Web 服务确认首页含“演示数据”及其来源说明。

## 第 3 次实现：岗位管理与投递看板

### 完成内容

- 实现岗位手动录入、详情、编辑和删除；可保存公司、职位、城市、岗位类型、招聘批次、截止日期、学历要求、技能、备注、标签、招聘主页、来源链接和原始岗位描述。信息不完整的记录允许先保存并标记为待核验。
- 新增按用户隔离的公司档案；同一用户重复录入公司时复用公司信息。岗位来源链接会标准化并按用户去重，重复时返回可读提示，不会静默合并。
- 实现结构化岗位筛选：公司/职位/城市/行业关键词、城市、投递阶段、截止日期和标签；筛选不调用 LLM。
- 实现投递看板及完整阶段：待了解、感兴趣、准备中、已投递、测评中、面试中、Offer、已接受、已拒绝、已撤回、已关闭。可记录申请日期、关联简历版本、联系人/进展备注、下一步和日期。
- 每次加入看板和阶段变化都追加历史记录；只有当前用户能读取和修改自己的岗位、公司、申请及关联简历版本。
- 新增首页工作台入口、岗位管理页面、API 错误校验提示、数据库迁移和岗位工作流测试；更新 README 与 OpenAPI。

### 技术

FastAPI、Pydantic、SQLAlchemy、Alembic、SQLite/PostgreSQL JSON 字段、Next.js App Router、React、TypeScript。通过 `companies`、`job_postings`、`applications` 与 `application_status_events` 分开管理公司资料、岗位、投递记录和阶段审计；数据库唯一约束辅助防止同用户重复公司及重复来源链接。

### 与上一版本相比

上一版本完成账户、个人档案和简历管理；本次补齐 PRD 阶段一所需的岗位 CRUD 与投递看板，形成“保存岗位—核验—加入看板—记录进展”的可操作流程。CSV 批量导入、Agent 岗位提取、匹配、RAG、MCP 和提醒仍属于后续阶段，当前没有虚构自动提取或自动投递能力。

### 验证

- 后端 `.venv/bin/pytest -q`：23 项通过，新增 9 项覆盖待核验保存、来源去重、公司资料复用、用户隔离、投递阶段和历史、筛选、简历归属及核验流程。
- `alembic upgrade head`：在 `/tmp` 中的全新 SQLite 数据库成功执行三条迁移；`alembic check`：无未生成迁移。
- `python -m compileall -q app migrations tests`：通过。
- 前端 `bun run typecheck`：通过；独立临时副本 `bun run build`：通过，静态生成 `/jobs` 页面。
- PostgreSQL 17 / Redis 7 容器实际联调仍需有 Docker 的环境；SQLite API 测试和迁移已通过。
