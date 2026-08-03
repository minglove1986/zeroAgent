# 记忆抽取白名单与异步触发设计

> 状态：已确认（本轮实现；无定期扫描；配置统一 MySQL+Redis）  
> 日期：2026-07-29  
> 作者：赵振明  

## 1. 要解决什么

1. 开放式 LLM 抽取自造 `memory_key`（如 `person_of_interest` / `search_intent`），把 KB 第三人写进用户长期记忆，污染新会话。  
2. `_enqueue_extract` 在对话请求内 **同步 await LLM**，拖住 SSE/`busy`，用户感觉「要等总结完才能继续聊」。  
3. Celery `extract_memories` 已存在但主路径未用。  

本规格：**白名单 Catalog（DB+管理 API）+ 仅三种异步触发（显式 / 空闲 / 窗口）**；去掉定期扫描。

## 2. 产品裁定

| 项 | 裁定 |
|---|---|
| 抽取范围 | 仅白名单 `field_key`；非法 key **丢弃** |
| Catalog 真相源 | **MySQL**（单租户，无 `tenant_id`） |
| 运行时读取 | **只读 Redis**；热路径禁止每轮打库 |
| 启动 | 服务启动从 MySQL **全量加载**到 Redis |
| 管理员改 Catalog | **先写 MySQL，再刷新 Redis**；失败可观测 + `/reload-cache` |
| 触发（仅三种） | **显式记住**（实时异步）+ **空闲超时**（质量）+ **滑动窗口**（容量） |
| 定期扫描 | **不做**（本规格明确废止） |
| 对话主路径 | **禁止** await 抽取；只 fire-and-forget 入队或登记待抽 |
| 队列 | 既有 Celery + RabbitMQ；失败重试 ≤3 |
| 纠正/元追问/纯 KB 检索轮 | **不入队**抽取 |
| 脏数据 | 迁移或启动时：归档/软删不在白名单内的历史 auto 记忆（可选工具脚本） |
| 方案 | 白名单填值（方案 A）+ 三触发异步 |

### 2.1 工程约定：频繁访问的配置类模块（以后统一照此）

凡「管理员可改、运行时高频读」的设置/词表/白名单（含本规格、L2 关键词等）：

1. **MySQL = 唯一真相源**  
2. **进程启动** → 全量加载 Redis（可附 version key）  
3. **业务热路径** → 只从 Redis 读；miss 才回源 DB 并回填  
4. **管理写路径** → 事务写库成功后再刷缓存；刷失败告警并提供强制 reload  
5. **降级** → Redis/DB 皆不可用时可用代码内 DEFAULT_SEED（只读），并打 `degraded` 标记  

禁止：热路径每请求 `SELECT` 配置表；禁止以 Redis 回写 MySQL。

## 3. 不做的事

- 不做 30 分钟定期批扫  
- 不在 API 请求内同步调用抽取 LLM  
- 不允管理员配置任意开放 schema（只允许枚举 category + 固定字段元数据）  
- 不引入多租户 / OpenIM / 外部 A2A  
- 不改短期 Redis 短记忆职责（仍按会话 TTL）  

## 4. 白名单数据模型

### 4.1 表 `memory_extract_fields`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | VARCHAR(32) PK | `mef_` + ULID |
| `category` | VARCHAR(16) NOT NULL | `fact` \| `preference` \| `summary` |
| `field_key` | VARCHAR(64) NOT NULL | 落库 `user_memories.memory_key` |
| `label` | VARCHAR(64) NOT NULL | 管理端展示（如「用户爱好」） |
| `description` | VARCHAR(255) NULL | 写入抽取 prompt 的说明 |
| `enabled` | TINYINT(1) DEFAULT 1 | |
| `priority` | INT DEFAULT 100 | |
| `remark` | VARCHAR(255) NULL | |
| `deleted_at` | DATETIME NULL | 软删 |
| `created_at` / `updated_at` | DATETIME | |

唯一：`(category, field_key)` 在未软删范围内业务保证。

### 4.2 种子（对齐 PRD 15.1，可增）

| category | field_key | label |
|---|---|---|
| fact | `display_name` | 姓名 |
| fact | `department` | 部门 |
| fact | `position` | 岗位 |
| fact | `hire_date` | 入职时间 |
| fact | `contact` | 联系方式 |
| fact | `hobby` | 爱好（示例：管理员可再加同类） |
| preference | `brevity` | 简洁度 |
| preference | `format` | 格式（Markdown/纯文本） |
| preference | `language` | 语言 |
| summary | `ongoing_task` | 进行中任务 |
| summary | `conv_digest` | 对话要点（仅窗口/空闲触发可写） |

### 4.3 缓存（硬约束，对齐 §2.1）

| 步骤 | 行为 |
|---|---|
| Redis key | `za:memory:extract_fields:v1`；version：`za:memory:extract_fields:ver` |
| 启动 | lifespan：`SELECT` 启用未删行 → 序列化覆盖写入 Redis → bump ver |
| 热读 | Worker / 抽取 prompt / 注入过滤：**只调 `get_extract_fields_catalog()`（内部读 Redis）** |
| miss | 回源 MySQL → 回填 Redis → 返回；禁止静默空目录导致「全不抽」无告警 |
| 管理 CRUD | 写库成功 → **全量刷 Redis** → bump ver；刷失败返回告警码 + 支持 `POST .../reload-cache` |
| 降级 | 双挂 → DEFAULT_SEED + `degraded=true`（可观测） |

管理端列表可走 DB（便于分页/含停用项）；**运行时匹配与抽取一律走缓存。**

## 5. 管理 API

