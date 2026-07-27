# Task 4 Brief

### Task 4: documents list + status

**Files:**
- Modify: `src/app/api/v1/knowledge.py`
- Modify: `tests/test_kb_admin_api.py`

**Interfaces:**
- `GET /documents?kb_id=&include_deleted=0|1`
  - 返回 `items: [{ id, title, status, hit_rate, qa_count, deleted_at, updated_at, created_at }]`
  - 默认排除 `deleted_at IS NOT NULL`
- `GET /documents/{id}/status` → `{ status, hit_rate, qa_count, reason? }`
  - `reason`：仅 `failed` 时可选（第一刀可先不落库 reason，字段可省略）

- [ ] **Step 1: Failing tests** — 有权用户列出 ready 文档；软删文档仅 `include_deleted=1` 可见；status 含 `qa_count`

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement** — 用 `select(func.count()).where(DocumentQaPair.document_id==...)` 算 qa_count；鉴权走文档所属 `kb_id` 的 `_require_kb_read`

- [ ] **Step 4: PASS**

---
