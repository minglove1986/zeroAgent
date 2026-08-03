# zeroAgent 研发断点（防上下文中断）

> **用途**：会话突然中断或新开上下文时，Agent/人类先读本文件再继续。  
> **维护规则**：每次有实质推进后 **必须更新**——顶部「当前断点」整段覆盖；底部「断点日志」**追加一条**（勿删历史）。  
> **禁止**：写入任何 API Key / 密码明文。

---

## 当前断点（覆盖写）

| 项 | 值 |
|---|---|
| 更新时间 | 2026-07-30 17:01:38（东八区） |
| 能力 | 修复本机 Windows Celery prefork 崩溃 |
| 改动 | `celery_app` Windows 默认 `worker_pool=solo`；`restart-dev.ps1 -WithCelery` 显式 `--pool=solo` |
| 测 | 需关掉旧 zeroAgent-Celery 窗口后按下方命令重启 |
| 下一步 | 重启 Celery 后复测反馈异步任务 |
| 备注 | Docker Linux worker 仍用 prefork，不受影响 |

### 新会话开场（复制）

```text
继续 zeroAgent。先读 docs/superpowers/CHECKPOINT.md「当前断点」。
```

### 启动命令备忘

```powershell
# 一键 Docker 部署（api/worker/beat + 依赖；API 固定 :8000）
cd D:\HermesWork\zeroAgent
.\scripts\deploy-docker.ps1
# 可选：.\scripts\deploy-docker.ps1 -Full
# 可选：.\scripts\deploy-docker.ps1 -Embed
# 停止：.\scripts\deploy-docker.ps1 -Down

# 本机热更新重启（API+Web 不在容器内开发时用）
cd D:\HermesWork\zeroAgent
.\scripts\restart-dev.ps1
# 可选：.\scripts\restart-dev.ps1 -WithDeps
# 可选：.\scripts\restart-dev.ps1 -WithCelery

# 后端（必须用本机 Python3.12；固定 :8000，禁止随意改端口）
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m uvicorn app.main:app --app-dir src --reload --host 127.0.0.1 --port 8000
# 前端代理：web/.env.local 中 API_PROXY_TARGET=http://127.0.0.1:8000

# 前端
cd D:\HermesWork\zeroAgent\web
npm run dev

# 依赖（也可被 deploy-docker 一并拉起）
cd D:\HermesWork\zeroAgent\deploy
docker compose --env-file .env up -d mysql redis rabbitmq litellm

# 本机 Celery（Windows 必须 --pool=solo）
cd D:\HermesWork\zeroAgent
$env:PYTHONPATH = "src"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo
```

---

## 断点日志（只追加）

### 2026-07-30 17:01:38
- 根因：本机 Windows Celery 默认 prefork → `tasks, accept, hostname = _loc` 解包失败；已改 solo（celery_app + restart-dev）；未 commit。

### 2026-07-30 16:37:06
- Web 登录页页脚居中增加内部版本号 `V0.0.1-B · 内部版本`；未 commit。

### 2026-07-30 16:28:45
- Web 登录页副文案改为「企业级智能体工作平台…」；去掉 SSE/交互卡片实现细节；未 commit。

### 2026-07-30 16:26:49
- 产品中文命名：全仓「零辖」→「灵辖」（README 主仓 + 3 worktree）；UI/工程代号 zeroAgent 未动；未 commit。

### 2026-07-30 16:10:04
- 部署重启：api/worker/beat rebuild 已起；迁移至 `0030_alert_webhooks`；admin-web :3001 Ready；`/health` ok。

### 2026-07-30 16:03:14
- 管理端反馈审阅/报表 + 员工端异步副作用已实现：`/admin/feedbacks*`、Celery 校准/差评通知/Webhook、admin-web「消息反馈」、迁移 `0030_alert_webhooks`；相关单测 11 passed；未 commit。

### 2026-07-30 15:52:40
- 反馈规格增补：员工端赞/踩落库快返回；Celery 异步做意图阈值校准；仅 down 发站内通知+Webhook。见 `2026-07-30-admin-feedback-review-design.md`；未 commit。

### 2026-07-30 15:46:15
- 管理端反馈审阅/报表：设计已确认并写入 `docs/superpowers/specs/2026-07-30-admin-feedback-review-design.md`；待用户审阅后出实现计划；未 commit。

### 2026-07-30 15:15:51
- 连续发送队列：api 已 rebuild 且 healthy；web :3000 可达；待浏览器硬刷新联调。

### 2026-07-30 15:09:37
- chat-queue final-fix：`ensureConversation(gen)` 防切会话绑错 id；`messages/send` 所有权 403 先于 supersede；`test_dismiss_card` 4 passed + `tsc` PASS；未 commit。

### 2026-07-30 15:03:17
- Task 1–5 连续发送队列收口：后端作废卡 + 前端 FIFO 队列/停止/焦点；dismiss 单测 3 + chatSendQueue 8 + tsc PASS；浏览器 E2E 待人工；规格已落地；未 commit。

### 2026-07-30 14:43:04
- Task 1 完成：`cancel_pending_cards` + `dismiss-card` + `supersede_pending_card`；pytest 3 passed；未 commit。

### 2026-07-30 14:36:00
- 连续发送队列规格已批准；实现计划写入 `docs/superpowers/plans/2026-07-30-chat-send-queue.md`，待选执行方式。

### 2026-07-30 14:35:05
- 连续发送队列设计定稿写入 `docs/superpowers/specs/2026-07-30-chat-send-queue-design.md`（含发送后聚焦输入框）；待用户审阅后出实现计划。

### 2026-07-30 14:21:17
- 重建 api/worker；`test_context_compress` 7 passed；容器冒烟压缩链路通过；Celery `compress_context` 已注册并可执行。

### 2026-07-30 14:06:56
- 上下文摘要压缩落地：相对窗 0.75 触发 / 目标 min(2000, 0.15窗)；异步 Celery；Redis digest + 短记忆改写；下轮注入【会话摘要】。
- 单测 `test_context_compress`；顺带修 persona_trial / plan_execute mock 签名。

### 2026-07-30 13:41:51
- 切换模型跟随上下文窗：后端按 `max_input_tokens`；PATCH 返回 context；前端即时刷新。

### 2026-07-30 13:23:14
- 全链路审计：补 doc_analyze、记忆抽取、上下文打包；新增 `test_llm_session_model_threading` 防回退。
- 非会话路径（chunk_clean/QA/试聊）保留环境默认。

### 2026-07-30 13:11:54
- 修：会话选 Agnes 但 LiteLLM 仍见 MiniMax。根因 L3/kb/Agent 图未带 `selected_model`。
- 已贯通 `model` 参数；api/worker rebuild；相关单测 17 绿。

### 2026-07-30 11:37:47
- Task 6–9：员工选模 API/UI；管理端模型治理页；ContextBudgetPacker；API 规范 v0.8.2 §12.3。

