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
