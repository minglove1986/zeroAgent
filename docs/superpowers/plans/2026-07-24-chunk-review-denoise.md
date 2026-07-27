# 切块预览与人工/LLM 去噪 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.  
> **规格：** `docs/superpowers/specs/2026-07-24-chunk-review-denoise-design.md`（已批准）

**Goal:** 文档入库后进入切块待审；支持列表/手改/LLM 建议或应用；确认后 `ready`；仅 `published` 文档参与对话检索。

**Architecture:** `ingest` 写 chunks 后置 `pending_review`（confirm 前可不写向量）；`search_kb_chunks` join `documents` 过滤 `status=published`；新增 `chunk_ops` / `chunk_llm_clean`；API 挂 `knowledge.py`；前端 `/knowledge` 增加切块面板。

**Tech Stack:** FastAPI、SQLAlchemy async、LiteLLM（`MOCK_EXTERNAL` 桩）、现有 Milvus upsert、Next.js。

## Global Constraints

- 单租户；禁止 `tenant_id`
- **不做**固定规则/配置化自动去噪模块
- LLM 只经 LiteLLM；单测 Mock
- 注释 `@author 赵振明` + 东八区实时时间
- 发布门禁不变（D7）
- 检索仅 `published`（规格硬裁定）

## File map

| 路径 | 职责 |
|---|---|
| `src/app/modules/knowledge/search.py` | 只搜 published 文档的 chunks |
| `src/app/modules/knowledge/ingest.py` | 结束态 `pending_review`；跳过 embedding（改到 confirm） |
| `src/app/modules/knowledge/chunk_ops.py` | list / update / confirm / reopen |
| `src/app/modules/knowledge/chunk_llm_clean.py` | suggest/apply；合同保护 |
| `src/app/api/v1/knowledge.py` | 新路由 |
| `web/src/app/knowledge/page.tsx` | 切块预览 UI |
| `tests/test_chunk_review.py` | 本刀主测 |
| 既有 `tests/test_document_ingest.py` 等 | 期望 status / 可检索性对齐 |

---

### Task 1：检索仅 published

**Files:**
- Modify: `src/app/modules/knowledge/search.py`
- Modify: `tests/test_kb_lookup_search.py`、`tests/test_kb_d13_search.py`（seed 改为 `published`）
- Test: `tests/test_chunk_review.py`（新建，先写本 Task 用例）

**Interfaces:**
- Consumes: `DocumentChunk`、`Document`
- Produces: `search_kb_chunks` 行为变更——未 published / 已软删文档的 chunk 永不返回

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chunk_review.py
@pytest.mark.asyncio
async def test_search_skips_pending_and_ready(db_session_with_kb):
    # 同 kb 下：doc_a status=pending_review content含「待审独有词」
    # doc_b status=ready content含「已确认独有词」
    # doc_c status=published content含「已发布独有词」
    hits = await search_kb_chunks(db=db, kb_ids=[kb_id], query="独有词", top_k=10)
    ids = {h["document_id"] for h in hits}
    assert "doc_c" in ids
    assert "doc_a" not in ids
    assert "doc_b" not in ids
```

- [ ] **Step 2: 跑测确认失败**

Run: `pytest tests/test_chunk_review.py::test_search_skips_pending_and_ready -v`  
Expected: FAIL（当前会命中 ready/pending）

- [ ] **Step 3: 实现过滤**

在 `search_kb_chunks` 拉 rows 时 join `Document`：

```python
stmt = (
    select(DocumentChunk)
    .join(Document, Document.id == DocumentChunk.document_id)
    .where(
        DocumentChunk.kb_id.in_(kb_ids),
        Document.status == "published",
        Document.deleted_at.is_(None),
    )
)
```

`document_ids` 预过滤仍保留，且同样受 published 约束。

- [ ] **Step 4: 修正既有 seed**

凡断言「能搜到」的测试，将 Document.status 改为 `"published"`。

- [ ] **Step 5: 跑测通过**

Run: `pytest tests/test_chunk_review.py::test_search_skips_pending_and_ready tests/test_kb_lookup_search.py tests/test_kb_d13_search.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**（仅当用户要求提交时执行）

```bash
git add src/app/modules/knowledge/search.py tests/test_chunk_review.py tests/test_kb_lookup_search.py tests/test_kb_d13_search.py
git commit -m "fix(kb): only search published document chunks"
```

---

### Task 2：ingest → pending_review（confirm 前不 embed）

**Files:**
- Modify: `src/app/modules/knowledge/ingest.py`
- Modify: `tests/test_document_ingest.py`、相关 upload/eager 测
- Test: `tests/test_chunk_review.py`

