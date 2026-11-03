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

## 修复：岗位页面 HTTP 500 与现有数据库升级

### 原因

当前本地数据库仍处于 `20261030_0002`，缺少岗位模块新增的四张表；访问岗位接口时 SQL 查询失败，产生 HTTP 500。开发服务器的 `--reload` 只重载代码，不执行 Alembic 迁移。此前岗位测试使用 `Base.metadata.create_all()` 创建完整新库，没有覆盖已有用户数据库升级及当前运行服务的联调。

### 修复内容与技术

- 使用 SQLite 在线备份接口，将当前数据库备份至被 Git 忽略的 `backend/storage/backups/`，再执行 Alembic 升级至 `20261031_0003`。升级前后对原有账号、档案和简历的完整记录做摘要比对，确认保留。
- 在 FastAPI 中处理 SQLAlchemy 数据库异常，识别 SQLite 缺表/缺字段错误及 PostgreSQL 对应 SQLSTATE；返回带 `database_schema_outdated` 错误码的 HTTP 503 和迁移操作提示，响应不暴露 SQL 或用户数据。
- 健康检查与业务接口使用一致的数据库升级提示；前端只对约定的迁移错误展示该提示，其他服务端错误继续使用通用提示。
- 新增真实 Alembic 迁移回归测试：在临时文件数据库上先运行旧迁移、保存账号/档案/已确认简历，复现缺表响应，再升级并验证原数据、岗位 CRUD、关联旧简历及投递历史。
- 补充缺字段和非迁移类数据库错误的回归测试，并明确 README 中本地开发的数据库升级步骤。

### 与上次实现相比

本次修复已有岗位模块在旧数据库上的运行问题，并补齐从旧版本升级和当前服务联调的验证；未增加新业务模块。

### 验证

- 后端 `.venv/bin/pytest -q`：26 项通过，新增 3 项回归测试。
- 当前数据库 `alembic check`：无模型与迁移差异；实际 API `/health`：HTTP 200。
- 前端 `bun run typecheck`：通过；迁移提示、通用服务端错误及输入校验错误的 4 项请求封装检查通过。
- 通过实际运行的 Next.js `/api` 代理，用临时账号验证岗位页面返回 HTTP 200、登录态岗位查询返回 HTTP 200，以及岗位创建/编辑/核验/筛选/删除、投递阶段和历史记录流程；测试结束后清理该临时账号及全部关联记录。

## 第 4 次实现：岗位 CSV 批量导入

### 完成内容

- 对照 PRD 第 2 步补齐 CSV 岗位导入。岗位管理页可下载带中文列名的模板，上传 CSV 后查看每一行的公司、职位、城市、截止时间和来源。
- 支持 UTF-8/UTF-8 BOM 与 GB18030，兼容模板中文列名和 API 字段英文列名；保留 CSV 引号、多行文本及技能/标签列表。限制文件 5 MB、最多 500 条，并将空日期、非法日期、无效链接、空行和列数异常分别反馈。
- 预览阶段只做解析和校验，不写入数据库。对当前账户已有来源链接和文件内重复来源链接标记重复，用户仅能勾选有效且非重复的行。
- 用户确认后通过单个事务批量创建公司和岗位；发现来源重复或数据库冲突时整批回滚。导入的岗位进入原有岗位列表，可继续编辑、核验并加入投递看板。

### 技术

Python 标准库 `csv`、`io` 与 `re` 处理模板、编码、RFC 风格引号/换行和列表字段；Pydantic 复用岗位字段规则；FastAPI Multipart 接收文件并提供预览和导入 API；SQLAlchemy 在一次事务中保存多条岗位并由数据库唯一约束处理并发重复；Next.js/TypeScript 增加预览选择与状态反馈。

### 与上一版本相比

上一版本只能逐条手动录入岗位。本次支持一次预览和选择多条表格岗位数据，完成 PRD 第 2 步中岗位 CSV 导入的缺口。导入仍由用户提供结构化 CSV；从网页自动抓取或让 LLM 从原始描述提取字段属于后续第 3 步，没有提前加入自动化行为。

### 验证

- 后端 `.venv/bin/pytest -q`：28 项通过；新增测试覆盖模板认证、UTF-8 BOM 与 GB18030、带引号和换行的描述、行级错误、文件内/数据库来源去重、公司资料复用、跨用户隔离及批量冲突回滚。
- `.venv/bin/python -m compileall -q app migrations tests` 与 `git diff --check`：通过。
- `bun run typecheck`：通过。
- 经当前运行的 Next.js `/api` 代理用临时账户完成模板下载、CSV 预览、批量保存和导入后编辑；联调结束后已清理测试账户及记录。

## 岗位页调整：统一列表与卡片内编辑

### 完成内容

- 根据最新交互要求，移除“全部岗位/投递看板”重复视图，统一在岗位卡片中管理阶段、简历版本、备注、下一步和历史记录。
- 移除岗位页面的“待核验/已核验”标签与“标记已核验”按钮。手动录入资料不再增加额外确认步骤，缺少字段直接显示未填写并允许编辑补充。
- 点击编辑时在对应卡片内展开表单，保存或取消后收起，不再回滚到页面顶部。新增岗位复用同一个表单组件，技能、标签和公司资料按需展开并完整保留。
- 新增岗位、CSV 导入和长篇岗位详情默认收起。保存失败显示在当前表单中，并保留输入；成功后显示明确反馈。后台刷新不卸载整个列表，也不覆盖其他卡片尚未保存的备注。
- 投递阶段和备注现在可以直接保存，无需先加入看板。首次保存会在一个事务中创建投递记录和初始历史；同阶段重复保存不增加重复历史，仍检查岗位/简历归属和请求来源。
- 更新 README 与 PRD，记录用户确认后的统一列表交互；后续 Agent 抽取结果仍按字段展示置信度与来源证据。

### 技术与上一版本的区别

使用 React 卡片局部状态和共享 `JobEditor` 组件实现就地编辑，把新增表单与岗位编辑状态分开管理；通过 Promise 传播保存异常，只有请求成功才关闭表单。FastAPI/SQLAlchemy 将已有投递更新接口扩展为首次保存时创建记录，事务保持阶段与历史一致。本次没有数据库结构变更。

上一版本编辑岗位会滚动到顶部，并有两个内容相近的列表；本次改为一个列表中按需展开操作，减少重复信息和上下跳转。

### 验证

- 后端 `.venv/bin/pytest -q`：31 项通过；新增 3 项验证直接保存阶段/备注、重复请求的历史幂等，以及非法简历、跨账户与不可信来源请求不产生部分记录。
- 前端 `bun run typecheck`：通过；隔离副本中的 `bun run build`：通过。
- Chromium/Playwright 真实浏览器 9 组交互通过：单列表与折叠入口、下方卡片就地编辑、保存及附加字段保留、取消不写入、模拟 HTTP 409 后保留草稿并重试、跨卡片刷新不丢失备注、直接记录投递及查看历史、新增和 CSV 导入、390px 手机布局无横向溢出。
- 浏览器测试未发现页面脚本异常，桌面/手机截图已检查；临时测试账号及关联记录已清理。
- Python 编译检查及 `git diff --check`：通过。

## 第 3 步：Agent API 与岗位信息提取

### 完成内容

