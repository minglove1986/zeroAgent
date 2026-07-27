# Review package Task 5 (NO_GIT)

### deploy/docker-compose.yml
`
# =============================================================================
# zeroAgent 本地依赖（开发拓扑）
# 数据目录默认绑定到 D:/dockers/zeroagent（可用 DOCKER_DATA_DIR 覆盖）
# OpenIM 不在此文件中；LLM 走 LiteLLM；无 Key 时 MOCK_EXTERNAL=true
# =============================================================================

name: zeroagent

services:
  mysql:
    image: mysql:8.0
    container_name: zeroagent-mysql
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-rootpass}
      MYSQL_DATABASE: ${MYSQL_DATABASE:-zeroagent}
      MYSQL_USER: ${MYSQL_USER:-zeroagent}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-zeropass}
    ports:
      - "3306:3306"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/mysql:/var/lib/mysql
      - ./mysql/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-uroot", "-p${MYSQL_ROOT_PASSWORD:-rootpass}"]
      interval: 10s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    container_name: zeroagent-redis
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD:-redispass}
    ports:
      - "6379:6379"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD:-redispass}", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    container_name: zeroagent-rabbitmq
    restart: unless-stopped
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_USER:-zeroagent}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD:-rabbitpass}
    ports:
      - "5672:5672"
      - "15672:15672"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/rabbitmq:/var/lib/rabbitmq
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 15s
      timeout: 10s
      retries: 8

  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    container_name: zeroagent-litellm
    restart: unless-stopped
    ports:
      - "4000:4000"
    environment:
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY:-sk-litellm-dev}
      MINIMAX_API_KEY: ${MINIMAX_API_KEY:-}
      MINIMAX_API_BASE: ${MINIMAX_API_BASE:-https://api.minimaxi.com/v1}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
    volumes:
      - ./litellm/config.yaml:/app/config.yaml:ro
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:4000/health/liveliness"]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 30s

  # 可选：无线上 OSS 时启动
  minio-biz:
    image: minio/minio:latest
    container_name: zeroagent-minio
    profiles: ["minio"]
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/minio:/data

  neo4j:
    image: neo4j:5
    container_name: zeroagent-neo4j
    profiles: ["full"]
    environment:
      NEO4J_AUTH: ${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-neopass}
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/neo4j:/data

  etcd:
    image: quay.io/coreos/etcd:v3.5.16
    container_name: zeroagent-etcd
    profiles: ["full"]
    environment:
      ETCD_AUTO_COMPACTION_MODE: revision
      ETCD_AUTO_COMPACTION_RETENTION: "1000"
      ETCD_QUOTA_BACKEND_BYTES: "4294967296"
      ETCD_SNAPSHOT_COUNT: "50000"
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/etcd:/etcd

  minio-milvus:
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    container_name: zeroagent-minio-milvus
    profiles: ["full"]
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    command: minio server /minio_data --console-address ":9001"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/milvus-minio:/minio_data

  milvus:
    image: milvusdb/milvus:v2.4.15
    container_name: zeroagent-milvus
    profiles: ["full"]
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio-milvus:9000
    ports:
      - "19530:19530"
      - "9091:9091"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/milvus:/var/lib/milvus
    depends_on:
      - etcd
      - minio-milvus

  worker:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: zeroagent-worker
    restart: unless-stopped
    env_file: .env
    environment:
      PYTHONPATH: /app/src
      # 容器内连 compose 网络主机名；若 .env 写 127.0.0.1 需覆盖：
      RABBITMQ_URL: amqp://${RABBITMQ_USER:-zeroagent}:${RABBITMQ_PASSWORD:-rabbitpass}@rabbitmq:5672//
      REDIS_URL: redis://:${REDIS_PASSWORD:-redispass}@redis:6379/0
      DATABASE_URL: mysql+aiomysql://${MYSQL_USER:-zeroagent}:${MYSQL_PASSWORD:-zeropass}@mysql:3306/${MYSQL_DATABASE:-zeroagent}
      MOCK_EXTERNAL: ${MOCK_EXTERNAL:-false}
    command: celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
    depends_on:
      rabbitmq:
        condition: service_healthy
      redis:
        condition: service_healthy
      mysql:
        condition: service_healthy

  beat:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: zeroagent-beat
    restart: unless-stopped
    env_file: .env
    environment:
      PYTHONPATH: /app/src
      RABBITMQ_URL: amqp://${RABBITMQ_USER:-zeroagent}:${RABBITMQ_PASSWORD:-rabbitpass}@rabbitmq:5672//
      REDIS_URL: redis://:${REDIS_PASSWORD:-redispass}@redis:6379/0
      DATABASE_URL: mysql+aiomysql://${MYSQL_USER:-zeroagent}:${MYSQL_PASSWORD:-zeropass}@mysql:3306/${MYSQL_DATABASE:-zeroagent}
      MOCK_EXTERNAL: ${MOCK_EXTERNAL:-false}
    command: celery -A app.workers.celery_app beat --loglevel=info
    depends_on:
      rabbitmq:
        condition: service_healthy
      redis:
        condition: service_healthy
      mysql:
        condition: service_healthy

`

### docs/superpowers/CHECKPOINT.md
`
# zeroAgent 研发断点（防上下文中断）

> **用途**：会话突然中断或新开上下文时，Agent/人类先读本文件再继续。  
> **维护规则**：每次有实质推进后 **必须更新**——顶部「当前断点」整段覆盖；底部「断点日志」**追加一条**（勿删历史）。  
> **禁止**：写入任何 API Key / 密码明文。

---

## 当前断点（覆盖写）

| 项 | 值 |
|---|---|
| 更新时间 | 2026-07-22 12:00:00（东八区） |
| 仓库 | `d:\HermesWork\zeroAgent` |
| 计划 | celery-harden（Tasks 1–5 DONE） |
| Docker 数据根 | `D:\dockers\zeroagent` |
| Alembic | `0015_conversation_tokens`（head） |
| 后端 | Celery worker/beat/入库 ready；`expire_approvals` + `beat_schedule` |
| 前端 | `/chat` 用量条 |
| MiniMax | 国内 `https://api.minimaxi.com/v1` |
| 下一步（优先） | 真 HTTP 工具 / KB 向量入库 |

### 新会话开场（复制）

```text
继续 zeroAgent。先读 docs/superpowers/CHECKPOINT.md「当前断点」。
```

### 启动命令备忘

```powershell
# 后端（必须用本机 Python3.12）
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m uvicorn app.main:app --app-dir src --reload --host 127.0.0.1 --port 8000

# 前端
cd D:\HermesWork\zeroAgent\web
npm run dev

# 依赖
cd D:\HermesWork\zeroAgent\deploy
docker compose --env-file .env up -d mysql redis rabbitmq litellm

# Celery Worker（本机）
cd D:\HermesWork\zeroAgent
$env:PYTHONPATH="src"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m celery -A app.workers.celery_app worker --loglevel=info

# Celery Beat（本机）
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m celery -A app.workers.celery_app beat --loglevel=info
```

---

## 断点日志（只追加）

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

`