### 2026-07-30 11:32:34
- Task 4：管理端 `GET/POST sync/PATCH llm-models`、`PUT agents/{id}/llm-models`；审计写入；PATCH 刷 Redis。
- Task 5：`model_resolve` + Gateway.resolve；messages 发消息/重试走解析；停用/缺失拒绝。

### 2026-07-30 11:26:10
- Task 3：`litellm_sync`（缺窗 incomplete、缺失联动停用、管理员关闭不自动开）；启动钩子经 Gateway；单测绿。

### 2026-07-30 11:23:42
- Task 1：迁移 `0029_llm_model_governance`（`llm_models` / bindings / `selected_model`）；ORM `catalog_models`；MySQL upgrade 成功。
- Task 2：`models_cache.py`（`za:llm:models:v1`）对齐 persona_cache；单测绿。

### 2026-07-30 11:19:49
- Task 0 完成：`LlmGateway` 全局门面；对话/记忆/意图/试聊/知识清洗与 QA/Agent 图均改走 Gateway。
- `client.py`/`lc_chat.py` 标明仅内部；单测 `test_llm_gateway.py` 绿。

### 2026-07-30 11:13:00
- 规格/计划补强：**LlmGateway 全局统一封装**为业务唯一 LLM 入口；client 仅内部使用。

### 2026-07-30 11:10:57
- 用户确认 LLM 模型治理规格；写出实现计划 `docs/superpowers/plans/2026-07-30-llm-model-governance.md`。
- 要点：启动+手动同步 LiteLLM→校验→MySQL→Redis；会话级选模；LiteLLM 缺失联动停用；P2 上下文预算防超窗。

### 2026-07-29 16:56:39
- 方案 B：Compose 增加 `litellm-db`（Postgres）并给 `litellm` 配独立 `DATABASE_URL`，以启用 `/ui`。
- `.env.example` / 本地 `.env` / `环境与密钥.md` 已补 `LITELLM_DB_*`、`LITELLM_UI_*`。
- 注意：本机 `docker pull postgres` 曾因网络卡住；镜像就绪后再 `up -d litellm-db litellm`。

### 2026-07-29 16:32:21
- 前后台 UI 挂载品牌标：`BrandMark`；员工端顶栏/登录/对话空态；管理端侧栏/登录/favicon/manifest。
- `assets/brand` 同步到 `admin-web/public`；双端静态图标 HTTP 200。

### 2026-07-29 16:30:00
- 根据 `D:\HermesWork\zeroAgent.png` 制作透明背景 logo：
  - `assets/brand/zeroagent-logo-master.png`（1440×1440 RGBA）
  - `web/public/zeroagent-icon-{16,32,48,64,128,180,192,256,384,512,1024}.png`
  - `web/public/favicon.ico`（16/24/32/48/64/128/256）、`favicon.png`、`apple-touch-icon.png`
  - `web/public/icon-192.png` / `icon-512.png` / `site.webmanifest`（PWA）
- 接入 `web/src/app/layout.tsx` 的 `metadata.icons` 与 `manifest`；`npm run build` 12 路由通过。

### 2026-07-29 16:04:42
- 本地验证：`docker compose up -d --build api worker beat`；OpenAPI 已含 `/test` `/reset-default`。
- 登录 demo 后 GET 人格含 `platform_safety`；试聊返回 `used_persona=true` 且有模型回复。
- admin-web `:3001` 可访问，待浏览器 UI 点验。

### 2026-07-29 16:00:36
- PRD v0.8.1：§12.1.3 提示词分层 + 第十六章 D43–D47；API 规范补 `/system/persona`。
- 平台安全段 `platform_safety.py` 始终最前注入；停用人格仍保留安全段。
- 试聊 `POST .../test`、恢复默认 `POST .../reset-default`；admin 页只读安全段 + 试聊区。
- 单测 21 passed（`test_system_persona` + `test_context_source_boundary`）。

### 2026-07-29 15:50:15
- 系统人格：管理端 `/system/persona`；MySQL+Redis；system 路径必注入【系统人格】。
- Agent 字段 `inherit_system_persona`（默认开）；员工端创建 Agent 可勾选；运行时引用非拷贝。
- 迁移 `0028_system_persona`；规格 `2026-07-29-system-persona-design.md`。

### 2026-07-29 15:19:45
- Codegraph：`codegraph init -i`，300 files / 3657 nodes。
- 管理后台：修复 `admin-web` 登录同源 Cookie、AuthProvider、概览解包；`:3001` 已起。
- 迁移 `0027_admin_console_schema`：`config_audit_logs` + L2/记忆字段 origin 等治理列。

### 2026-07-29 14:10:45
- 修复删除会话 HTTP 405：本机多个孤儿 uvicorn worker 占 `127.0.0.1:8000`，请求未打到已含 DELETE 的 Docker API。
- 已终止孤儿进程；`restart-dev.ps1` / `deploy-docker.ps1` 端口清理增加「幽灵 PID → 杀其子进程」。

### 2026-07-29 11:40:21
- 系统对话侧栏：历史会话支持删除；`DELETE /api/v1/conversations/{id}` 软删 `status=deleted`；列表仅 active。
- 迁移 `0026_conversation_status_deleted`。

### 2026-07-29 11:25:43
- 记忆抽取：白名单 Catalog（DB+Redis+管理 API）；三触发异步（显式/空闲/窗口）；去掉请求内同步 LLM 抽取。
- 注入侧过滤非白名单 key；迁移软删历史 `person_of_interest` 等脏 auto 记忆。
- 工程约定：`docs/05-开发指南/配置类模块缓存约定.md`。

### 2026-07-29 10:47:04
- L2 否定门禁：「我没让你总结赵世龙的简历」→ `chitchat`，不再 `doc_analyze`。
- 关键词真相源 MySQL `intent_l2_keywords` + 启动/CRUD 刷 Redis；管理 API `/api/v1/intent/l2-keywords`。
- 规格/计划：`docs/superpowers/specs|plans/2026-07-29-l2-negation-catalog*`。

### 2026-07-28 15:29:36
- 新增 Docker 一键部署：`scripts/deploy-docker.ps1` / `deploy-docker.cmd`。
- Compose 补 `api`（`:8000`）；Dockerfile 打包 `alembic.ini` + `migrations`；部署后自动 `alembic upgrade head`。
- 与 `restart-dev.ps1` 分离：部署进容器 vs 本机热更新。前端仍本机 `:3000`。

### 2026-07-28 11:17:13
- 新增本地一键重启：`scripts/restart-dev.ps1` / `scripts/restart-dev.cmd`。
- 行为：释放 8000/3000/8001/8002 → 写回 `API_PROXY_TARGET=8000` → 新窗口起 uvicorn + `npm run dev`；可选 `-WithDeps` / `-WithCelery`。