- 岗位页新增“AI 提取岗位”：接收用户粘贴的招聘原文（20–30,000 字符）和可选来源链接，不访问招聘网站。模型提取公司、职位、地点、类型、批次、截止日期、学历和技能；结果逐字段带置信度与原文引用。用户可修改结果，确认后才创建岗位。
- 新增 `agent_runs` 持久化任务状态、步骤事件、尝试次数、模型名、错误摘要和结果；新增 `job_source_evidence` 保存原始文本及字段级引用。任务/来源 API 都按当前用户隔离，任务列表不返回原文；待确认原文通过单独的 owner-scoped API 读取。
- 提供 OpenAI 兼容 Chat Completions Provider Adapter，使用环境变量配置地址、密钥、模型、请求超时和低置信阈值。密钥不进入 API 响应或日志；未配置、超时、限流、服务端错误与非法模型输出都会转换成安全错误摘要。原文按不可信数据处理，不提供工具调用权限。
- 服务端对模型 JSON 做 Pydantic 字段/类型/长度校验；字段引用必须逐字出现在输入原文里，否则引用清空、置信度归零并列入“需要确认”。低置信、缺失或无引用的字段在前端明确标注。
- 提供任务详情、SSE 事件回放、失败重试（每任务最多 3 次）、最多 3 个并行活动任务、任务删除。进程重启时将残留的排队/运行任务标记为失败并允许重试。岗位保存和证据写入同一事务；确认接口幂等，删除岗位会清除关联的原文、证据和任务记录。
- Compose、`.env.example`、README 和 PRD 补充模型服务配置与 API 用法。当前用 FastAPI 进程内后台任务，持久队列在 PRD 第 6 步接入 Celery/Redis；生产部署时须配置模型地址、模型名和 API Key。

### 技术与上一版本的区别

上一版本支持手动与 CSV 结构化录入，不能从原始招聘文本提取字段，也没有可观察/重试的 Agent 任务。本次新增模型 Provider 边界、持久化任务状态、SSE、字段证据校验和人工确认后保存；仍未实现网页抓取、RAG、匹配、多 Agent、Skills 或自动投递。

### 验证

- 后端 `.venv/bin/pytest -q`：38 项通过；包含任务创建/完成/SSE 回放、字段证据与置信度处理、重试上限、确认幂等、数据隔离、失败任务删除与原文清理、删除岗位清理证据、Provider MockTransport 请求格式/缺配置/伪造引用测试。
- 临时 SQLite 从零执行 4 条 Alembic 迁移；`alembic check`：无未生成迁移。`uv lock --check --offline`、Python 编译、前端 `bun run typecheck`、`git diff --check`：通过。
- 为本地 `backend/offerpilot.db` 创建权限为 `0600` 的迁移前备份，再从 `20261031_0003` 升级至 `20261101_0004`；本地 API `/health` 返回 HTTP 200，新 Agent 任务路由未登录时按预期返回 HTTP 401。
- Chromium/Playwright 浏览器流程（模型/API 使用测试响应）：粘贴招聘文本、检查低置信字段及证据、修改城市、确认保存、岗位列表显示、查看已保存引用；无浏览器脚本异常。
- 隔离目录的 Next.js 生产构建尝试超过 5 分钟停留在 `compile` 且无进展，已终止该构建；因此不计为通过。当前验证覆盖 TypeScript 和实际开发页浏览器流程，生产构建仍需后续在构建正常的环境复核。

## 修复：新岗位保存后被现有筛选条件隐藏

- 核对数据库后确认 Agent 已创建岗位和来源依据；岗位页保存成功后的刷新复用了当前搜索/城市/状态等筛选，可能导致新记录被列表条件过滤，看起来像没有保存。
- 新增手动岗位、CSV 导入或 AI 提取岗位成功后，统一清空当前筛选条件并刷新完整岗位列表，保持岗位列表页面内的新记录可见。
- 验证：`bun run typecheck` 通过；Playwright 浏览器回归先应用“已投递”筛选，再完成 AI 字段核对和保存，确认筛选重置、新岗位出现且无页面脚本异常。

## 修复：AI 岗位保存后的列表可见性与请求覆盖

### 原因与复现

上次仅清空筛选，未覆盖已有多条岗位时的排序和视口行为。此次沿真实 Web 代理、FastAPI、SQLite 核对保存与查询：岗位和来源依据已持久化，列表也返回记录，但原列表优先按截止日期排序，保存后没有定位卡片。用独立临时账号预置 12 条较早截止的岗位后，真实页面确认的新岗位排在第 13 条、视口下方约 3700 像素处；原代码的首卡/视口断言失败。

### 完成内容与技术

- SQLAlchemy 列表查询默认改为 `created_at DESC, id DESC`，让最新保存的岗位在刷新后仍排在前面；保留截止日期筛选。
- React 保存回调使用接口返回的 `JobPosting` 立即更新列表，清空筛选并聚焦对应卡片；列表刷新时保留并再次定位目标岗位，避免较早的已保存任务或批量导入目标被重新排序移出视口。成功提示增加“查看岗位”，已确认任务增加“查看已保存岗位”。已有岗位数据无需重新导入。
- 使用请求版本号忽略较早发出的列表响应，防止空列表或旧筛选响应在保存完成后覆盖当前状态。保存后读取列表失败时，已返回的岗位仍在页面中。
- 补齐创建/重试直接返回成功任务时的草稿回填，避免空字段覆盖模型结果。模型测试显式隔离本地 `.env`；排查时旧的缺配置测试曾触发一次合成样例调用，修正后缺配置测试不会使用真实模型密钥。
- 提交可重复运行的 `scripts/check_agent_job_visibility.py`，使用真实服务及专属临时账号，模型阶段预置成功任务，确认保存、查询和来源依据均走真实 API；无数据库迁移。

### 验证

- 后端 `.venv/bin/pytest -q`：39 项通过；新增确定性测试覆盖最新保存排序、相同创建时间稳定顺序和截止日期筛选。
- 前端 `bun run typecheck`：通过。
- 真实 Chromium 回归：同一 12 条已有岗位场景修复后新岗位位于第 1 条并可见；刷新后仍为第 1 条，来源依据可读取；恢复已确认任务可定位岗位；人为延迟真实的空筛选响应，验证其不会覆盖保存后的列表。再新增 3 条岗位后打开较早已保存任务，确认目标在列表刷新后仍保持可见。页面无脚本异常。
- 测试临时账号与关联数据已全部清理，原有已确认任务保留；实际页面截图已检查。

## 第 4 步：个人资料 RAG 与岗位匹配

### 完成内容

- 新增个人求职笔记的增删改查；RAG 索引只包含当前账户的笔记和用户已确认的简历。文档按 900 字符切片并保留 120 字符重叠，使用独立配置的 OpenAI 兼容 Embeddings API 批量生成 1536 维向量。
- 新增资料重建索引与问答 API。PostgreSQL 使用 pgvector `vector(1536)`、余弦距离和 HNSW 索引；SQLite 把向量存为 JSON，并在应用中计算余弦相似度，供无 Docker 的本地运行和测试。
- 回答只读取当前用户检索到的片段。模型返回的引用须同时满足“片段属于本次检索结果”和“引用原文逐字存在于该片段”；引用无效或无证据时不展示模型答案，明确返回未找到支持资料。无索引资料时不请求模型。
- 新增岗位匹配卡片操作，逐项比较岗位学历要求、城市/职位/行业偏好与档案，并检查岗位技能在最新已确认简历或技能档案中是否有文字依据。没有静态总分或录用概率；“未找到”明确表示现有资料未写到，不判断用户实际不具备。
- 简历删除、笔记修改/删除会清除对应的派生向量片段；重建索引时先成功生成新向量，再以事务替换旧索引，模型失败不会清空已有索引。所有文档、笔记和检索结果均按 `user_id` 服务端隔离。
- 新增 Alembic `20261101_0005`；Compose PostgreSQL 镜像切换为含 pgvector 扩展的 PostgreSQL 17 镜像。SQLite 与 PostgreSQL 的数据查询路径分别处理，Redis 未用于本模块。
- README 增加 `/knowledge` 使用步骤及独立 Embeddings 环境变量说明。当前本地 `.env` 中没有 Embeddings 配置，因此真实外部向量服务尚未联调；配置 Chat 模型和 Embeddings 模型是两件独立的事。