**Interfaces:**
- Consumes: `chunk_text`、`decode_document_bytes`
- Produces: `ingest_document_sync` → `status="pending_review"`；写 `document_chunks`；**不**调用 `embed_texts` / `upsert_kb_chunk_vector`（`embedding_id` 可空）

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_ingest_ends_pending_review_without_vectors(db, monkeypatch):
    # mock get_object / embed；若 embed 被调用则 fail
    result = await ingest_document_sync(db, document_id)
    assert result["status"] == "pending_review"
    doc = await db.get(Document, document_id)
    assert doc.status == "pending_review"
    chunks = (await db.execute(select(DocumentChunk).where(...))).scalars().all()
    assert chunks and all(c.embedding_id is None for c in chunks)
```

- [ ] **Step 2: 跑测确认失败**

Run: `pytest tests/test_chunk_review.py::test_ingest_ends_pending_review_without_vectors -v`  
Expected: FAIL（当前 ready + 有 embedding）

- [ ] **Step 3: 改 ingest**

- 去掉（或跳过）`embed_texts` / `upsert_kb_chunk_vector` 循环中的向量写入  
- `DocumentChunk.embedding_id = None`  
- `doc.status = "pending_review"`  
- return `status: "pending_review"`

- [ ] **Step 4: 修既有 ingest 断言** `ready` → `pending_review`

- [ ] **Step 5: 跑测通过**

Run: `pytest tests/test_chunk_review.py::test_ingest_ends_pending_review_without_vectors tests/test_document_ingest.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**（用户要求时）

```bash
git commit -m "feat(kb): ingest stops at pending_review without embedding"
```

---

### Task 3：切块 list / update / confirm / reopen

**Files:**
- Create: `src/app/modules/knowledge/chunk_ops.py`
- Modify: `src/app/api/v1/knowledge.py`
- Test: `tests/test_chunk_review.py`

**Interfaces:**
- Produces:
  - `async def list_chunks(db, document_id) -> list[dict]`
  - `async def update_chunk(db, document_id, chunk_id, content: str) -> dict` — 仅 `pending_review`
  - `async def confirm_chunks(db, document_id) -> dict` — embed 全部 chunks → upsert → `ready`
  - `async def reopen_chunks(db, document_id) -> dict` — `ready`→`pending_review`；`published`→ 冲突错误

- [ ] **Step 1: API 契约测试（RED）**

```python
async def test_list_update_confirm_flow(client, auth_headers, seeded_pending_doc):
    r = await client.get(f"/api/v1/documents/{doc_id}/chunks", headers=auth_headers)
    assert r.status_code == 200
    chunks = r.json()["data"]["items"]
    assert len(chunks) >= 1
    cid = chunks[0]["id"]
    r2 = await client.put(
        f"/api/v1/documents/{doc_id}/chunks/{cid}",
        headers=auth_headers,
        json={"content": "清洗后的正文不含噪音串"},
    )
    assert r2.status_code == 200
    with patch embed upsert:
        r3 = await client.post(f"/api/v1/documents/{doc_id}/chunks/confirm", headers=auth_headers)
    assert r3.status_code == 200
    assert r3.json()["data"]["status"] == "ready"
```

```python
async def test_reopen_published_409(client, auth_headers, published_doc):
    r = await client.post(f"/api/v1/documents/{doc_id}/chunks/reopen", headers=auth_headers)
    assert r.status_code == 409
```

- [ ] **Step 2: 实现 `chunk_ops.py`**

要点：
- `update_chunk`：空 content → 422；非 `pending_review` → 409  
- `confirm_chunks`：无 chunks → 422；`embed_texts` 全量；写 `embedding_id`；`status=ready`  
- `reopen_chunks`：`published` → raise 冲突；`ready` → `pending_review`（可不删向量，因检索已按 status 过滤）

- [ ] **Step 3: 挂路由**（鉴权同 `_require_kb_read` / 写操作与现有文档写一致）

| 方法 | 路径 |
|---|---|
| GET | `/documents/{id}/chunks` |
| PUT | `/documents/{id}/chunks/{chunk_id}` |
| POST | `/documents/{id}/chunks/confirm` |
| POST | `/documents/{id}/chunks/reopen` |

- [ ] **Step 4: 跑测通过**

Run: `pytest tests/test_chunk_review.py -k "list_update_confirm or reopen" -v`  
Expected: PASS

- [ ] **Step 5: Commit**（用户要求时）

```bash
git commit -m "feat(kb): chunk list/update/confirm/reopen APIs"
```

---

### Task 4：LLM 切块清理（suggest / apply）

**Files:**
- Create: `src/app/modules/knowledge/chunk_llm_clean.py`
- Modify: `src/app/api/v1/knowledge.py`
- Test: `tests/test_chunk_review.py`

**Interfaces:**
- Produces: `async def llm_clean_chunks(db, document_id, *, chunk_ids, scope, mode, force_apply) -> dict`
- 合同判定 `is_contract_like(doc, schema_codes)`：标题含「合同」或 `schema_code in {"schema_policy"}` 且标题/metadata 含合同语义；无分类 → 非合同但仍默认 suggest 优先（apply 允许，规格：无分类默认 suggest 模式默认值即可）

