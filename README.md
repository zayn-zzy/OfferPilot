# OfferPilot

面向秋招求职流程的 Agent 工作台。当前实现到全栈骨架与账户登录阶段，后续按 [PRD](秋招求职%20Agent%20产品需求文档.md) 分模块推进。

## 技术栈

- 前端：Next.js App Router、React、TypeScript
- 后端：FastAPI、Pydantic、SQLAlchemy、Alembic
- 数据：PostgreSQL；Redis 已加入本地 Compose，为后续后台任务预留
- 本地开发：Docker Compose；前端依赖使用 Bun

## 启动

需要 Docker Compose。复制 `.env.example` 为 `.env`，将 `POSTGRES_PASSWORD` 和 `OFFERPILOT_SECRET_KEY` 改成自己的值，然后从本目录运行：

```bash
docker compose up --build
```

- Web：<http://localhost:3000>
- API：<http://localhost:8000>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>

首次启动会运行 Alembic 迁移。账户密码使用 Argon2id 哈希；登录状态通过 HttpOnly Cookie 维护。开发环境未设置密钥时使用临时随机密钥，重启后现有会话会失效；部署环境必须设置 `OFFERPILOT_SECRET_KEY`。

## 后端开发与测试

```bash
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
uv run pytest
```

测试使用隔离的 SQLite 内存数据库，不需要启动 PostgreSQL。实际开发环境默认连接 Compose 中的 PostgreSQL。

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