### 技术与上一版本的区别

上一版本可从招聘原文提取并保存岗位，但不能搜索个人简历/笔记，也没有岗位条件匹配。本次增加 pgvector RAG、可核验引用及规则化匹配；模型用于向量生成和基于检索片段的问答，结构化筛选/岗位条件判断仍由代码执行。没有引入多 Agent、Skills、网页抓取或自动投递。

### 验证

- 后端 `.venv/bin/pytest -q`：48 项通过；新增测试覆盖向量 Provider 请求和维度、索引切片、引用校验、笔记变更清理、索引过程中资料修改的并发保护、跨用户隔离、无简历保护、硬性学历/偏好与技能证据，并检查 PostgreSQL 的 `VECTOR(1536)` DDL 与余弦运算符可编译。测试通过 Fake Provider/MockTransport，不访问外部模型。
- 前端 `bun run typecheck`：通过；本地 Next.js `/knowledge` 页面返回了预期页面内容；本地 API `/health` 返回数据库正常。
- SQLite Alembic 全迁移链在后端迁移测试中通过。本机 `backend/offerpilot.db` 已从 `20261101_0004` 升至 `20261101_0005`；迁移前备份为 `backend/storage/backups/offerpilot-before-0005-20261101.sqlite3`，权限 `0600`。
- `git diff --check`：通过。当前环境没有 PostgreSQL/pgvector 实例及 Docker，因此未声称通过真实 PostgreSQL 集成测试；本地实际数据库验证使用 SQLite。

## 修复：兼容 Embeddings 服务返回的向量维度

- 用户触发“建立 / 更新索引”返回 HTTP 503。用不含个人资料的合成诊断文本调用已配置的 Embeddings 服务，确认服务可连通，但返回维度与代码硬编码的 1536 不同；因此不是登录、数据库或 API 连通故障，而是实现错误限制了可用模型。
- 移除固定的 1536 维校验，索引时记录实际向量维度；PostgreSQL 使用无固定维度的 pgvector 列，查询前检查当前模型/维度与索引一致，配置改变时提示重建索引。SQLite 继续用 JSON 与本地余弦计算。PostgreSQL 改为账户过滤后的精确余弦检索，移除只支持固定维度的 HNSW 索引。
- 向量服务错误现在以不含密钥/响应正文的错误码写入 API 日志；前端仅对知识模块的安全 Embeddings/Answer 错误展示服务端消息，其他 5xx 仍不泄漏内部异常。
- 新增 Alembic `20261101_0006`，为现有索引记录维度并把 PostgreSQL 向量列改为可变维度；本地数据库迁移前另存了权限为 `0600` 的备份。

### 验证

- 使用不含个人资料的合成文本直接检查已配置的 Embeddings 服务：请求成功，返回 1 个 1024 维向量；修复前同一返回会因 1536 维硬编码而失败。
- 后端 `.venv/bin/pytest -q`：49 项通过，新增覆盖 1024 维索引与问答、拒绝同次请求中的混合维度。前端 `bun run typecheck`、Python `compileall` 和 `git diff --check` 均通过。
- 本机 SQLite 已迁移到 `20261101_0006`；迁移前备份为 `backend/storage/backups/offerpilot-before-0006-20261101.sqlite3`，权限 `0600`。运行中的 API `/health` 返回数据库正常。
- 当前环境没有 PostgreSQL/pgvector 实例，因此没有声称完成真实 PostgreSQL 集成验证；PostgreSQL 查询和无固定维度列仍有 SQL 编译测试。

## 第 5 步：MCP 与公司公开信息研究

> 本节验证记录对应首次使用 Brave Provider 的实现；后续已按用户可用的 API Key 切换到 Tavily，当前配置与验证见本节后的“搜索服务切换为 Tavily”。

### 完成内容

- 选用 Brave Search Web Search API 作为一个只读公开信息源。工具只提交搜索词并返回标题、URL、摘要片段和搜索时间；不抓取链接目标、不访问登录内容、不执行外部写操作。
- 使用官方 MCP Python SDK v2 注册 `search_company_recruitment` 工具，并在 FastAPI 中通过 MCP Client 调用同一个工具。额外提供 `offerpilot-research-mcp` stdio 入口供兼容 MCP 的客户端连接。工具有输入长度/结果数校验、只读注解、12 秒搜索超时、每进程每分钟 30 次限流；API 对每账户执行每小时 10 次限流。
- 岗位卡片增加“公司研究”折叠面板；按公司名和岗位名称搜索，展示事实摘要、逐项原文引用、全部来源链接与时间。相同岗位 30 分钟内复用结果；超过 7 天的报告显示过期提示，并可强制重新搜索。
- Chat 模型只接收 Brave 返回的公开摘要片段，返回结构化事实、来源 ID 和原文引用。服务端校验来源属于本次搜索，且引用逐字存在于对应片段；无证据时保留来源并明确提示，不把模型错误或真实空结果伪装成搜索失败/无结果。
- 复用 `AgentRun` 保存用户、岗位、查询词、公开来源、模型、状态、事件、引用和结果；研究 API 按用户检查岗位所有权，并提供读取最新成功结果的接口。Agent 岗位抽取任务列表只读取 `job_extraction` 类型，避免两类运行记录互相污染。
- 新增 `OFFERPILOT_BRAVE_SEARCH_API_KEY` 和可配置搜索超时环境变量；Compose 会注入配置，README 说明模型与搜索服务的数据流。使用 MCP SDK v2 后，Python 最低版本升为 3.11；Docker API 镜像使用 Python 3.12。本模块没有新增数据库表或迁移。

### 技术与上一版本的区别

上一版本只支持个人资料 RAG 和结构化岗位匹配，没有只读外部搜索工具或带来源的公司调研。本次增加 MCP 标准工具调用、公开搜索 Provider Adapter、引用核验、用户范围的运行审计与研究面板；没有引入自动网页抓取、写操作、多 Agent 或定时任务。

### 验证

- 后端 `.venv/bin/pytest -o addopts='' -q`：59 项通过，其中新增 10 项覆盖 MCP Client/Server 调用、Brave 响应归一化、摘要 JSON、原文引用校验、结果缓存、账户级与进程级限流、失败记录、空结果和跨用户隔离。测试使用 Fake Provider/MockTransport，不调用真实外部搜索或模型服务。
- 前端 `bun run typecheck`、依赖 `uv lock --check --offline`、Python `compileall`、`git diff --check`：通过；`uv sync --offline --extra dev` 已安装 MCP CLI 入口。
- 本地 API `/health` 返回数据库正常；Next.js `/jobs` 和页面 JavaScript bundle 包含公司研究控件。当前运行环境未配置 Brave API Key，因此未执行真实 Brave 网络查询；接入前需在仓库根 `.env`（Compose）或 `backend/.env`（本地）配置该变量。

