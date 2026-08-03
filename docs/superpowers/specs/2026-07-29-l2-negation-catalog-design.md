# L2 否定门禁与关键词目录（DB + Redis）设计

> 状态：已确认（P0 含完整管理 CRUD）  
> 日期：2026-07-29  
> 作者：赵振明  
> 修订说明：关键词由「代码 Catalog」改为 **MySQL 持久化 + 启动加载 Redis + CRUD 双写同步**；管理 API 本轮一并交付。

## 1. 要解决什么

1. 否定句「我没让你总结赵世龙的简历」被 L2 任务词「总结」误判为 `doc_analyze`。  
2. L2 口令散落在 `rules.py`，难运维、难热更新。  

本规格：

- L2 **否定/纠正门禁** + 匹配顺序（行为不变自上一版）  
- L2 关键词 **持久化与缓存架构**（本修订核心）  
- 不确定仍走既有澄清卡  

## 2. 产品裁定

| 项 | 裁定 |
|---|---|
| 明确纠正/否定 | L2 高置信 → `chitchat`；禁止 `doc_analyze` / `kb_lookup` |
| 明确正向指令 | 保持现 L2 行为 |
| 不确定 | L4 → 澄清卡（复用 `kb_confirm`）；确认后再执行 |
| 关键词真相源 | **MySQL**（单租户，无 `tenant_id`） |
| 运行时读取 | **优先 Redis**；禁止每轮打库 |
| 启动 | 服务启动从 MySQL **全量加载**到 Redis |
| 增删改查 | **先写 MySQL，再刷新 Redis**（双写同步）；失败有明确错误与回滚策略 |
| 管理权限 | 仅 `platform_admin` / `super_admin`（部门管理员不可改） |
| 方案 | 否定门禁 = A；词表存储 = **DB+Redis**（取代纯代码 Catalog 作为真相源） |

## 3. 不做的事

- 不为否定病例堆模糊正则猜意图  
- 不允管理员任意写入无界正则（防 ReDoS）；P0 仅 **字面短语 / contains**  
- 不引入多租户、OpenIM、外部 A2A  
- P0 不新造 `clarify_kind`；复用现澄清卡  

## 4. 数据模型

### 4.1 表 `intent_l2_keywords`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | VARCHAR(32) PK | `l2k_` + ULID |
| `category` | VARCHAR(32) NOT NULL | 见下枚举 |
| `phrase` | VARCHAR(128) NOT NULL | 口令/关键词原文 |
| `match_mode` | ENUM('contains','equals','prefix') | P0 默认 `contains` |
| `enabled` | TINYINT(1) DEFAULT 1 | 启用开关 |
| `priority` | INT DEFAULT 100 | 同 category 内排序（小优先） |
| `remark` | VARCHAR(255) NULL | 运维备注 |
| `deleted_at` | DATETIME NULL | 软删 |
| `created_at` / `updated_at` | DATETIME | UTC |

**category 枚举（P0）：**

| category | 用途 | 命中后意图 |
|---|---|---|
| `explicit_kb` | 显式查库口令 | `kb_lookup` |
| `leave` | 请假 | `ask_user_form` |
| `meta_reply` | 元追问 + **用户纠正否定** | `chitchat` |
| `doc_dump` / `doc_summarize` / `doc_critique` | 文档任务词 | `doc_analyze` + task |
| `person_search_verb` | 「搜索/查一下」等动作词（裸人名结构仍由代码组装） | 与裸人名组合 → `kb_lookup` |

唯一约束建议：`UNIQUE(category, phrase)`（未软删范围可用业务层保证，或生成列）。

### 4.2 种子数据

Alembic 迁移 + seed：把现行 `rules.py` 口令迁入表（含「总结」「我没让你」「不要」等纠正短语）。  
代码内保留 **DEFAULT_SEED** 常量，仅用于：空库兜底、单测、Redis/DB 皆不可用时的只读降级。

## 5. 缓存架构

```text
MySQL (intent_l2_keywords)
        │ 启动 / CRUD 后
        ▼
Redis key: za:intent:l2_catalog:v1
  - JSON：按 category → [{phrase, match_mode, priority}, ...]
  - 另存 version: za:intent:l2_catalog:ver （单调递增）
        │ 匹配时读取
        ▼
l2_catalog_service.get_catalog()
        │
        ▼
match_l2_rules()
```

### 5.1 启动加载

应用 lifespan / 启动钩子：

1. `SELECT` 全部 `enabled=1 AND deleted_at IS NULL`  
2. 序列化写入 Redis（覆盖）  
3. `INCR` version  
4. 失败：打错误日志；进程加载 DEFAULT_SEED 到内存，标记 `degraded=true`（可观测）

### 5.2 运行时读取