### 2026-07-28 10:15:31
- 用户裁定：**后端固定 `:8000` / 前端 `:3000`**，禁止因僵尸进程或临时联调改到 8001/8002。
- 已写入 `.cursor/rules/zeroagent-ai-dev.mdc`；`web/.env.local` 与启动备忘均改回 `8000`。
- 占用时先杀进程，再回 8000。

### 2026-07-27 16:45:29
- **Mock 回声**：用户问「你是什么模型」得到「收到：…【已注入用户记忆】」——`:8002` 进程继承了 `MOCK_EXTERNAL=true`。
- 已用 `MOCK_EXTERNAL=false` 重启 `:8002`；直打验证返回 MiniMax-M3，非 Mock。

### 2026-07-27 15:46:05
- **过程阶段不可见根因**：`:8001` 被旧 uvicorn 僵尸占用（无 stage 代码）；新进程绑端口失败，前端仍代理到僵尸。
- **绕过**：后端改 `:8002`，`web/.env.local` 指向 8002；实测 SSE 含 stage/thought_delta。
- 验证：硬刷新聊天页，新发「你好」。

### 2026-07-27 14:45:31
- **过程面板可见性**：用户反馈页面找不到；加固正文合并不丢 process、面板样式更醒目；说明「深度思考」按钮是占位、与过程区无关。
- 验证：硬刷新 `/chat`，新发「你好」，看助手气泡上方「处理过程」。

### 2026-07-27 12:44:11
- **路由收束实现完成**（inline T1–T6）：`resolve_route` → Dispatcher；有 Agent 禁系统 kb 捷径；System kb 模板合成 + D14；L3 Mock=fixture（含「我是谁」→chitchat）；`meta.route`。
- 测：57 passed。未 commit。

### 2026-07-27 12:24:05
- **路由收束实现计划**：`docs/superpowers/plans/2026-07-27-conversation-route-resolver.md`（Task1–6）。
- **下一刀**：用户选执行方式。未 commit。

### 2026-07-27 12:17:13
- **路由收束规格**：`docs/superpowers/specs/2026-07-27-conversation-route-resolver-design.md`（RouteResolver + Handler；禁拼片段捷径）。
- **下一刀**：用户审阅规格。未 commit。

### 2026-07-27 11:41:36
- **联调热修**：`我是谁` 误入 `kb_lookup`（`(.+?)是谁`）→ 改为 `self_identity` 闲聊；`kb_lookup` 路径补 stage/thought；过程面板加「处理过程」标题。
- 测：8 passed。浏览器需硬刷新后新开对话验证。

### 2026-07-27 11:19:01
- **过程可见 Task1–6 收口**：合成器 + Plan-Execute astream + runtime/legacy/闲聊 + 前端 ProcessPanel + API 文档。
- 测：过程可见相关包 **34 passed**。未 commit。
- **下一刀**：浏览器联调系统对话过程区。

### 2026-07-27 11:06:03
- **过程可见实现计划**：`docs/superpowers/plans/2026-07-27-chat-process-visibility.md`（Task1–6）。
- **下一刀**：用户选 subagent-driven 或 inline 执行。未 commit。

### 2026-07-27 10:30:18
- **对话过程可见规格定稿**：`docs/superpowers/specs/2026-07-27-chat-process-visibility-design.md`。
- 裁定：阶段胶囊+可折叠思考；合成叙述；不落库；方案一 SSE。
- **下一刀**：用户审阅规格后写实现计划。未 commit。

### 2026-07-27 10:17:05
- **上下文分栏 Task4 收口**：CHECKPOINT 更新；规格状态改「已实现」。
- 测：`test_context_source_boundary` + `test_plan_execute_graph` + `test_chat_routing_hotfix` + `test_route_clarify_p2` **23 passed**（6.57s）。未 commit。
- **下一刀**：新开对话验证称呼与记忆偏好。

### 2026-07-27 10:13:45
- **上下文分栏 Task3**：legacy `_build_llm_messages` 接 `TurnContextBlocks`；删除 `_IDENTITY_GUARD`；`_stream_skill_fc`/闲聊改为 `build_turn_context_blocks`；短记忆按 role 注入（已 append 本轮 user 时 `short[:-1]`）。
- 测：`test_context_source_boundary` + `test_chat_routing_hotfix` **13 passed**。未 commit。

### 2026-07-27 10:07:55
- **上下文分栏 Task2**：`run_plan_execute`/`run_agent_turn` 透传 `memory_access`；组装 `context_system`；`_execute_respond` 用分栏替换症状 `_RESPOND_SYSTEM`；RAG/技能 obs 经 `label_third_party_observation`；`_stream_plan_execute` 删除 `_ = memory_access`。
- 测：`test_context_source_boundary` + plan_execute + chat_routing_hotfix **16 passed**。下一步 Task3 legacy。

### 2026-07-27 09:44:31
- **对话路由热修**：① `build_route_clarify_card` 无助手候选时标题同步为「是否检索知识库」；② L2 `_META_REPLY` 将「资料从哪/我怎么是/刚才你说」标为 chitchat；③ legacy `_IDENTITY_GUARD` + Plan-Execute `_RESPOND_SYSTEM` 禁止用 KB 人名当用户称呼。
- 测：`tests/test_chat_routing_hotfix.py` 等 **17 passed**。复测请新开对话。

### 2026-07-27 09:22:17
- **B5 收尾**：方案 B Task1–6 完成；相关回归 **42 passed**；`_stream_skill_fc` 标注 legacy；默认 `AGENT_RUNTIME=langgraph`。
- 联调：Agent 绑定「文档理解」技能后重启服务验证。

### 2026-07-27 09:21:37
- **B4 落地**：`migrations/versions/0023_seed_skill_doc_understand.py`（skill_doc_understand + kb_lookup/kb_doc_analyze）；`tests/test_doc_understand_e2e.py`（内存 DB、Mock ReAct 调 kb_doc_analyze dump、「唐亮的全部信息」）。
- 测：`test_doc_understand_e2e` **2 passed**（Python312）；本机 `alembic upgrade head` → 0023 成功。

### 2026-07-27 09:18:42
- **B3 落地**：`plan_execute.py`（AgentState、plan→execute loop→aggregate、Mock 规则 §5.4）、`build.py`（`run_agent_turn`）、`config.agent_runtime`/`agent_plan_max_steps`；`runtime._stream_plan_execute` + `stream_mock_reply` 切换。
- 测：`test_plan_execute_graph` **5 passed**；`test_skill_fc` 加 `AGENT_RUNTIME=legacy` fixture；漏斗/ ReAct 回归 **21 passed**（Python312）。