## 第 5 步补充：搜索服务切换为 Tavily

- 根据实际可用的 Tavily API Key，将默认搜索 Provider 从 Brave Search 切换为 Tavily Search API。MCP 工具、岗位研究页面、结果缓存、来源链接、引用校验和 AgentRun 持久化逻辑保持不变。
- 后端通过 `POST https://api.tavily.com/search` 和 Bearer Token 认证，只请求基础网页搜索；将 Tavily 的 `title`、`url`、`content`、`published_date` 归一化为项目统一来源结构。新增无效 Key、额度/频率限制的安全错误提示，Key 不写日志、不发送给浏览器。
- 新配置项为 `OFFERPILOT_TAVILY_API_KEY`；Compose 将根目录 `.env` 中的配置注入 API 容器。本地 API 从 `backend/.env` 读取。更新 `.env.example` 和 README。没有数据库结构变化。
- 修正岗位卡片研究面板上的 Provider 名称，避免迁移后仍显示 Brave Search。
- 搜索适配器及摘要 Provider 定向测试：5 项通过，使用 HTTPX MockTransport 验证 Tavily endpoint、Bearer 认证、请求参数、结果归一化、危险 URL 丢弃、无效 Key 和额度/频率错误映射；没有使用真实 API Key 发起外部请求。Python 编译检查、前端类型检查和 `git diff --check` 通过。
- 公司研究完整测试文件未能完成：首个 ASGI 集成用例在账户注册请求处等待超过一分钟，尚未进入 Tavily Provider 调用；已中断该次运行。需要在可正常完成注册集成测试的环境补跑回归。

## 第 6 步：提醒中心与可靠后台任务

### 完成内容

- 增加账户 IANA 时区字段和提醒管理接口，支持招聘开放、网申截止、测评、面试、跟进及自定义事件；提醒可关联岗位，保存事件时间、提前量、时区和站内通知渠道。
- 提醒支持暂停/恢复、完成、取消、延期和手动重试。暂停中的提醒不参与后台投递；恢复时若原触发时间已过则立即重新排队。创建请求使用客户端幂等键和请求内容哈希；重复提交返回同一提醒，键与内容不匹配时拒绝冲突请求。
- 新增 Celery Worker 与 Beat：Beat 每分钟扫描到期提醒，Worker 在事务中创建站内通知并更新提醒状态。按提醒 ID 和排期版本设置唯一键；重复运行或任务重试不会生成重复通知。数据库故障可重试，达到 5 次后提醒显示为失败并允许用户手动重试。
- 新增站内通知列表、未读计数和标记已读接口。所有提醒、通知和岗位关联均由当前用户范围约束。
- 用户修改时区需明确确认是否重算未来提醒；服务端保持原本地事件钟点，更新 UTC 触发时间并增加排期版本。夏令时导致的不存在时间会拒绝更新并提示调整。
- 新增提醒中心页面：建立/关联提醒、查看触发时间与状态、延期/完成/取消/重试，以及查看和标记站内通知。Compose 增加独立 Worker/Beat 服务并通过 Redis Broker 工作；更新 API 配置、README 和环境变量模板。
- 新增 Alembic `20261101_0007`，为账户添加时区字段，并创建提醒、通知表及幂等约束和到期扫描索引。

### 技术与上一版本的区别

上一版本提供只读 MCP 公司搜索和岗位公开信息研究，但没有持久化定时通知。本次接入 Celery、Redis Broker、Beat 周期调度和 Worker；业务提醒与通知状态留在数据库，Redis 不作为唯一的数据存储。数据库仍可使用 SQLite 或 PostgreSQL，时间统一按 UTC 保存，按账户时区展示。

### 验证

- 后端 `.venv/bin/pytest -o addopts='' -q tests/test_reminders.py`：9 项通过，覆盖幂等创建、用户范围、暂停/恢复、延期/完成、通知投递与去重、通知已读、时区重算、失败重试、Celery Beat 任务配置和路由注册。测试直接调用异步路由逻辑及投递服务，不连接 Redis 或外部模型。
- 使用全新临时 SQLite 数据库执行 `alembic upgrade head`：从初始版本连续升级到 `20261101_0007` 成功；Python `compileall`、前端 `bun run typecheck` 和 `git diff --check` 通过。
- 当前本地 SQLite 数据库已先备份，再从 `20261101_0006` 升级到 `20261101_0007`；备份 `backend/storage/backups/offerpilot-before-0007-20261101.sqlite3` 权限为 `0600`。本地 API `/health` 返回 200，OpenAPI 已列出提醒、暂停/恢复及通知路由；本地 Next.js `/reminders` 返回 200 并包含提醒中心页面文案。
- 本机的 ASGI in-process 请求测试在既有 `/health` 端点的同步数据库依赖阶段也会挂起；与第 5 步记录的账户注册集成测试等待问题一致。本次未将 ASGI/浏览器端到端请求、真实 Redis Worker/Beat 或 Docker Compose 运行宣称为通过，需要在可正常执行 HTTP 集成测试和 Redis/Compose 的环境补验。

## 第 7 步：Skills 与审批

### 完成内容

- 新增六个带版本号的求职 Skill 模板：岗位分析、简历定向建议、申请问题草拟、公司研究摘要、面试准备和申请准备包。每个模板公开输入/输出约定、示例与使用边界；模型输出经过结构校验，来源引用必须指向本次提供的资料且原文逐字匹配，不支持的引用会被剔除并要求人工核对。
- AgentRun 现在保存 Skill ID/版本、幂等键、请求哈希、状态事件和关联简历版本。流程依次校验用户资料与岗位上下文、调用模型生成草稿、验证证据并保存结果；支持查询、失败重试和取消。读取岗位、资料、简历及研究材料时均限制在当前账户范围内。
- `application_prep_pack` 允许用户申请将草稿保存为站内准备包。用户先批准明确的本地保存操作；服务端重新检查目标、草稿内容哈希、批准记录与有效期后，才执行站内数据库写入。操作及批准结果写入审计记录，重复执行会返回已有准备包。其他 Skill 不暴露写操作执行器；MVP 不会登录招聘网站、提交申请、发送邮件或执行其他外部写操作。
- 新增 `/skills` 工作台，展示模板约定和边界，支持选岗位、补充问题、查看运行进度与引用证据、重试/取消、审核并保存申请准备包，以及查看历史准备包和审计记录。仪表盘、岗位、知识、档案和提醒页面均可导航至工作台。
- 删除简历或岗位时同步清理关联的模型运行结果、批准请求与准备包；保留审计记录但解除已删除的批准记录关联，避免删除业务资料后仍留下派生内容。
- 新增 Alembic `20261102_0008`，扩展 AgentRun 幂等与版本字段，并创建批准请求、申请准备包及审计事件表。README 说明使用步骤、隐私边界和本地数据库迁移方式。

### 技术与上一版本的区别

上一版本通过 Celery/Redis 定时处理提醒与站内通知；本次加入可复用的版本化 Skill 工作流、基于来源证据的草稿生成、显式审批、幂等本地执行与审计。根据 PRD，现由 LangGraph `StateGraph` 编排“上下文校验 → 草稿生成 → 引用校验 → 人工审批 → 本地保存”。普通业务校验和写入仍由确定性服务代码负责；模型调用沿用 OpenAI 兼容接口，提醒仍由 Celery/Redis 处理。`AgentRun` 保存产品可见的任务、状态和事件，LangGraph checkpointer 单独保存暂停/恢复所需的图状态。