- [ ] **Step 1: RED**

```python
async def test_llm_clean_suggest_does_not_write(client, pending_doc_with_noise):
    r = await client.post(..., json={"scope": "all", "mode": "suggest"})
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert items[0]["original"] != items[0]["proposed"] or "~~" not in items[0]["proposed"]
    # DB content 仍为 original

async def test_llm_clean_apply_contract_requires_force(client, contract_pending_doc):
    r = await client.post(..., json={"scope": "all", "mode": "apply"})
    assert r.status_code == 409  # 或业务码约定
    r2 = await client.post(..., json={"scope": "all", "mode": "apply", "force_apply": True})
    assert r2.status_code == 200
```

- [ ] **Step 2: Mock 桩**

`MOCK_EXTERNAL=true` 时：对每块删除「连续重复且匹配 `^[0-9a-fA-F]{8,}[A-Za-z0-9_-]+~~$` 的行」（仅测试桩，**不是**生产自动过滤模块）。

真模型：`chat_completion` / JSON，prompt 强调只删噪声、不改金额电话条款。

- [ ] **Step 3: 路由** `POST /documents/{id}/chunks/llm-clean`

- [ ] **Step 4: 跑测通过**

Run: `pytest tests/test_chunk_review.py -k llm_clean -v`  
Expected: PASS

- [ ] **Step 5: Commit**（用户要求时）

```bash
git commit -m "feat(kb): LLM chunk clean suggest/apply with contract guard"
```

---

### Task 5：端到端 — 改块后发布可检索

**Files:**
- Test: `tests/test_chunk_review.py`
- 必要时微调 `publish` 前置（仍要求 ready + QA；本刀不改门禁逻辑）

- [ ] **Step 1: RED/GREEN 集成测**

```python
async def test_edited_chunk_searchable_only_after_publish(...):
    # ingest → pending_review
    # PUT 去掉噪音
    # confirm → ready
    # search 仍空
    # 写入足够 QA + mock hit_rate 或走 generate-qa（Mock）
    # publish → published
    # search 命中且 snippet 无噪音串
```

- [ ] **Step 2: 跑全量相关测**

Run: `pytest tests/test_chunk_review.py tests/test_document_ingest.py tests/test_kb_lookup_search.py tests/test_kb_qa_hit.py -v`  
Expected: PASS（若 `test_kb_qa_hit` 依赖 ready 可生成问答，保持；检索类已改 published）

- [ ] **Step 3: Commit**（用户要求时）

---

### Task 6：前端切块预览

**Files:**
- Modify: `web/src/app/knowledge/page.tsx`（及如有拆分的组件文件则同目录新建 `ChunkReviewPanel.tsx`）

- [ ] **Step 1: 状态文案**  
  `pending_review` →「待审切块」；`ready` →「已确认」；`published` →「已发布」

- [ ] **Step 2: 待审面板**  
  - 拉 `GET .../chunks`  
  - 每块 textarea + 保存（PUT）  
  - 「大模型清理（预览）」→ 展示 original/proposed → 勾选后 `mode=apply`（合同提示需确认 force）  
  - 「确认切块」→ confirm → 刷新状态

- [ ] **Step 3: ready 仍展示既有问答/发布；pending 时禁用发布**

- [ ] **Step 4: 手测清单**  
  上传 txt/pdf → 待审 → 改一块 → 确认 → 生成问答 → 发布 → 对话能搜到

- [ ] **Step 5: Commit**（用户要求时）

```bash
git commit -m "feat(web): knowledge chunk review and LLM clean UI"
```

---

### Task 7：规格收尾 + CHECKPOINT

**Files:**
- Modify: `docs/superpowers/specs/2026-07-24-chunk-review-denoise-design.md`（状态改为已批准并落地）
- Modify: `docs/superpowers/CHECKPOINT.md`

- [ ] 顶部断点：本刀完成项、下一步  
- [ ] 日志追加一条  
- [ ] 不写密钥  

---

## Spec coverage（自检）

| 规格项 | Task |
|---|---|
| 不做固定过滤 | 全局约束；Task4 Mock 桩仅测用 |
| `pending_review` + confirm→ready | Task2/3 |
| 检索仅 published | Task1/5 |
| GET/PUT chunks | Task3 |
| llm-clean suggest/apply + 合同 | Task4 |
| reopen + published 409 | Task3 |
| 前端预览 | Task6 |
| 验收脏 PDF 人工/LLM 路径 | Task5/6 |

## 执行方式

计划写好后请用户选：

1. **本会话按 Task 推进**（subagent-driven-development）  
2. **另开会话执行**（executing-plans）  