### 2026-07-27 09:12:46
- **B2 落地**：`src/app/modules/agent/graph/skill_react.py`（reason→act LangGraph、`load_skill_openai_tools`、`run_skill_react`）；ask_user deferred_card；kb_lookup/kb_doc_analyze async + citation 合并。
- 测：`test_skill_react_graph` **4 passed**（Python312）；runtime 未改（Task4 再接）。

### 2026-07-27 09:07:52
- **B1 落地**：`doc_analyze_graph.py`（load→budget→route→dump|single|map-reduce→cite）、`doc_analyze.py`、`kb_doc_analyze` registry/executor、L2 `doc_analyze`、runtime 无 Agent 漏斗。
- config：`doc_analyze_context_tokens` / `output_reserve` / `map_chunk_tokens` / `max_output_chars`。
- 测：`test_doc_analyze_graph` **10 passed** + `test_kb_entity_filter` **3 passed**（Python312）。

### 2026-07-27 09:00:50
- 规格通过（方案 B）。实现计划：`docs/superpowers/plans/2026-07-27-agent-langgraph-runtime.md`。
- 待执行：Task1 lc_chat → … → Task6 收尾。

### 2026-07-27 08:58:44
- 用户选 **方案 B**：主 Agent Plan-Execute+ReAct 与文档理解一并落地。
- 规格已重写为完整 B 设计（B0–B5 分期）；待用户审阅通过后写实现计划。

### 2026-07-24 17:29:53
- 用户指出 PRD **Plan-Execute + ReAct** 亦未实现；写入设计 §0 缺口与范围 A/B 待选。

### 2026-07-24 17:26:57
- **设计再修订**：LLM 对接改为 LangChain（ChatOpenAI→LiteLLM Proxy），禁止本刀/后续补全走纯 httpx；存量 `client.py` P1 迁完。
- 规格：`docs/superpowers/specs/2026-07-24-doc-understand-skill-design.md`。

### 2026-07-24 17:24:08
- **设计修订**：用户要求 P0 即引入官方 LangGraph；删除「自研状态机一期」方案。
- 规格：`docs/superpowers/specs/2026-07-24-doc-understand-skill-design.md`（待审）。

### 2026-07-24 17:19:51
- **设计（待审）**：整篇文档理解——技能 `skill_doc_understand` + 工具 `kb_doc_analyze` + 阅读子图（预算内单次 / 超长 map-reduce / dump 拼接）。
- 规格：`docs/superpowers/specs/2026-07-24-doc-understand-skill-design.md`。
- 注：现网仍为单层技能 FC；子图一期可自研状态机，二期换 LangGraph。

### 2026-07-24 16:03:30
- **热修**：搜「高扬」串出「唐亮」——根因 `extract_focus_terms("搜索下高扬")` 为空，Hybrid 按前端技能相似混检。
- 修：焦点前缀/裸名、L2 person_search、标题 `-高扬` 抽词、检索结果 prefer_hits；相关 **12 passed**。

### 2026-07-24 15:38:44
- **切块预览闭环落地**：Task1–7。检索仅 published；ingest→pending_review；chunk list/update/confirm/reopen；llm-clean；前端 ChunkReviewPanel；e2e 测绿。
- 测：`test_chunk_review`+ingest+lookup **24 passed**。未 commit（用户未要求）。

### 2026-07-24 15:32:54
- **Task4 LLM 切块清理**：`chunk_llm_clean.py`（suggest/apply、Mock 噪声行去重、`is_contract_like`）；`POST .../chunks/llm-clean`；`tests/test_chunk_review.py` 新增 5 用例，全文件 12 用例全绿（Python312）。
- 合同保护：标题含「合同」或 `schema_policy`+合同语义 → apply 默认 409，须 `force_apply=true`。
- **下一刀**：Task5 端到端检索验收或 Task6 前端切块预览。

### 2026-07-24 15:27:32
- **Task3 切块 API**：`chunk_ops.py`（list/update/confirm/reopen）；`knowledge.py` 四路由；`tests/test_chunk_review.py` 5 用例全绿（Python312）。
- confirm：embed_texts + upsert_kb_chunk_vector → embedding_id + status=ready；published reopen→409。
- **下一刀**：Task4 LLM 切块清理或 Task5 端到端。

### 2026-07-24 15:19:25
- **计划就绪**：`docs/superpowers/plans/2026-07-24-chunk-review-denoise.md`（Task1 检索 published → Task7 CHECKPOINT）。
- 规格已批准；等待按 Task 实现或另开会话执行。

### 2026-07-24 15:14:44
- **设计**：切块预览 + 人工/大模型去噪（不做固定规则过滤）。
- 规格：`docs/superpowers/specs/2026-07-24-chunk-review-denoise-design.md`（待用户审阅）。
- 要点：`pending_review` → 确认 → `ready` → 发布；检索仅 `published`；合同 LLM 默认只建议。

### 2026-07-24 10:05:36
- **意图漏斗 P3**：`thresholds`（赞/踩微调 τ，夹紧+可选 Redis）；`lexicon`（从文档 person_name/标题抽人名）；L2 裸名命中；runtime 发消息前刷新词典；feedback API 钩子。
- 计划：`docs/superpowers/plans/2026-07-24-intent-funnel-p3.md`；设计 P0–P3 均已落地。
- **测**：thresholds + lexicon + 漏斗相关 **29 passed**。

### 2026-07-24 10:00:27
- **意图漏斗 P2**：L4 中置信 kb→`route_clarify`（是否查库）；runtime 下发卡；card-action 续跑 RAG/D14 或闲聊；`agent_pick` 可写回 `conversation.agent_id`。
- 计划：`docs/superpowers/plans/2026-07-24-intent-funnel-p2.md`。
- **测**：funnel_p2 + route_clarify_p2 + card_action 等 **8+** 通过；请假卡回归仍绿。

### 2026-07-24 09:55:20
- **意图漏斗 P1**：`classifier.py`（parse + Mock + LiteLLM）；`evaluate_intent_funnel_async`（L2≥0.75 短路，否则 L3→L4）；runtime 接入。
- 计划：`docs/superpowers/plans/2026-07-24-intent-funnel-p1.md`；设计状态已标 P1 落地。
- **测**：classifier + funnel p0/p1 + rag_trigger + leak_guard **22 passed**。
- **下一刀**：P2 `route_clarify` 卡（中置信带）。

### 2026-07-23 16:44:22
- **问题**：用户「在知识库中搜索赵世龙」得到虚构「山东高速董事长」等 6 条；公开信息不符（现任董事长为王其峰；000429 亦非山东高速）。
- **根因**：该问法未命中 L2（无「知识库中找」等前缀）→ `chitchat`；模型伪造 `function_calls.search` + tool_result。
- **修复**：显式 KB 口令扩「在知识库/知识库搜索…」；`parse_rag_query` 同步抽干净检索串；伪工具调用改为落库整段替换 + 流末【更正】。
- **测**：`test_intent_funnel_p0` + `test_tool_call_leak_guard` + `test_rag_trigger` **12 passed**。