### 验证

- 后端 `.venv/bin/pytest -o addopts='' -q tests/test_skills.py`：LangGraph 对齐后 12 项通过。覆盖六种模板、输入校验、幂等与用户隔离、引用清洗、模型失败、审批过期/篡改检查、拒绝后的重新运行边界、重复执行、简历删除清理及 OpenAI 兼容 Provider 请求格式；使用 Fake Provider/MockTransport，不调用真实模型。
- 测试覆盖真实 `ainvoke` 图节点、SQLite 检查点中断与恢复、审批后本地保存；测试用 SQLite 检查点数据库与业务测试数据库隔离。前端 `bun run typecheck`、`.venv/bin/python -m compileall -q app tests`、`uv lock --check` 和 `git diff --check` 通过。
- 在独立临时 SQLite 上验证完整 Alembic 升级链及从 `20261101_0007` 升级/降级数据保留；本机 `backend/offerpilot.db` 先备份至 `backend/storage/backups/offerpilot-before-0008-20261102.sqlite3`（权限 `0600`），再成功迁移到 `20261102_0008`。
- 迁移集成测试文件在既有 ASGI 注册请求处等待且未运行到迁移断言，已停止该用例。额外尝试排除迁移文件后的后端回归集，30 秒内没有产生结果，已中断；因此只报告定向 Skills 测试，不将全量回归算作通过。真实模型、浏览器端到端、Redis Worker/Beat 和 Docker Compose 联调也未执行。迁移本身由独立临时数据库全链路与本机升级验证。

### PRD 对齐修正：LangGraph 编排与检查点

- 将先前仅由 `AgentRun` 显式阶段驱动的流程改为 LangGraph `StateGraph`；`AgentRun` 保留为业务运行记录，LangGraph 负责图节点推进及人工审批中断/恢复，两者职责不同。
- 图状态只保存 `run_id`、阶段结果及审批决定，不写入简历、岗位原文或模型草稿；草稿及用户可见事件仍保存于用户隔离的业务表。
- PostgreSQL 模式使用 `AsyncPostgresSaver`，SQLite 本地模式将 checkpoint 写入存储目录独立文件；每次运行以 `run_id:attempt_count` 作为 thread ID，审批执行时沿用同一 thread ID，通过 `Command(resume=...)` 恢复。
- 人工审批节点只为申请准备包触发 `interrupt`；其他 Skill 会越过审批及保存步骤。执行节点再次核对审批主体、动作、目标岗位、有效期、草稿哈希和审批摘要哈希，再执行唯一允许的本地数据库保存，并记录审计事件。
- 测试发现当前依赖组合中连续条件边会在异步执行时挂起，因此图改为静态有向顺序边；节点根据 `outcome` 和 `decision` 跳过不适用的工作，审批中断和批准后的恢复仍在图内完成。
- 运行任务仍由 FastAPI `BackgroundTasks` 触发，checkpoint 不等同于持久任务队列；服务重启后尚未完成的 `queued/running` 记录由应用启动逻辑标记失败并允许手动重试。审批暂停对应的图 checkpoint 会保留。

## 第 8 步（子模块一）：Agent 评测基础设施

### 完成内容

- 新增版本化合成烟雾集：50 条岗位文本抽取案例，包含城市/截止日期缺失场景；30 条 RAG/公司研究问题，覆盖可回答、来源冲突、旧资料、无答案和 4 条不可信指令文本安全探针。数据由固定生成器生成并写入 JSONL，不含真实招聘内容或候选人资料。
- 新增严格数据契约和评分函数。岗位抽取报告字段精确率、召回率、准确率和逐字引用支持率；RAG 报告 Recall@5、引用支持率、冲突/弃答模式准确率，以及 P50/P95 任务时延。
- 新增 `python -m app.evals.runner` 命令；默认只校验数据集，不调用模型。仅传入 `--live` 后才会调用配置的 Chat Completions / Embeddings 服务，并将报告写到 `artifacts/agent-eval/`。支持 `--limit` 做小样本试运行。
- 报告明确标记数据集为 `synthetic_smoke_v1`。当前 Provider Adapter 没有 token usage 元数据，因此 token 用量和费用输出为空；未把合成样本结果宣称为 PRD 验收指标。

### 验证与限制

- `backend/.venv/bin/pytest -o addopts='' -q tests/test_eval.py`：4 项通过；验证数据量/分类/安全探针、字段与引用评分、RAG 冲突及弃答评分，以及使用 Fake Provider 的评测运行路径。
- 两个评测 CLI 的无模型数据校验模式、Python `compileall`、后端依赖锁检查、前端类型检查和 `git diff --check` 通过。没有运行 live 模型评测，因此没有报告模型准确率、延迟或费用实测值。
- 此为 PRD 第 8 步的评测基础子模块。合规的人工标注验收集、安全检查清单、生产部署配置和完整作品集演示材料仍需后续完成；当前环境没有 Docker，未执行 Compose 构建或容器联调。

## PRD F-10：Agent 自然语言任务计划

### 完成内容

- 在 `/agent` 增加任务规划页。用户可输入自然语言求职待办，查看模型整理出的动作、提醒时间和关联岗位；需要补充日期等关键信息时页面会展示澄清问题。仪表盘和提醒中心增加入口。
- 任务规划以 LangGraph `StateGraph` 编排“读取上下文 → 生成候选计划 → 校验日期与岗位 → 保存预览”。该图不配置 checkpoint：一次调用中的状态只在内存流转，AgentRun 保存可恢复的任务内容、用户可见状态和预览；用户确认通过独立 API 触发最终提醒写入。
- 新增 `POST/GET /api/v1/agent/task-plans`、单条查询、重试、取消和确认接口。任务计划复用 `AgentRun` 持久化状态与事件，不新增数据库表或迁移；状态包括排队、运行、等待确认、需补充信息、已确认、已取消和失败。
- 新增 OpenAI 兼容的结构化任务规划 Provider。模型请求包含账户时区和当前本地时间；日期不明确时要求澄清，只有日期时默认当地 09:00。关联岗位只从当前用户的数据中查找，无法唯一匹配时保留未关联草稿。
- 用户确认前不会创建提醒。确认时由服务端把预览写入既有 Reminder 表，按计划 ID 生成幂等键；重复确认返回既有提醒。Provider 失败可重试，确认和计划写入都做账户归属检查。
- 提示词明确将用户文本视为不可信输入，只生成站内提醒草稿；本模块不会登录招聘网站、改动投递阶段、发送消息或执行外部操作。

### 技术与上一版本的区别

之前已有固定输入的版本化求职 Skills 和 LangGraph 工作流；本次补上 PRD F-10 的自然语言待办规划。模型负责从请求中提出结构化提醒草稿，普通代码负责日期/时区校验、岗位归属匹配、任务状态、幂等和写入。AgentRun 提供可查询的任务生命周期，Reminder/Celery 继续负责后续站内通知。

### 验证与限制