1. 读 Redis；命中则用  
2. Redis miss / 不可用 → 读 MySQL → 回填 Redis → 返回  
3. MySQL 也失败 → DEFAULT_SEED（降级，禁止静默空词表导致全交 L3 行为漂移不可控——至少保留纠正与总结种子）

**禁止**：`match_l2_rules` 热路径直接 `SELECT`（除 miss 回源一次）。

### 5.3 CRUD 同步（硬约束）

| 操作 | 顺序 |
|---|---|
| Create / Update / Soft-delete / Enable | ① 事务写 MySQL ② 成功后 **全量刷新** Redis（或按 category 局部刷新，P0 用全量更简单） ③ bump version |
| 读列表 | 可走 DB（管理端）或 Redis（调试）；管理端列表以 DB 为准 |

写库成功、刷缓存失败：返回 **部分成功/告警**（HTTP 503 或业务码），并记日志；提供 `POST .../reload-cache` 运维补偿。  
**不以缓存为准回写库**。

### 5.4 多实例

各 API 实例匹配时读共享 Redis，无需本机长驻脏缓存。  
若引入进程内短缓存：必须绑 `ver`，ver 变化则失效（P1 可选；P0 可每次读 Redis JSON，词表很小）。

## 6. API（管理端）

前缀建议：`/api/v1/intent/l2-keywords`  
鉴权：`platform_admin` / `super_admin`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 分页列表（DB） |
| POST | `/` | 新增 → 同步 Redis |
| PATCH | `/{id}` | 改 phrase/enabled/priority → 同步 Redis |
| DELETE | `/{id}` | 软删 → 同步 Redis |
| POST | `/reload-cache` | 强制 DB→Redis 全量重载 |

请求校验：`phrase` 长度、category 枚举、禁止空串；`match_mode` 仅允许白名单。

文档：同步更新 `docs/01-产品需求/API接口规范.md` 与 `数据库表结构.md`。

## 7. 匹配顺序（`match_l2_rules`）

与上一版一致，词表来源改为 `get_catalog()`：

1. 空句 → `None`  
2. `explicit_kb`  
3. `leave`  
4. `meta_reply`（含纠正否定）→ `chitchat`  
5. `doc_*` → `doc_analyze`  
6. 词典人名 / `person_search_verb`+裸人名 → `kb_lookup`  
7. 未命中 → `None` → L3 → L4 澄清  

## 8. 模块边界

| 模块 | 职责 |
|---|---|
| `models` + migration | `intent_l2_keywords` |
| `intent/l2_catalog_store.py` | DB 读写、seed、reload→Redis |
| `intent/l2_catalog_cache.py` | Redis get/set/version |
| `intent/rules.py` | 只消费 `get_catalog()` 做匹配 |
| `api/v1/intent_l2_keywords.py` | 管理 CRUD |
| `main` lifespan | 启动 `reload_l2_catalog()` |
| `classifier.py` | L3 prompt 防御条款（纠正→chitchat） |

原「纯代码 `l2_catalog.py` 作真相源」改为：**DEFAULT_SEED + DB 真相源**；代码常量不再是生产唯一来源。

## 9. 风险与应对

| 风险 | 应对 |
|---|---|
| Redis 宕机 | miss 回源 DB；双挂则 DEFAULT_SEED + 降级标记 |
| 刷缓存失败导致脏读 | CRUD 返回告警 + `/reload-cache`；监控 version |
| 管理员写危险模式 | P0 禁自定义 regex；仅短语 |
| 空表无种子 | 迁移强制 seed；启动检测空表自动 seed |
| 与文档不同步 | 改表/API 必须改白名单文档 |

## 10. 测试要点

1. 「我没让你总结赵世龙的简历」→ `chitchat`  
2. 「总结赵世龙的简历」→ `doc_analyze`  
3. 启动加载：DB 有词 → Redis 有 key  
4. CRUD：改库后 Redis 内容一致  
5. Redis 不可用时仍能匹配（回源/种子）  
6. 非平台管理员 CRUD → 403  
7. 中置信澄清卡回归不破  

## 11. 验收

- 否定句不再总结简历  
- 改关键词：写库即热更新（经 Redis），无需改代码发版（短语类）  
- 启动必加载；CRUD 必同步  
- 文档与表、API 对齐  

## 12. 实现顺序

1. 表结构文档 + migration + seed  
2. store/cache + 启动加载（TDD）  
3. `rules` 消费缓存 + 否定门禁用例  
4. 管理 API + 权限  
5. L3 prompt 防御  
6. API/库表文档 + CHECKPOINT  

## 13. 与现有规格关系

- 对齐 RouteResolver（L2 高确定性、澄清走卡）  
- 对齐阈值模块「可选 Redis」习惯，但本词表 **MySQL 为权威**  
- 废止上一版「仅 `l2_catalog.py` 作唯一词表源」的说法；该文件若保留，仅作 DEFAULT_SEED  
