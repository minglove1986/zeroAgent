# 知识库切块预览与人工/大模型去噪（设计）

> **日期**：2026-07-24  
> **状态**：已落地（2026-07-24；计划 Task1–7 完成）  
> **用户裁定**：先不做固定规则过滤；只做切块预览，人工或大模型干预后再确认入库可检索。  
> **权威对齐**：单租户；Web 上传 → OSS → Celery；检索须 citation（D14）；LLM 只经 LiteLLM；发布门禁（D7）仍在确认之后。

## 1. 目标（人话）

上传文档后，系统先切成块给你看。你可以手改，也可以让大模型帮清噪声；你点「确认」之后，这些块才参与对话检索。  
**本刀不做**自动正则/固定规则去噪。

## 2. 非目标

- 入库默认规则过滤（`…~~` 等写死/配置化规则引擎）——明确不做  
- 多种切分策略 / SmartChunker  
- 运营在后台自助编写任意正则  
- 改发布门禁阈值（仍 `qa≥5` 且 `hit_rate≥0.8`）  
- OCR/扫描件专项增强  

## 3. 状态与检索边界

### 3.1 文档状态

在现有 `draft | processing | ready | published | failed` 上增加 **`pending_review`**：

| 状态 | 含义 | 对话检索 |
|---|---|---|
| `processing` | 解析/切块中 | 否 |
| `pending_review` | 已有切块，待预览/编辑/确认 | **否** |
| `ready` | 切块已确认，可生成问答/命中测 | **否**（与「仅 published 可检索」对齐，见下） |
| `published` | 过发布门禁 | **是** |
| `failed` | 失败 | 否 |

**本刀硬裁定**：`search_kb_chunks` / `kb_lookup` **只检索 `status=published` 且未软删** 的文档切块。  
（修正现状：当前按 KB 拉全量 chunk，`ready` 也会进检索；本刀一并收口，避免未审内容进对话。）

**兼容**：已存在的 `ready`/`published` 历史文档——迁移时：

- 已是 `published`：不变，可检索  
- 已是 `ready` 且已有 chunks：保持 `ready`（不可检索，直到用户走发布）；**不**强制打回 `pending_review`，避免存量全部卡住  
- 若产品希望存量 `ready` 仍可临时检索：本刀**不**做例外；统一以 published 为准（与发布门禁一致）

> 若联调发现「以前 ready 就能搜」的习惯被打破：前端提示「请先确认切块并发布」。属预期行为。

### 3.2 入库流水线变更

```
上传 → OSS → Celery
  → decode
  → chunk_text
  → 写入 document_chunks
  →（本刀）可先不写向量，或写向量但不参与检索（因 status 过滤）
  → status = pending_review
用户预览 / 手改 / LLM 建议并应用
  → POST confirm
  → 对变更块重算 embedding 并 upsert
  → status = ready
（既有）生成问答 → 命中测 → publish → published
```

**推荐实现**：`pending_review` 阶段仍写 MySQL chunks；**embedding 可在 confirm 时统一做**（省无效向量）。若实现简单起见 ingest 仍 embed，必须以 status 过滤检索，且编辑后必须重 embed。

## 4. API

鉴权同现有文档写权限（`_require_kb_read` / 写权限与知识库管理一致）。

| 方法 | 路径 | 行为 |
|---|---|---|
| `GET` | `/api/v1/documents/{id}/chunks` | 按 `ordinal` 返回切块列表：`id, ordinal, content, content_len, updated?` |
| `PUT` | `/api/v1/documents/{id}/chunks/{chunk_id}` | body `{ content }`；仅 `pending_review`（或已确认后再次「打回审」见 4.1）；写库；标记该块 dirty |
| `POST` | `/api/v1/documents/{id}/chunks/llm-clean` | body 见下；大模型去噪建议或直接应用 |
| `POST` | `/api/v1/documents/{id}/chunks/confirm` | 校验仍有 chunks；对 dirty/全部块 embedding；`pending_review` → `ready` |

### 4.1 `llm-clean` 请求

```json
{
  "chunk_ids": ["chk_xxx"],
  "scope": "selected | all",
  "mode": "suggest | apply"
}
```

- `suggest`（默认）：返回 `{ chunk_id, original, proposed }`，**不写库**  
- `apply`：写入 proposed 并标 dirty；合同类（见 §5）默认拒绝 `apply`，除非 body `force_apply=true` 且调用方为有写权限用户  

LLM：只经 LiteLLM；`MOCK_EXTERNAL` 时用规则桩（例如去掉连续重复的长 token 行）便于单测。

### 4.2 打回再审（可选，本刀建议做）

`POST /documents/{id}/chunks/reopen`：`ready` → `pending_review`（未 published 时）；已 `published` 须先下架/取消发布策略——**本刀规定**：已 published 不允许 reopen，返回 409，避免检索中文档被改脏。

## 5. 大模型去噪策略

- **通用 prompt**：删除明显非正文噪声（重复无意义串、抽取乱码）；**禁止改写事实**（姓名、金额、日期、条款编号、甲乙方、电话邮箱）。  
- **简历等**：允许 `suggest` / `apply`。  
- **合同**（文档挂载分类 schema 含 contract/政策类，或标题/metadata 标明合同）：默认仅 `suggest`；`apply` 需 `force_apply`。  
- 无分类时：一律默认 `suggest`，降低误伤。

## 6. 前端（`/knowledge` 文档详情）

1. 文档为 `pending_review`：展示切块列表（可折叠长文本），每块可编辑保存。  
2. 工具条：「大模型清理（预览）」→ 对比 original/proposed → 用户勾选应用；「确认切块」。  
3. `ready` 后走既有「生成问答 / 命中 / 发布」。  
4. 列表列增加状态文案：待审切块 / 已确认 / 已发布。

## 7. 数据与迁移

- Alembic：`documents.status` 允许 `pending_review`（若 DB 为 ENUM 则 ALTER；模型已是 String 则主要是约定 + 查询过滤）。  
- `document_chunks`：可选增加 `updated_at`、`dirty`；若不想加列，confirm 时对全文重 embed 亦可（文档不大时可接受）。  
- **禁止** `tenant_id`。

## 8. 测试要点

1. ingest 结束后 `pending_review`，`kb_lookup` / `search_kb_chunks` **搜不到**该文档。  
2. 手改 chunk → confirm → `ready` → 仍搜不到 → publish 后能搜到，且内容为修改后文本。  
3. `llm-clean` suggest 不写库；apply 写库；合同默认不可 apply。  
4. Mock LiteLLM 路径单测稳定。  
5. 已 published 文档 reopen → 409。

## 9. 验收

- 上传赵世龙类脏 PDF：预览可见垃圾串；人工或 LLM 清掉后确认并发布；对话检索答案中不再出现该垃圾串。  
- 合同样例：LLM 默认只出建议，不自动落库。  
- 无固定过滤规则模块上线。

## 10. 后续（明确不在本刀）

- 配置化/规则引擎自动去噪  
- 切块预览中调整切分大小并重切  
- published 文档的在线热修流程  