- `backend/.venv/bin/pytest -o addopts='' -q tests/test_task_planner.py`：4 项通过，覆盖未确认不写提醒、确认幂等、澄清阻止确认、失败重试、当地 09:00 默认值及 OpenAI 兼容请求结构；测试使用 Fake Provider/MockTransport，没有调用真实模型。
- `backend/.venv/bin/python -m compileall -q app tests`、FastAPI OpenAPI 路由注册检查、在 `frontend/` 执行 `bun run typecheck` 和 `git diff --check` 通过。
- 未运行真实模型或浏览器端到端联调。尝试运行 `test_agent.py` 的 ASGI 注册流程时请求挂起，已停止该次尝试；因此不把 HTTP 登录全链路列为通过项。另尝试 `bun run build`，Next.js 优化构建持续占用 CPU 且两分钟无进度输出后停止，不计为通过。

## PRD F-11 子模块：公司档案聚合

### 完成内容

- 新增 `/companies` 公司档案页和 `GET /api/v1/companies`、`GET /api/v1/companies/{company_id}` 只读接口。接口按登录用户查询公司、岗位、投递阶段和公司研究运行记录，不依赖前端过滤。
- 每家公司归集招聘批次、岗位截止日期、岗位来源、个人公司备注以及每个岗位最新一次成功的研究。研究事实带原文引用和来源链接；保留来源片段、搜索时间和过期状态。页面可直接对岗位启动/刷新只读公司研究。
- 研究结果超过 7 天会在公司汇总和岗位行标出；没有研究或没有可核验证据时给出不同提示，不把缺少证据说成公司事实。搜索与摘要继续使用 Tavily 和现有 Chat Completions 配置。
- 复用 `Company`、`JobPosting`、`Application` 和 `AgentRun` 现有表，无新增数据库迁移。公司备注单独标识为用户自己的记录，与公开搜索事实区分。
- 仪表盘和岗位管理页增加公司档案入口；README 补充页面入口、数据来源和证据边界。

### 技术与上一版本的区别

上一版本可从单个岗位卡片发起研究并查看引用，但没有跨岗位的公司归档。本次按公司聚合岗位、招聘批次、用户备注和各岗位最新研究；研究本身仍沿用 MCP 只读搜索、Tavily Provider、引用校验和 AgentRun 持久化，不新建重复研究记录表。

### 验证与限制

- `backend/.venv/bin/pytest -o addopts='' -q tests/test_company_archive.py`：2 项通过，覆盖公司归档聚合、最新研究选择、引用与过期状态、无证据提示及跨用户隔离。
- `backend/.venv/bin/python -m compileall -q app tests`、FastAPI OpenAPI 路由注册检查、在 `frontend/` 执行 `bun run typecheck` 和 `git diff --check` 通过。未调用真实搜索或模型服务，也未完成浏览器端到端联调。

## PRD 设置与数据控制：导出与账户删除

### 完成内容

- 新增 `/settings` 页面，展示当前账户邮箱与时区、当前站内通知渠道，以及模型/搜索服务的配置边界；时区仍从提醒中心修改。网页不读取、不回显服务端 API 密钥，密钥继续由部署者通过 `backend/.env` 配置。
- 新增 `GET /api/v1/account/export`，以 ZIP 提供账户资料、简历解析文本、岗位/投递/公司记录、Agent 任务、审批审计、提醒通知、笔记和 RAG 文本片段。已上传且仍存在的 PDF/DOCX 原件一并导出；缺失原文件会在清单中注明。密码哈希、服务密钥和派生 embedding 数值不导出。
- 新增 `DELETE /api/v1/account/me`。操作需要再次提交当前密码和完全匹配的账户邮箱；服务端校验同源请求后，按外键依赖顺序删除账户业务记录、Agent 历史、提醒通知与 RAG 向量片段，删除账户私有文件目录并清除登录 Cookie。
- 文件目录会先在同一存储根目录内暂存；数据库删除事务失败时恢复目录，避免只删文件却保留账户。当前模型的用户表使用逐表显式删除，因此在 SQLite 外键检查未启用时也会清理所有用户记录。
- 复用既有数据库表，没有新增迁移。仪表盘增加设置入口，README 补充数据范围和 API。

### 技术与上一模块的区别

上一模块按公司聚合招聘信息和研究证据；本次加入账户级隐私控制，不调用模型或外部服务。导出使用 SQLAlchemy 按 `user_id` 隔离读取、内存/临时文件滚动的 ZIP 构建和流式下载；删除使用子记录优先的数据库事务与同文件系统目录重命名，成功后清理暂存目录。

### 验证

- 后端 `.venv/bin/pytest -o addopts='' -q tests/test_account_data_controls.py`：3 项通过，覆盖导出用户隔离及简历原件、错误邮箱/密码阻止删除、成功删除全部用户表记录/RAG 片段/私有文件并清除 Cookie。
- `.venv/bin/python -m compileall -q app tests`、FastAPI OpenAPI 路由检查、前端 `bun run typecheck` 和 `git diff --check` 通过。未运行完整后端回归、浏览器端到端或生产数据库联调。

## PRD 页面模块：求职仪表盘

### 完成内容

- 将 `/dashboard` 从仅显示账户问候和静态提示的页面改为登录后的账户仪表盘；数据全部来自 `GET /api/v1/dashboard`，未登录或服务错误时显示可操作的错误提示，不用演示数据填充个人工作区。
- 展示最近更新的进行中投递阶段及阶段数量。当前阶段取当前用户最近更新、且尚未结束的 Application；已接受/拒绝/撤回/关闭的投递不覆盖当前进行阶段。
- 汇总当前时区下未来 7 天的提醒与投递跟进、未来 14 天的岗位截止时间，以及最近 5 条 AgentRun。每个列表有对应页面入口；接口只返回展示所需字段，不返回 Agent 的输入原文、模型结果或错误正文。
- 查询对 Application、Reminder、JobPosting、Company 和 AgentRun 均限制当前用户；时间窗口按用户 IANA 时区确定。没有创建新表或迁移，不调用模型/搜索服务。
- 仪表盘导航增加页面内快捷入口；README 增加汇总 API 说明。

### 技术与上一模块的区别

上一模块提供数据导出和账户删除；本次读取多个已有业务模块并组合成一个只读 dashboard API。后端用 SQLAlchemy 聚合投递阶段，并用用户归属条件联查岗位/公司；前端用 TypeScript 响应类型和用户时区格式化时间，保留各模块原有的写入和确认边界。

### 验证

- 后端 `.venv/bin/pytest -o addopts='' -q tests/test_dashboard.py`：2 项通过，覆盖投递阶段、提醒/跟进、截止日期和 Agent 运行聚合，以及用户间数据隔离。
- `.venv/bin/python -m compileall -q app tests`、FastAPI OpenAPI 路由检查、前端 `bun run typecheck` 和 `git diff --check` 通过。未运行浏览器端到端或 PostgreSQL/Redis Compose 联调。

## PRD Agent 工作区：任务类型入口与跨流程运行记录

### 完成内容

- `/agent` 增加由后端返回的任务类型目录：提醒计划、岗位抽取、岗位匹配、公司研究、个人资料问答和求职材料。每类显示用途、只读/生成草稿边界、是否需要用户确认及现有执行入口。
- 新增 `GET /api/v1/agent/workspace`，聚合用户自己的最近岗位提取、公司研究和 Skills 运行摘要；按当前账户联查岗位/公司，仅返回任务类别、状态、时间与岗位标签，不返回原文输入、模型结果或错误正文。自然语言提醒计划仍由同页现有预览/确认流程展示，避免重复一份任务历史。
- 岗位抽取入口可直接跳转到 `/jobs?task=extract` 并展开提取表单；其他能力跳转至已有的岗位、公司、资料或 Skills 专属流程。没有绕过各专属流程的用户确认和审批逻辑。
- 复用 AgentRun 和现有业务接口，没有新增数据库迁移或外部副作用。

