# 知识库管理闭环设计（规格全量 + 第一刀管理端 B）

@author 赵振明
@date 2026-07-22 17:27:38

> **路径**：需求规格先行 → 补齐管理 API → 重做 `/knowledge`（方案 1，已确认）。  
> **权威对齐**：PRD 场景 2 / §12.3 / §13.2–13.4；第十六章 D4、D7、D13、D14；API §7；库表 `knowledge_bases` / `kb_permissions` / `documents` / `document_qa_pairs`。  
> **禁止依据**：PRD 附录 A；OpenIM / OSS 事件入库旧方案。

---

## 1. 目标与分层

| 层 | 内容 |
|---|---|
| **规格（全量）** | 写清 KB 管理产品边界与后续切片，避免实现与 PRD 继续分裂 |
| **实现第一刀（B）** | 管理闭环：KB 列表/创建 → 文档列表 → 上传与状态进度 → 发布 → 软删/恢复 → 权限读写 |

**成功标准（第一刀）**

1. 超管可建库并出现在列表  
2. 配置权限后，专家仅见有权库并可管文档  
3. 上传后可见 `processing` → `ready` / `failed`  
4. 发布不达标返回可读的 `42201` 原因  
5. 软删后列表可查、检索不可查；可恢复  

---

## 2. 硬约束（不改）

- 单租户，禁止 `tenant_id`  
- 文件：**Web 上传 → OSS → Celery**（非 OSS 事件；不做 OpenIM）  
- KB 权限：**并集**（D13）；无权限库不参与检索  
- Agent 配置面仅 `skill_ids` + `kb_ids` + `kg_ids` + `callable_agent_ids`  
- RAG 路径强制 citation（D14）——**本刀不改检索/拒展逻辑**  
- 超管建库；业务专家维护授权范围内文档（D4）  
- 发布门槛：问答对默认 ≥5 且召回率 ≥80%（D7 / 现有 `evaluate_publish_gate`）  

---

## 3. 全量需求索引（规格层）

以下为产品全量能力地图；标注实现归属。

| 能力 | PRD/裁定 | 第一刀 | 后续 |
|---|---|---|---|
| 超管建库、按部门归属 | F2.2 / D4 | ✅ 建库+列表；**不扩** `department_id` 列（归属用权限行表达） | 部门筛选/归属字段 |
| 专家维护授权文档 | D4 | ✅ | — |
| 权限 user/department/role 并集 | F2.8 / D13 | ✅ GET/PUT permissions | — |
| Web 上传（表单） | F2.1 / D25 | ✅ 沿用 `content_b64` 上传 | STS 直传 |
| 拖拽上传 | §12.3 | ❌ | 下一刀 UI |
| URL 抓取 | F2.7 | ❌ | 另排期 |
| 分阶段进度（解析/Embedding/入库） | §12.3 | ✅ 轮询 status；细 `stage` 有则展示，无则文案映射 | Celery 细粒度 stage |
| 文档列表筛选排序 | §12.3 | ✅ 按库；基础状态筛选 | 多列排序 |
| 自动命中测试 + 发布门槛 | F2.4 / D7 | ✅ 调用现有 publish gate；**不增强算法** | 上传时写 QA + 真 hit_rate 流水线 |
| 文档版本 | F2.5 | ❌ | 另排期 |
| 软删 30 天可恢复 + 立即不可查 | F2.6 | ✅ 软删/恢复 + 向量清理（复用现有 delete 向量能力） | 到期硬删定时任务 |
| 批量导入/重试 | API §7 | ❌ | 另排期 |
| 父子分块 / Hybrid / KG | 场景 2 约束 | ❌（检索侧已有另规） | — |

---

## 4. 第一刀：页面信息架构（`/knowledge`）

单页三区（不新开子路由）：

```
AppNav
左：KB 列表（搜索；超管「新建」）
右：当前库
  · 库名 +「权限」入口
  · 上传区（文件 + 标题）
  · 文档表（状态 / hit_rate / qa_count / 操作）
  · 权限面板（抽屉或页内折叠）
```

**角色可见性**

| 角色 | 行为 |
|---|---|
| `platform_admin`（超管） | 新建 KB、见全部库、文档全操作、**读写权限** |
| 业务专家（有权） | 无新建；仅并集有权库；上传/发布/软删/恢复；**只读**权限面板（改权限仅超管，对齐「全局策略」） |
| 其它 | 空态「无知识库管理权限」（不展示操作） |

**主路径**：进页拉列表 → 选库拉文档 → 上传 → 轮询 status → 发布 / 软删 / 恢复 → 权限保存。

---

## 5. 文档状态机（实现口径）

PRD §13.2 产品语义为「草稿 → 发布」。实现沿用现码状态字，映射如下：

| status / 标记 | 产品语义 | 允许操作 |
|---|---|---|
| `processing` | 入库中 | 仅查看进度 |
| `ready` | 草稿（可走发布门槛） | 发布、软删 |
| `failed` | 入库失败 | 软删；提示 reason；可重新上传新文档 |
| `published` | 已发布 | 软删 |
| `deleted_at != null` | 已软删（向量与 chunks 已清） | 恢复（仅元数据）；恢复后须重新入库才可检索 |

**发布门槛**（已有，保持）：

- `qa_count < 5` → 失败原因 `qa_pairs`  
- `hit_rate is None` 或 `< 0.8` → 失败原因 `hit_rate`  
- HTTP `422` + 业务码 `42201`  

