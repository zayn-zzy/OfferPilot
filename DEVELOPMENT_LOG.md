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