### 技术与上一模块的区别

上一模块将投递、提醒和 Agent 运行聚合到求职仪表盘；本次聚焦 PRD §6 的 Agent 工作区，增加明确的任务类型目录与跨工作流运行摘要。执行仍由现有岗位提取、提醒计划、公司研究、资料问答和 Skills 服务负责，工作区只是受控入口与可观测视图；单一 LangGraph 对所有任务类型统一编排仍是后续架构集成项，本次没有将独立流程伪装成一个统一执行图。

### 验证

- 后端 `.venv/bin/pytest -o addopts='' -q tests/test_agent_workspace.py`：2 项通过，覆盖能力目录/确认边界、跨流程运行摘要、隐私字段裁剪和用户隔离。
- `.venv/bin/python -m compileall -q app tests`、FastAPI OpenAPI 路由检查、前端 `bun run typecheck` 和 `git diff --check` 通过。未运行浏览器端到端或真实模型联调。

## 求职工作台加载超时兜底

- 仪表盘读取 `/api/v1/dashboard` 时增加 15 秒超时和卸载清理；请求长期无响应时展示明确的超时错误与重试入口，不再永久停留在加载文案。
- 排查时本机首页、仪表盘 HTML、前端脚本与 API 健康检查均返回成功；未登录的仪表盘 API 返回预期 401。当前没有已登录浏览器会话可复现挂起请求，因此超时处理是可见失败兜底，不代表已经定位导致原请求挂起的服务端原因。
- 验证：前端 `bun run typecheck`、`git diff --check`；本机 HTTP 检查首页、仪表盘、API 健康状态及脚本资源。

## 远程开发访问说明与真实浏览器排查

- 补充远程服务器开发时的 SSH/VS Code 端口转发步骤，明确电脑浏览器的 `localhost` 与服务器的 `localhost` 属于各自机器；转发命令在本机端口冲突时明确失败，便于发现错误映射。
- 使用已有的 Playwright/Chromium 环境连接当前运行中的服务：根首页内容可见，页面脚本无运行错误、无悬挂资源；未登录仪表盘显示登录入口。
- 使用一次性测试账户验证注册、已登录仪表盘和 Agent 工作区可见；删除测试账户返回 204，再访问仪表盘显示登录入口。该过程未操作现有账户。
- 此次验证确认服务器侧页面与认证流程可运行；用户本地浏览器是否映射至当前服务器，需要通过其电脑上的端口转发确认。此前仅检查 HTTP 状态与增加超时不足以确认浏览器完整加载。

## PRD §5.1、§6：持久化 Agent 任务统一路由（首批流程）

### 完成内容

- 新增统一 LangGraph 路由，接入岗位提取、提醒计划和 Skills 的创建/重试入口。服务端先核对 `AgentRun` 的任务类型和 `queued` 状态，再把 ID 与任务类型交给既有专属处理流程；过期、类型不符或已处理的运行会被跳过。
- Skills 的批准执行和拒绝恢复也经过该路由。恢复前复核 Skill 运行状态、审批记录与运行记录的关联、账户归属及审批决定，避免错误审批恢复另一项任务。
- LangGraph 状态仅传递任务 ID、任务类型和审批参数，不带招聘原文、简历文本或生成草稿。既有专属处理流程继续负责模型调用、来源证据、业务校验、人工确认和写入；没有新增数据库表、迁移或外部写入动作。
- LangGraph 异步调用采用 v2 返回格式；Skills 适配层将中断结果转换回现有接口使用的 `__interrupt__` 结构，以保留审批恢复行为。

### 技术与上一版本的区别

上一版在各 API 路由中分别直接调度提醒计划、岗位提取和 Skills；本次增加共同的任务入口与权限/状态校验，同时保留每类任务已有的执行图和业务规则。这是 PRD 单一显式工作流的第一段集成，当前只覆盖三类持久化后台任务；公司研究、资料问答和岗位匹配仍由各自已有路径处理，后续再按需求接入。

### 验证与限制

- `backend/.venv/bin/pytest -o addopts='' -q tests/test_agent_workflow.py`：4 项通过，覆盖三类任务路由、旧任务跳过、审批与运行/账户关联校验，以及应用工厂中真实岗位抽取处理器的派发和失败状态记录。
- `backend/.venv/bin/pytest -o addopts='' -q tests/test_task_planner.py tests/test_skills.py`：16 项通过，回归提醒预览/确认及 Skill 草稿、审批和恢复行为；使用测试 Provider，不调用真实模型。
- `backend/.venv/bin/python -m compileall -q app tests` 和根目录 `git diff --check` 通过。
- 额外尝试岗位提取 HTTP/ASGI 全链路测试时，该测试等待未完成后停止，因此不计作通过；本次以应用工厂创建的真实路由图直接调用测试处理器派发。未运行全量后端测试、前端测试、真实模型调用或浏览器联调。

## PRD §5.1、§5.2：公司公开研究接入统一 Agent 路由

### 完成内容

- 将公司研究加入统一 LangGraph 任务类型。岗位研究 API 仍在本次请求内等待结果，返回结构、30 分钟缓存、每账户每小时 10 次限流和搜索失败的 503 语义保持不变；运行记录现在按 queued → running → succeeded/failed 推进。
- 研究处理器从 `AgentRun` 重新读取所属岗位、公司和搜索词，执行前确认岗位及公司属于同一账户；搜索/摘要期间不把原文放入图状态，最终写入来源、引用、摘要和阶段事件。
- 研究完成前再次确认岗位和公司没有变化；若目标在搜索期间被删除或改名，任务失败并提示重新研究，避免把旧公司结果写到当前岗位。
- 继续复用 MCP allowlist 只读搜索、Tavily Provider、摘要模型和引用校验；没有新增表、迁移或对外写操作。

### 技术与上一模块的区别

上一模块已将岗位提取、提醒计划和 Skills 接入统一路由；本次把已有的公司研究管线也改为由 `AgentRun` 任务状态校验后派发。API 的同步等待行为与产品响应不变，搜索与摘要逻辑从路由处理函数中提取为可独立调度的流程，未来可继续纳入统一进度和后台执行策略。

### 验证与限制

- `backend/.venv/bin/pytest -o addopts='' -q tests/test_agent_workflow.py tests/test_task_planner.py tests/test_skills.py`，并运行公司搜索 Provider/MCP 的 6 个定向用例：共 28 项通过，覆盖统一路由、审批绑定、公司研究处理器成功/失败、引用保存、缓存、Skills 与提醒计划。
- `backend/.venv/bin/python -m compileall -q app tests` 和 `git diff --check` 通过。公司研究既有 HTTP/ASGI 测试在测试环境等待未完成，未计为通过；新增直接调用 API 处理函数的集成测试覆盖了路由派发、结果和缓存。未调用真实 Tavily/LLM 服务或进行浏览器联调。

## PRD §5.1、§5.2：个人资料 RAG 问答接入统一 Agent 路由

### 完成内容