### 2026-07-23 16:27:48
- **伪 web_search 卡死**：问「搜索赵世龙曾经在职的公司」意图落 chitchat，真模型把 `web_search` function_call 写进正文后停更。
- 修复：L2 增履历/就职公司规则 → `kb_lookup`；闲聊路径检测泄漏工具调用并补提示。
- 测：`test_intent_funnel_p0` 等 **13 passed**。若知识库无赵世龙，会走 D14 无引用（预期），而非假搜索。

### 2026-07-23 16:05:34
- **D14 无引用根因**：意图强制 `hr.resume`，旧简历未挂分类；soft 只去 metadata 仍空集 → 检索 0 命中。
- 修复：soft 二级放宽分类，仍空则退回权限内全文；entity_filter 仍可锁「唐亮」文档。
- 测：`test_kb_metadata_filter_p2` 等相关 **14 passed**。建议重启后端后重试「帮我看看唐亮是谁」。

### 2026-07-23 15:30:58
- **唯一用户权限**：`users.role`；`demo` → `platform_admin`，主部门 `dept_it`；登录写入 Session `role`/`department_id`。
- 测：`test_auth_login` **3 passed**；迁移 `0022_user_role`。

### 2026-07-23 15:21:22
- **知识库左侧列表可删**：`DELETE /api/v1/knowledge-bases/{id}`（仅超管软删）；连带软删下属文档并清切块/向量；列表排除已删。
- 前端：列表项「删除」确认；迁移 `0021_kb_deleted_at`。
- 测：`test_kb_delete` + 相关 **28 passed**。

### 2026-07-23 14:51:38
- **部门 KB + 多分类 Metadata P0–P2 落地**：设计/计划已确认并实现。
- P0：`owner_department_id`/`visibility`；创建自动写 `kb_permissions`；`GET /departments` 种子 HR/IT；旧库回填 public+employee；前端建库选部门/可见性。
- P1：`doc_categories` + `document_categories` 多对多；上传 `category_ids`+主分类；列表返回分类标签。
- P2：入库规则抽 Metadata；意图 `slots.filters`（如 hr.resume + person_name）；检索 soft 降级。
- 测：`test_kb_visibility_p0` + `test_doc_categories_p1` + `test_kb_metadata_filter_p2` 及相关回归 **58 passed**。
- **下一刀**：浏览器联调；P3 手工改 Metadata / Milvus 标量（可选）。

### 2026-07-23 14:27:00
- **检索串文档修复**：问「唐亮」时 hybrid 混入「尹庆为」简历；增加 `entity_filter`（抽人名 → 只在含该人名的文档内检索）。
- 测：`test_kb_entity_filter` + `test_kb_search` **9 passed**；联调「帮我看看唐亮是谁」citations 均来自唐亮文档。
- **意图漏斗 P0**：`app.modules.intent`（rules/funnel/decision）接入 `runtime`；关键词降级为规则特征。
- 自然问法「帮我看看唐亮是谁」→ `kb_lookup`；请假 → `ask_user_form`；其余 chitchat。
- 测：`test_intent_funnel_p0` + `test_rag_trigger` + citation **8 passed**。
- **下一刀**：P1 L3 LiteLLM 分类；P2 澄清卡。

### 2026-07-23 13:48:43
- **QA + 命中测试**：设计/计划落盘；API `qa-pairs` / `generate-qa` / `hit-test`；前端面板。
- 测：`test_kb_qa_hit` + 回归相关 **35 passed**。
- 约定：未达标展示明细并可改题/重生；**不**强制发布；切分策略后续。

### 2026-07-23 10:50:41
- **PDF 入库**：`decode_document_bytes` + `pypdf`；损坏 → `pdf_parse_error`（Celery 不重试）。
- 测试：`test_document_ingest` **7 passed**；相关 ingest **10 passed**。
- 联调：`doc_34277b4e1b8c4d32` 重入 → **ready**（5246 字 / 8 chunks）。
- 说明：当前为文本层抽取；扫描件/复杂版式后续按 PRD 接 MinerU。

### 2026-07-23 10:44:32
- **文档一直 processing**：旧 Celery worker（7/22）吞任务不落库；队列空但状态未更新。
- 清理全部 celery 后同步入库 `doc_34277b4e1b8c4d32` → **`failed` / `unsupported_extension`**（上传的是 PDF）。
- 已新起 `celery ... --pool=solo -n worker-kb@%h`。
- **结论**：当前入库只支持 txt/md/json；请用文本文件联调，或另开 PDF 解析任务。

### 2026-07-23 10:31:34
- **文档列表 500**：`Unknown column 'documents.fail_reason'`；库停在 `0017_agent_kbs`。
- 已执行 `alembic upgrade head` → `0018_document_fail_reason`；`GET /documents?kb_id=...` → **200**。

### 2026-07-23 10:28:17
- **知识库页 HTTP 405**：根因是本机 `:8000` 仍跑旧 uvicorn（OpenAPI 仅有 POST `/knowledge-bases`，无 GET）。
- 处理：新后端起在 **:8001**；`web/.env.local` 代理指向 8001；代理 `GET /api/v1/knowledge-bases` → **200**。
- **下一刀**：手动清 `:8000` 僵尸（PID 表现为 93100/67656 但 taskkill 找不到）后改回 8000。

### 2026-07-23 09:40:43
- **整支评审 MUST FIX**：`POST /documents` 鉴权；未软删恢复 409；列表 `viewer.is_platform_admin` + 前端权限只读；发布闸门中文；`documents.fail_reason`（Alembic `0018`）。
- 验证：`test_kb_admin_api` + `test_document_ingest` → **24 passed**；`test_document_publish_gate` → **4 passed**。
- 报告：`docs/superpowers/sdd/task-7-report.md`（Final-review fixes）。
- **下一刀**：MySQL `alembic upgrade head`；QA/hit_rate；浏览器联调。

### 2026-07-23 09:33:59
- kb-admin-closure **Task 7 完成**：KB 管理闭环第一刀 B 收口；回归 `test_kb_admin_api` + `test_kb_d13_search` + `test_document_ingest` **25 passed**；全量 pytest **153 passed**（8 warnings）。
- 报告：`docs/superpowers/sdd/task-7-report.md`
- **下一刀**：QA/hit_rate 流水线；或拖拽/URL 上传；浏览器联调 Task 6 清单。

### 2026-07-23 09:28:43
- kb-admin-closure **Task 6 完成**：重做 `web/src/app/knowledge/page.tsx`（左 KB + 新建；右上传/文档表/权限）；`processing` 2s 轮询 status；发布展示 422 message；软删恢复提示；`include_deleted=1`；`.kb-*` 样式。
- 报告：`docs/superpowers/sdd/task-6-report.md`
- **下一刀**：Task 7（CHECKPOINT + 回归）+ 浏览器联调 Task 6 清单。

