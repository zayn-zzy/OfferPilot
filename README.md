# OfferPilot

面向秋招求职流程的 Agent 工作台。当前已实现账户认证、个人档案、简历版本管理，以及在统一岗位列表中维护资料和投递进度，后续按 [PRD](秋招求职%20Agent%20产品需求文档.md) 分模块推进。

## 技术栈

- 前端：Next.js App Router、React、TypeScript
- 后端：FastAPI、Pydantic、SQLAlchemy、Alembic
- 数据：Compose 使用 PostgreSQL 17 和 Redis 7；简历文件使用私有本地存储卷
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

Compose 会启动 PostgreSQL 17、Redis 7、API 和 Web；PostgreSQL 数据及简历原文件分别保存在命名卷中，首次启动会运行 Alembic 迁移。浏览器通过 Web 同源的 `/api` 路径访问后端，再由 Next.js 服务转发到 API 容器，因此不依赖浏览器能否直接访问后端端口。账户密码使用 Argon2id 哈希；登录状态通过 HttpOnly Cookie 维护。开发环境未设置密钥时使用临时随机密钥，重启后现有会话会失效；部署环境必须设置 `OFFERPILOT_SECRET_KEY`。

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