**第一刀 QA / hit_rate 约定**

- 上传接口**不强制**一次带齐 `qa_pairs`（与当前 `POST /documents/upload` 一致）  
- 无 QA 或无 `hit_rate` 时，发布按钮可点，但必须展示门槛错误（不静默失败）  
- **不做**本刀命中测试算法改造；真 hit_rate 流水线归后续切片  

---

## 6. API 契约（第一刀必补）

对齐 `docs/01-产品需求/API接口规范.md` §7。

### 6.1 已有（保留）

| 方法 | 路径 |
|---|---|
| POST | `/api/v1/knowledge-bases` |
| POST | `/api/v1/documents/upload` |
| POST | `/api/v1/documents/{id}/publish` |
| POST | `/api/v1/documents`（内部/联调创建，管理页可不暴露） |

### 6.2 新增 / 补齐

| 方法 | 路径 | 行为要点 |
|---|---|---|
| GET | `/knowledge-bases` | 返回 `{ items: [{ id, name, description, created_at }] }`；非超管按并集过滤；**0 条权限行的库对非超管不可见**（与检索侧 D13 一致） |
| GET | `/knowledge-bases/{id}/permissions` | `{ items: [{ subject_type, subject_id }] }` |
| PUT | `/knowledge-bases/{id}/permissions` | body `{ items: [...] }` **全量替换**；`subject_type ∈ user\|department\|role`；**仅超管** |
| GET | `/documents?kb_id=&include_deleted=0\|1` | 文档摘要：id/title/status/hit_rate/qa_count/deleted_at/updated_at |
| GET | `/documents/{id}/status` | `{ status, stage?, hit_rate, qa_count, reason? }`；`stage` 可选 |
| DELETE | `/documents/{id}` | 软删：写 `deleted_at`；删 `document_chunks`（若存在）并 **立即**按 document 清向量 |
| POST | `/documents/{id}/recover` | 清 `deleted_at`；状态置 `ready`；**第一刀不自动重跑 ingest**——管理端提示「已恢复元数据，需重新上传/入库后才能检索」（避免假可搜） |

**鉴权**

- 创建 KB、PUT permissions：仅超管  
- 读 KB/文档、上传/发布/软删/恢复、GET permissions：超管 **或** 对该 KB 并集有权  
- 一律走现有 Actor / Cookie Session，禁止硬编码密钥  

**进度轮询**：前端对 `processing` 每 2s 拉 status，直至离开该状态；超时仅提示可刷新，不锁死页面。

---

## 7. 数据流

```
Web /knowledge
  → GET /knowledge-bases
  → GET /documents?kb_id=
  → POST /documents/upload → OSS → DB(processing) → Celery ingest
       → ready | failed
  → POST .../publish → published | 42201
  → DELETE ... → soft delete + vector purge
  → POST .../recover
  → GET/PUT .../permissions
```

与对话检索关系：软删立即不可查；权限并集已在 `lookup`/`permissions` 模块——管理页写入 permissions 后，检索侧无需改算法即可生效。

---

## 8. 错误处理

| 场景 | 行为 |
|---|---|
| 无权 | 403 或空列表；操作按钮禁用 |
| 上传失败 | 顶部/行内错误，不插入假成功行 |
| `failed` | 展示 `reason`（如 `unsupported_extension` / `oss_missing`） |
| 发布门槛 | `42201` + `qa_pairs` / `hit_rate` 中文提示 |
| 轮询仍 processing | 「仍处理中，可稍后刷新」 |

---

## 9. 测试与验收

**后端单测（必做）**

- GET KB：无权限行 → 非超管不可见；有 user/dept/role 授权 → 可见；超管全见  
- PUT permissions 全量替换  
- GET documents / status 字段  
- 软删写 `deleted_at` 且触发向量删除（Mock）  
- recover 清 `deleted_at`  
- publish 门槛回归（已有 gate 测保留）  

**前端**：联调清单覆盖 §1 成功标准；本刀不做重型 E2E。

---

## 10. 明确不做（第一刀）

- 拖拽上传、URL 抓取、批量导入/重试  
- 文档版本 UI、STS 直传  
- 命中测试算法 / 自动写 hit_rate 增强  
- 改 D14 citation、改 Hybrid/KG  
- 多租户、OpenIM、外部 A2A  

---

## 11. 实现顺序（供 writing-plans）

1. 补齐 GET KB / permissions / documents / status / soft-delete / recover + 单测  
2. 重做 `web/src/app/knowledge/page.tsx`（列表+上传+轮询+发布+删恢复+权限面板）  
3. 联调验收清单打勾  
4. 更新 `CHECKPOINT.md`  

后续候选切片：QA 录入与真 hit_rate、拖拽/URL、版本、批量导入、到期硬删。

---

## 12. 决策记录

| 项 | 结论 |
|---|---|
| 完善路径 | D：规格 → 实现；第一刀选管理端 B |
| 工程路径 | 方案 1：规格 → API → 页面 |
| 状态字 | 沿用 `processing/ready/failed/published` + `deleted_at` |
| 上传与 QA | 上传不强制 QA；发布强制门槛 |
| 恢复后向量 | 软删已清 chunk/向量；恢复只还原元数据为 `ready`，需重新入库才可检索 |
| 改权限 | 仅超管；专家只读权限面板 |