### 2026-07-23 09:24:30
- kb-admin-closure **Task 5 完成**：`document_ops.soft_delete_document` / `recover_document`；`DELETE /documents/{id}` + `POST /documents/{id}/recover`；upload/publish 加 `_require_kb_read`；`tests/test_kb_admin_api.py` 15 passed。
- 报告：`docs/superpowers/sdd/task-5-report.md`
- **下一刀**：Task 6 重做 knowledge 前端页。

### 2026-07-23 09:20:04
- kb-admin-closure **Task 4 完成**：`GET /documents?kb_id=`（默认排除软删，`include_deleted=1` 含软删）+ `GET /documents/{id}/status`（`qa_count`/`hit_rate`）；鉴权复用 `_require_kb_read`；`tests/test_kb_admin_api.py` 11 passed。
- 报告：`docs/superpowers/sdd/task-4-report.md`
- **下一刀**：Task 5 软删/恢复 + upload/publish 鉴权。

### 2026-07-23 09:15:40
- kb-admin-closure **Task 3 完成**：`GET/PUT /knowledge-bases/{id}/permissions`；`_require_kb_read`；`tests/test_kb_admin_api.py` 8 passed。
- 报告：`docs/superpowers/sdd/task-3-report.md`
- **下一刀**：Task 4 documents list + status。

### 2026-07-23 09:09:16
- kb-admin-closure **Task 2 完成**：`GET /knowledge-bases`（超管全量 / 员工并集过滤）+ `POST` 仅超管；`tests/test_kb_admin_api.py` 5 passed。
- 报告：`docs/superpowers/sdd/task-2-report.md`
- **下一刀**：Task 3 permissions GET/PUT。

### 2026-07-23 09:03:40
- kb-admin-closure **Task 1 完成**：`user_can_access_kb` + `tests/test_kb_admin_api.py` 骨架（2 passed）。
- 报告：`docs/superpowers/sdd/task-1-report.md`
- **下一刀**：Task 2 `GET /knowledge-bases` + create 仅超管。

### 2026-07-22 17:31:09
- Spec 用户确认通过；已写实现计划 `docs/superpowers/plans/2026-07-22-kb-admin-closure.md`（Task 1–7，TDD）。
- **下一刀**：选 Subagent-Driven 或 Inline Execution 开跑。

### 2026-07-22 17:27:38
- Superpowers 头脑风暴完成：完善知识库需求 → 路径 D + 管理端 B + 方案 1。
- 规格：`docs/superpowers/specs/2026-07-22-kb-admin-closure-design.md`（全量索引 + 第一刀 API/页面/状态机）。
- 自检裁定：改权限仅超管；软删清向量；恢复不自动 re-ingest。
- **下一刀**：用户审阅 spec → writing-plans → 实现。

### 2026-07-22 17:01:23
- **根因**：`/chat` 历史消息加载后 `bottomRef.scrollIntoView()` 连带滚动 html/body，顶部 AppNav 被顶出视口。
- **修复**：改为只滚动 `.chat-stream`；复位文档 scrollTop；AppNav sticky + `overflow-anchor: none`。
- **验证**：刷新 `/chat`，等历史会话/消息加载后，顶栏应完整可见。
- **下一刀**：真 HTTP 工具 / `kg_ids` / Web 上传接线 `OssUploadUtil`。

### 2026-07-22 16:21:28
- 对齐 wish-pool `OssUploadUtil`：新增 `src/app/shared/oss_upload.py`（oss2）；支持图片/文档/PDF 等。
- Settings 增加 `OSS_PUBLIC_BASE_URL`；密钥仅环境变量；`tests/test_oss_upload_util.py` + 既有 OSS 测 **12 passed**。
- **勿**把 AccessKey 明文写入仓库；聊天中暴露的密钥应轮换。
- **下一刀**：真 HTTP 工具 / `kg_ids` / 演示权限种子；或 Web 上传接线 `OssUploadUtil`。

### 2026-07-22 16:10:56
- 近线拓扑拉起：`profile full` → etcd / minio-milvus / milvus；`.env` 写 `MILVUS_URI=http://127.0.0.1:19530`。
- 真 Embedding Docker（st + 本地 bge-small-zh）仍健康；冒烟 upsert → 集合 `za_kb_chunks_v2`（512 维）。
- 主 API 重启；本机 Celery worker + beat 已起。
- **下一刀**：真 HTTP 工具 / `kg_ids` / 演示权限种子。

### 2026-07-22 15:26:39
- Hybrid + 独立 `services/embed_rerank`：契约 `/v1/embeddings` `/v1/rerank`；主仓 HTTP client；`embed_texts` 优先服务。
- `search_kb_chunks`：稠密∥本地 BM25→RRF（BM25 同分打破）→可选 Rerank；Milvus `za_kb_chunks_v2`（含 content）；Compose `profile: embed`。
- 全量 pytest **130 passed**。
- **下一刀**：真 HTTP 工具 / `kg_ids` / 演示权限种子 / 起 embed 验真模型。

### 2026-07-22 15:04:39
- D13：检索前并集过滤；无 `KbPermission` = 拒绝；`platform_admin` 豁免。
- `list_accessible_kb_ids` + `run_kb_lookup`/`messages` 传 Actor；测试 `test_kb_d13_search.py`。
- 全量 pytest **122 passed**。
- **注意**：演示前须给 KB 写授权，否则非管理员搜不到。
- **下一刀**：Hybrid / 真 HTTP 工具 / `kg_ids`。

### 2026-07-22 14:52:35
- Agent `kb_ids`：表 `agent_kbs`（0017）；创建/GET/PUT；`resolve_kb_ids_for_agent` 过滤检索。
- 全量 pytest **117 passed**；本机 `alembic upgrade` → `0017_agent_kbs`。
- **下一刀**：D13 并集进检索；或 Hybrid；或真 HTTP 工具；或 `kg_ids`。

### 2026-07-22 14:40:00
- Alembic：`upgrade head` → `0016_document_chunks`（本机 MySQL）。
- `kb_lookup` / 「查知识库」接 `search_kb_chunks` + citation；D14「无引用」仍拒答。
- 新增 `knowledge/lookup.py`、`execute_builtin_tool_async`；规格 `2026-07-22-kb-lookup-search-design.md`。
- 全量 pytest **113 passed**。
- **下一刀**：Agent `kb_ids` 落库过滤；或 Hybrid；或真 HTTP 工具。

### 2026-07-22 12:45:00
- vector-harden Task 6：CHECKPOINT 收口；全量 `pytest -q` → **106 passed**（1 warning）。
- 自检：`runtime.py` 仍请求内同步 `extract + persist`；`search_kb_chunks` 未接 `runtime` / `kb_lookup` 桩。
- 启动备忘补 Milvus profile full 命令。
- 报告：`docs/superpowers/sdd-vector/task-6-report.md`。
- **下一刀**：`kb_lookup` 接稠密检索 / Hybrid。