- 将 `knowledge_qa` 注册为统一 LangGraph 任务类型。`POST /api/v1/knowledge/ask` 先保存 `AgentRun`，再由统一路由校验类型与 queued 状态并派发到现有 RAG 流程；接口仍同步返回原有问答和引用结构。
- 为问答任务记录 queued、running、succeeded/failed 状态、检索/回答阶段事件、尝试次数和结果。未建立索引、检索证据不足时明确返回无证据答案；向量/回答 Provider 失败会保留可重试的失败记录和安全错误信息。
- 保留用户级索引隔离、向量模型/维度校验、逐字引用校验；回答完成前重新检查引用片段仍属于当前用户，避免资料被删除或重建后保存失效引用。
- Agent 工作区将最近问答任务标为“个人资料问答”，可跳转到资料页查看和继续使用。更新 README 与本开发日志，没有新增数据库表或迁移。

### 技术与上一模块的区别

上一模块把公司研究接入统一路由，并在执行前后检查岗位/公司归属；本次接入本地个人资料 RAG，重点是确认检索片段与问答运行属于同一用户，并在持久化前重新核验引用。向量检索、回答生成和引用规则仍由既有知识服务实现；统一 LangGraph 只负责有限任务分发和运行状态前置校验，不把简历正文或问答内容放进图状态。

### 验证

- `backend/.venv/bin/pytest -o addopts='' -q tests/test_agent_workflow.py`：7 项通过，覆盖统一派发、所有者引用、无索引无证据，以及 Provider 失败后的 AgentRun 记录。
- RAG 定向测试 3 项通过，覆盖 Embeddings 维度校验、文本切块和 PostgreSQL 向量查询编译；`tests/test_task_planner.py tests/test_skills.py`：16 项通过。
- `backend/.venv/bin/python -m compileall -q app tests`、前端 `bun run typecheck`、`git diff --check` 通过。使用 Fake Provider/SQLite 测试库，没有调用真实 LLM、向量服务或外部网络；未做浏览器端到端测试。

## PRD F-08、§5.1：岗位匹配接入统一 Agent 工作流

### 完成内容

- 将 `job_match` 加入统一 LangGraph 路由。岗位卡片的“匹配分析”现在通过 `POST /api/v1/jobs/{id}/match` 创建并运行 `AgentRun`；原有 `GET` 只读接口保留，便于兼容既有客户端。
- 匹配仍使用原有确定性逻辑比较硬性学历条件、城市/岗位/行业偏好和简历技能证据，不调用 LLM、不生成录用概率，也不修改岗位或投递状态。
- 成功运行保存结构化结果、岗位关联、阶段事件和尝试次数；岗位不属于当前用户时不创建任务；没有已确认简历时将失败原因写入运行记录。Agent 工作区显示岗位匹配运行记录。
- 复用 `AgentRun`，没有新增表或迁移。更新 README 的工作流说明和 API 契约。

### 技术与上一模块的区别

上一模块将资料问答的检索与引用校验接入统一路由；本次接入的是纯规则、只读的岗位匹配。它不需要模型 Provider 或外部工具，重点是复用统一任务状态和所有权校验，同时不改变原有匹配结果契约。

### 验证

- `backend/.venv/bin/pytest -o addopts='' -q tests/test_agent_workflow.py`：8 项通过；新增用例覆盖成功结果、阶段记录、工作区展示、跨用户岗位访问拒绝和未确认简历的失败记录。
- RAG/匹配相关的文本切块与 PostgreSQL 向量查询编译定向测试：2 项通过。
- `backend/.venv/bin/python -m compileall -q app tests`、前端 `bun run typecheck` 和 `git diff --check` 通过。使用 SQLite 测试库，未运行真实 PostgreSQL/Redis Compose 或浏览器端到端验证。

## PRD §7.3：Agent 执行耗时、Provider 用量与费用估算

### 完成内容

- 统一 Agent 路由为每次派发记录执行耗时和 request ID；API 响应增加 `X-Request-ID`。HTTP Provider 观测记录 Chat Completions、Embeddings、Tavily 调用耗时、操作、模型和成功/失败状态。
- 从 Provider 响应中的 usage 元数据汇总 prompt/completion/total tokens。可配置模型输入/输出、Embedding 和 Tavily 单次搜索费率，按配置估算费用；缺少 token 用量或费率时显式标为估算不完整，不把未知数当成零。
- 在 Agent 工作区显示完整可确认的任务耗时、Token 数和费用估算；每次尝试的 Provider 明细保存在 `AgentRun.events` 中。
- 观测层不持久化请求/响应正文、Authorization Header 或搜索查询；利用现有 JSON 事件存储，没有新增数据库列或迁移。

### 技术与上一模块的区别

上一模块让岗位匹配进入统一任务路由并保存执行状态；本次为所有统一路由增加共用的计量钩子。HTTPX transport/response hook 在不改变各 Provider 返回契约的情况下捕获调用时间和 usage，ContextVar 将这些数据限制到当前 request/run，工作区只暴露聚合值。

### 验证

- `tests/test_agent_telemetry.py tests/test_agent_workflow.py tests/test_agent_workspace.py`：14 项通过，覆盖 request ID 绑定、Chat/Embedding/Tavily 计量、传输失败记录、正文不落库、任务事件持久化和工作区汇总。
- `tests/test_task_planner.py tests/test_skills.py`：16 项通过；岗位抽取、Embedding、Tavily 与公司摘要 Provider 定向回归：8 项通过。
- Python `compileall`、前端 `bun run typecheck`、`git diff --check` 通过。未调用真实服务；费率需由使用者按当前服务商价格配置，估算不替代账单。

## PRD §5.1：岗位抽取任务取消

### 完成内容

- 提取面板增加“取消解析”。排队任务立即标记已取消，统一工作流看到非排队状态后会跳过模型调用。
- 运行中的任务记录取消请求并显示“取消中”；当前 Provider 请求返回后，不论成功还是失败，都将任务完成为已取消且不保存解析结果。取消接口对重复请求幂等，已完成或已保存的任务不能取消。
- SSE 以 `cancelled` 事件结束；取消期间任务不能删除或被新的任务额度释放。API 重启时，取消中的任务按已取消收敛，原文与结果仍遵循现有账户隔离和清理规则。
- 更新 API/TypeScript 状态类型、面板状态提示、README 接口说明。未增加数据库字段或迁移。

### 技术与上一模块的区别

上一模块为统一 Agent 路由增加耗时、Token 与费用观测；本次处理任务生命周期控制。取消采用持久化的 `cancelling → cancelled` 状态与 SSE 事件，后台 handler 在写成功结果或失败状态前重新读取取消状态，避免用户请求取消后保存模型输出。当前 HTTP Provider 调用无法被服务端强行中断，因此运行中取消是协作式取消：会等待该请求返回，但结果不会进入业务数据。

### 验证

- `tests/test_agent.py`：新增覆盖运行中取消后丢弃成功响应、排队取消后不调用 Provider。
- 定向 Agent 生命周期测试：5 项通过，覆盖运行中取消遇到成功/失败响应、排队取消跳过 Provider、统一路由派发与非排队任务跳过。
- Python `compileall`、前端 `bun run typecheck`、取消路由 OpenAPI 注册检查及 `git diff --check` 通过。
- 整份 `tests/test_agent.py` 未能完成：已有的首个 ASGI 集成用例卡在注册账户请求阶段，尚未进入岗位抽取；取消流程使用独立 Provider/SQLite 生命周期测试验证。