前缀：`/api/v1/memory/extract-fields`  
权限：`platform_admin` / `super_admin`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 列表 |
| POST | `/` | 新增（如爱好） |
| PATCH | `/{id}` | 改 label/description/enabled/priority |
| DELETE | `/{id}` | 软删 |
| POST | `/reload-cache` | 强制刷 Redis |

文档同步：`API接口规范.md`、`数据库表结构.md`。

## 6. 抽取逻辑

1. 加载启用白名单 → 写入 system prompt（仅允许这些 key + description）。  
2. LLM 输出 JSON 数组；`parse` 后 **只保留白名单 key**。  
3. `persist_extracted_memories`：同 key 覆盖或 embedding 去重（沿用现逻辑）。  
4. Mock：规则抽取亦须映射到白名单 key，禁止开放 key。  
5. 废除开放式 `_EXTRACT_SYSTEM`；废除无白名单的 `_maybe_append_summary` 任意摘要（仅允许 `conv_digest`/`ongoing_task` 且来自白名单启用项）。  

## 7. 三种触发（本轮全部实现）

### 7.1 显式记住（实时性）

- 检测用户话含高确定性口令：`请记住` / `记住：` / `以后请` / `帮我记一下` 等（规则表可进 seed 或代码常量）。  
- 对话 SSE **结束后** `extract_memories_task.delay(...)`，**不 await**。  
- 仅投递本轮 transcript（或本轮+近 2 条短记忆）。  

### 7.2 空闲超时（质量）

- 每轮用户消息更新 Redis：`za:memextract:idle:{conversation_id}` = now，TTL = idle+缓冲。  
- Celery 倒计时任务或「延迟队列」：空闲 **默认 3 分钟**（可配置 `MEMORY_EXTRACT_IDLE_SECONDS`）无新消息 → Worker 拉取该会话短记忆全文抽取。  
- 新消息到达则取消/覆盖旧延迟任务（防抖）。  

### 7.3 滑动窗口（容量）

- 短记忆 turns ≥ 阈值（默认与 `SHORT_MAX_TURNS` 对齐，或独立 `MEMORY_EXTRACT_WINDOW_TURNS=12`）时，异步投递一次抽取。  
- 投递后打标记 `za:memextract:window:{conversation_id}` 防抖，避免每多一轮连投；窗口滑动后再允许下一次。  

### 7.4 主路径改造

```text
message_end 即将返回
  → 若本轮可抽：登记/delay Celery（毫秒级）
  → 立即结束响应（前端 busy 释放）
  → Worker 异步：白名单抽 → 落库
```

删除/改造 `runtime._enqueue_extract` 的同步 await；改为 `schedule_memory_extract(...)`。

### 7.5 跳过条件

下列任一成立则 **不调度**：

- `allow_memory_write=false`  
- 本轮 route 为 `meta_reply` / 用户纠正  
- 本轮仅为 `kb_lookup`/`doc_analyze` 且用户未显式「记住」  
- transcript 为空  

## 8. 注入侧（防再污染）

- `build_memory_system_prompt`：仅注入 `memory_key ∈ 当前启用白名单` 的条目（或至少过滤已知污染 key 列表 + 白名单）。  
- 历史脏数据：提供一次性清理（软删 `source=auto` 且 key 不在白名单）。  

## 9. 模块边界

| 模块 | 职责 |
|---|---|
| `models` + migration | `memory_extract_fields` + seed |
| `memory/extract_catalog_*` | DB/Redis/CRUD 辅助 |
| `memory/service.py` | 白名单约束抽取；去掉同步开放抽 |
| `memory/extract_scheduler.py` | 显式/空闲/窗口调度 |
| `workers/tasks/extract_memories.py` | Celery 执行体（增强读白名单） |
| `api/v1/memory_extract_fields.py` | 管理 API |
| `runtime.py` / handlers | 改调度，禁止 await 抽 |
| 文档 / CHECKPOINT | 对齐 |

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| Worker 未启，记忆变「慢」或不落 | 健康检查/日志；文档要求 `-WithCelery`；显式记住可提示「已后台记录」 |
| 空闲任务与窗口重复抽 | 同一会话短时间去重锁；embedding 去重 |
| 管理员乱加敏感字段 | 权限限平台管理员；审计 remark |
| 下一轮立刻要用新记忆 | 接受秒～分钟级延迟；显式记住优先调度 |

## 11. 测试要点

1. 开放 key（如 `person_of_interest`）被过滤，不落库  
2. 启用 `hobby` 后，含爱好的话语可抽到 `hobby`  
3. `_enqueue_extract` / 调度函数 **不 await LLM**（单测 mock delay 被调用）  
4. 纠正句 / kb_lookup 不入队  
5. 窗口满触发 delay；空闲逻辑可用假时钟单测  
6. 管理 API 非平台管理员 403；CRUD 刷缓存  
7. 注入 prompt 不含白名单外旧脏 key（过滤后）  

## 12. 验收

- 对话结束前端可立即再问，不等抽取  
- 管理员加「爱好」后，符合条件的交流能异步写入该字段  
- 新会话不再因「查过唐亮」而胡乱道歉/串人  
- 无定期扫描任务  

## 13. 实现顺序（本轮）

1. 表 + seed + 缓存 + 管理 API  
2. 抽取白名单门禁 + 注入过滤  
3. 调度器三触发 + 改 runtime 去同步 await  
4. Celery 任务对齐白名单  
5. 脏数据清理脚本/迁移可选步骤  
6. 单测 + CHECKPOINT + API/库表文档  

## 14. 与现有规格关系

- 对齐 PRD 十五章类型范围；**收紧** 15.2「LLM 随意识别」为白名单填值  
- 对齐 15.9 异步队列；**不实现**其中「每 30 分钟定期」  
- 与 L2 Catalog（DB+Redis+CRUD）治理模式同构  
- 与来源边界：第三人资料不得进用户 fact  