### 2026-07-22 12:40:00
- vector-harden Task 5：`search_kb_chunks`（Milvus 优先 + MySQL 本地余弦回落）；返回 chunk_id/document_id/kb_id/score/content。
- 测：`test_kb_search.py` 5 passed；KB 相关 16 passed。
- 报告：`docs/superpowers/sdd-vector/task-5-report.md`。
- **未改** `runtime` / `kb_lookup`。
- **下一刀**：Task 6 CHECKPOINT + 全量回归。

### 2026-07-22 12:32:35
- vector-harden Task 4：`chunk_text` + ingest 写 `document_chunks` + best-effort `upsert_kb_chunk_vector`（`za_kb_chunks`）；空文本→failed/empty_text。
- 测：`test_kb_chunk_ingest.py` + `test_document_ingest.py` → **10 passed**。
- 报告：`docs/superpowers/sdd-vector/task-4-report.md`。
- **下一刀**：Task 5 `search_kb_chunks`。

### 2026-07-22 12:25:00
- vector-harden Task 2：`DELETE /memories/{id}` 与 `POST /clear` 软删 commit 后 best-effort 调 `delete_memory_vector`。
- 测：`test_user_memory.py` 5 passed（含 2 条新向量删除 mock 用例）。
- 报告：`docs/superpowers/sdd-vector/task-2-report.md`。
- **下一刀**：Task 3 KB ingest 向量写入。

### 2026-07-22 12:10:00
- Final-review：OSS `put_object` 始终镜像 `.data/oss`；ingest 重试耗尽→`failed`；expire_approvals 对齐 `_run_async` 线程桥。
- 测：覆盖 11 passed；全量 **91 passed**（1 warning）。
- 报告：`docs/superpowers/sdd/task-5-report.md`（Final-review fixes）、`docs/superpowers/sdd/final-fix-report.md`。
- **下一刀**：真 HTTP 工具 / KB 向量入库。

### 2026-07-22 12:00:00
- Task 5：Compose 追加 `worker`/`beat`（build `deploy/Dockerfile`，覆盖 rabbitmq/redis/mysql 主机名）；CHECKPOINT 启动备忘补本机 Celery 命令。
- celery-harden Tasks 1–5 收口；记忆同步热路径未改。
- 测：全量 `pytest -q` → **89 passed**（1 warning）；记忆相关用例仍绿。
- 报告：`docs/superpowers/sdd/task-5-report.md`。
- **下一刀**：真 HTTP 工具 / KB 向量入库。

### 2026-07-22 11:50:00
- Task 3：`celery_app` include ingest/extract；`ingest_document_task` 调 `ingest_document_sync`；无 expire/beat。
- 测：`test_upload_eager_reaches_ready` + `test_document_ingest`/`test_web_upload_ingest`/`test_oss_get` → 8 passed。
- 报告：`docs/superpowers/sdd/task-3-report.md`。
- **下一刀**：Task 4 expire_approvals + beat_schedule。

### 2026-07-22 11:29:47
- 修记忆失忆：`MOCK_EXTERNAL=false` 时原只 `Celery.delay`，无 Worker 则不落库。
- 改为请求内同步 `extract + persist`；提问卡路径也抽取；测试 `80 passed`。

### 2026-07-22 11:20:59
- Token UI：流式 `stream_options.include_usage`；Mock 启发式；多轮 FC usage 累加。
- 迁移 `0015` 会话累计；`message_end` + 会话详情 `usage_summary`/`context`；前端顶栏展示。
- 测试 `79 passed`。
- **下一刀**：真 HTTP 工具；或审计用量。

### 2026-07-22 11:06:03
- 多轮技能 FC：`skill_fc_max_rounds` 默认 5；循环 tools→回灌；`ask_user` 仍立即出卡。
- 触顶 `path=skill_fc_max_rounds`；`message_end.fc_rounds`；Mock「多轮工具」两轮。
- 测试 `76 passed`。
- **下一刀**：真 HTTP 工具；或审计/用量。

### 2026-07-22 10:57:10
- 审批超时：默认 `approval_timeout_minutes=30`；创建写 `expires_at`；列表/决定前惰性过期。
- 过期 → `cancelled` + 通知；workflow 实例 cancel；`POST /approvals/expire-due`。
- 前端 cancelled 筛选 + 截止时间；测试 `75 passed`。
- **下一刀**：多轮 FC；或真 HTTP 工具。

### 2026-07-22 10:45:36
- Prompt 变量：迁移 `0014`；`variables_schema_json` / `variables_json` / `prompt_template_versions`。
- 插值 `{{var}}`（未知保留）；Agent 缺必填 422；发布快照；rollback→draft。
- 前端模板 schema + Agent 变量表单；测试 `72 passed`。
- **下一刀**：审批超时；或多轮 FC / 真 HTTP。

### 2026-07-22 10:39:23
- 技能层 FC：内置 `ask_user`/`echo`/`kb_lookup`；`load_agent_openai_tools`；`chat_completion_with_tools`。
- Agent+技能工具走一轮 FC；`ask_user`→卡；其它→执行回灌；SSE `tool_call`；无工具仍保留请假关键字捷径。
- 测试 `67 passed`。
- **下一刀**：Prompt 变量插值；或审批超时；或多轮/真 HTTP。

### 2026-07-22 10:31:11
- 审批：表 `approval_tasks` + 迁移 `0013`；`GET/POST /approvals`、`POST .../approve|reject`。
- 工作流进入 `waiting_human` 自动建待办；通过 → resume，驳回 → cancel；通知 requester。
- 前端 `/approvals`；测试 `63 passed`。
- **下一刀**：真工具 FC；或 Prompt 变量插值。

### 2026-07-22 10:25:28
- Prompt 模板：表 + 迁移 `0012`；CRUD/发布；`agents.prompt_template_id`；对话注入 published 模板。
- 前端 `/prompts`；Agent 下拉选模板；测试 `59 passed`。
- **下一刀**：审批 / 真 FC / 变量插值。

### 2026-07-22 10:20:30
- Skill Prompt 注入：`build_agent_skill_system_prompt`；对话 system 顺序：技能 → 记忆 → 历史 → user。
- Mock 回复含 `【已注入技能指令】`；测试 `57 passed`。
- **下一刀**：Prompt 模板；或审批；或真 FC。

### 2026-07-22 10:17:48
- F5.4：`agents.fallback_model_ids` + 迁移 `0011`；`resolve_agent_model_chain`；`stream_chat_completion_with_fallback`。
- 对话/重试按 Agent 主备链调用；`message_end.model_used`；Mock 下 `fail*` 模型名模拟失败。
- 前端 Agent 创建可填备用模型；测试 `56 passed`。
- **下一刀**：Skill Prompt 注入；或 Prompt 模板 / 审批。

### 2026-07-22 10:11:46
- 站内通知：表 `notifications` + 迁移 `0010`；`GET/POST /notifications`、`POST .../read`；`create_notification`。
- 前端 `/notifications`（演示发送 + 标已读）；测试 `53 passed`。
- **下一刀**：`/approvals`；或工作流通知节点调用 `create_notification`。

### 2026-07-22 10:04:34
- Summary+Milvus MVP：阈值触发 `summary`；`embed_texts`（Mock 伪向量 / LiteLLM）；cosine >0.9 跳过；`persist_extracted_memories`；Milvus best-effort（需 `MILVUS_URI` 且非 Mock）。
- 依赖：`pymilvus`；配置项 `memory_summary_char_threshold` / `memory_dedupe_threshold` / `litellm_embed_model`。
- 测试：`51 passed`。
- **下一刀**：真 Milvus profile 联调；或通知/审批；冷热分层仍不做。

### 2026-07-22 09:40:33
- LLM JSON 记忆抽取：设计/计划已批；`parse_memory_json` + `extract_memories_from_transcript`；`chat_completion_json`。
- Mock 走规则；真模型走 LiteLLM 非流式 JSON；坏 JSON/异常回落规则；Celery/runtime 共用。
- 测试：`47 passed`。
- **下一刀**：通知/审批；或 summary；Milvus 暂缓。

### 2026-07-22 09:34:39
- Superpowers：方案 A 消息重试；设计 `specs/2026-07-22-message-retry-design.md`；计划 `plans/2026-07-22-message-retry.md`。
- TDD：`POST /messages/{id}/retry` SSE；保留旧回复；`meta_json.retry_of`；前端「重试」+ SSE 代理。
- 测试：`41 passed`。
- **下一刀**：LLM JSON 记忆抽取；或通知/审批。

### 2026-07-22 09:29:05
- F1.7：`message_feedbacks` + 迁移 `0009`；`POST /messages/{id}/feedback`（up/down + comment，可更新）。
- 会话详情返回 `feedbacks`；对话页助手消息「有用/无用」，踩可填原因。
- 测试：`39 passed`；Alembic → `0009_message_feedbacks`。
- **下一刀**：`/messages/{id}/retry`；或 LLM JSON 抽取。

### 2026-07-22 09:22:58
- Agent：`memory_access` / `can_modify_memory` + 迁移 `0008`；创建/列表 API 与前端表单。
- 对话：按会话 `agent_id` 解析策略注入；默认 Agent 禁止自动写记忆；系统对话（无 Agent）仍平台抽取。
- 记忆导出：`GET /users/me/memories/export` + 前端导出按钮；聊天页可选 Agent。
- 测试：`37 passed`；Alembic → `0008_agent_memory_access`。
- **下一刀**：联调 memory_access；或 F1.7 反馈 / LLM JSON 抽取（Milvus 仍暂缓）。

### 2026-07-22 09:13:26
- 用户记忆 MVP：`user_memories` + 迁移 `0007`；Redis 短期 TTL 2h（失败回落进程内）。
- API：`/api/v1/users/me/memories` CRUD + clear；对话 `runtime` 注入 System Prompt；结束后 Mock 同步抽取 / 生产 Celery `extract_memories`。
- 前端：`/memories` + 导航「我的记忆」。
- 测试：`34 passed`（含 `test_user_memory`）；`alembic upgrade` → `0007_user_memories`。
- 刻意暂缓：Milvus/Embedding 去重、冷热分层、Agent `memory_access` 字段（现默认 `all`）。
- **下一刀**：浏览器联调抽取与注入；可选 Agent.memory_access / LLM JSON 抽取。

### 2026-07-22 08:57:02
- 切页后聊天消失：根因是对话页仅用 React state。
- 新增 `GET /api/v1/conversations/{id}`（消息 + pending_cards）；前端 `sessionStorage` 记会话并在挂载时恢复；提供「新对话」。
- **下一刀**：浏览器验证 对话→知识库→对话 历史仍在。

### 2026-07-22 08:51:45
- 用户要求「帮我更新」：已停旧前端并重启 `npm run dev`；后端 :8000 仍健康。
- 请浏览器强刷后验证 `/chat` 流式输出。

### 2026-07-22 08:49:34
- 用户反馈聊天非流式：根因是 Next `rewrites` 代理会缓冲完整 SSE。
- 新增 `web/src/app/api/v1/messages/send/route.ts` 与 `card-action/route.ts` 透传 `upstream.body`。
- 对话页 `content_delta` 使用 `flushSync` 强制同步渲染。
- **须重启前端 dev server** 后验证。

### 2026-07-21 17:29:36
- 确认使用**国内 MiniMax**（`api.minimaxi.com`，非 `api.minimax.io`）。
- `.env` / Compose / `litellm/config.yaml` 增加 `MINIMAX_API_BASE`；litellm force-recreate。
- 先前 401 根因：默认打国际站；切换国内后鉴权通过。
- M3 默认会产出 `reasoning_content` 占满短 `max_tokens`；客户端已 `thinking.disabled` + `max_tokens=2048`，并兼容流式 reasoning 回落。
- 验证：`POST /v1/chat/completions` 返回 `content=OK`。
- **下一刀**：浏览器联调系统对话 SSE。

### 2026-07-21 17:23:26
- 新增迁移 `0006_kb_agents_skills`；`alembic.ini` 去掉非 ASCII 以免 Windows GBK 读失败。
- `alembic upgrade head` 成功 → `0006_kb_agents_skills`。
- 后端/前端已常驻；`/health` `/api/v1/runtime` `/login` 正常。
- 真模型联调失败：LiteLLM 日志 `authorized_error / invalid api key (2049)`。
- 流式路径已加 LLM 上游错误收口（`message_end.status=error`），避免裸 500 打断。
- **下一刀**：换有效 MiniMax Key → recreate litellm → 浏览器验证对话。

### 2026-07-21 17:14:10
- MVP Task 0–9 + D14 + Web（login/chat/knowledge/agents）+ LiteLLM 客户端已落地。
- Compose 数据改绑 `D:\dockers\zeroagent`；已 `up -d mysql redis rabbitmq litellm`。
- `.env` 已 `MOCK_EXTERNAL=false`；LiteLLM 配置含 `MiniMax-M3`；Compose 注入 `MINIMAX_API_KEY`（密钥仅在本地 `.env`）。
- **未做**：对 MySQL 跑 Alembic；后端/前端常驻进程；litellm healthcheck 镜像内 wget 可能失败导致 unhealthy（接口可用则忽略或改探针）。
- **下一刀**：Alembic upgrade + 启后端/前端联调。
