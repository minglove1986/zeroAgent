# Task 4 报告：documents list + status

> **计划**：`docs/superpowers/plans/2026-07-22-kb-admin-closure.md` Task 4  
> **Brief**：`docs/superpowers/sdd/task-4-brief.md`  
> **执行时间**：2026-07-23 09:20:04（东八区）  
> **状态**：DONE

## 目标

- `GET /api/v1/documents?kb_id=&include_deleted=0|1`：有权用户列出文档；默认排除软删。
- `GET /api/v1/documents/{id}/status`：`{ status, hit_rate, qa_count }`（`reason` 本刀省略）。
- 鉴权复用 `_require_kb_read`（列表用 query `kb_id`，status 用 `doc.kb_id`）。
- `qa_count` 由 `DocumentQaPair` 计数；`hit_rate` 为 `float | null`。

## 变更文件

| 操作 | 路径 |
|---|---|
| 修改 | `src/app/api/v1/knowledge.py` |
| 修改 | `tests/test_kb_admin_api.py`（保留 Task 1–3，追加 3 个文档测） |
| 修改 | `docs/superpowers/CHECKPOINT.md` |

## TDD 证据

### Step 1 — 写失败测试

- `test_list_documents_ready_for_granted_user`：有权用户见 ready + `qa_count`/`hit_rate`
- `test_list_documents_soft_deleted_only_with_flag`：默认不含软删；`include_deleted=1` 可见
- `test_document_status_includes_qa_count`：status 含 `qa_count`

### Step 2 — RED

```text
test_list_documents_ready_for_granted_user FAILED           — 405（仅有 POST）
test_list_documents_soft_deleted_only_with_flag FAILED      — 405
test_document_status_includes_qa_count FAILED               — 404
3 failed, 8 passed
```

### Step 3 — 实现

- `list_documents`：`_require_kb_read(kb_id)`；`include_deleted!=1` 时 `deleted_at IS NULL`。
- `get_document_status`：文档不存在 404；再按 `doc.kb_id` 鉴权。
- `_qa_count_for_document`：`select(func.count()).where(DocumentQaPair.document_id==...)`。

### Step 4 — GREEN

```text
tests/test_kb_admin_api.py  ...........  11 passed in 2.00s
```

命令：

```powershell
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_kb_admin_api.py -q
```

## 接口行为

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/v1/documents?kb_id=` | 有权；`items` 含 id/title/status/hit_rate/qa_count/时间戳 |
| GET | `/api/v1/documents/{id}/status` | 有权；`status`/`hit_rate`/`qa_count` |

## 自检

- [x] Task 1–3 单测保留且仍通过（共 11 passed）
- [x] 默认排除软删；`include_deleted=1` 包含
- [x] 鉴权走 `_require_kb_read`；未引入 OpenIM / `tenant_id`
- [x] 未 git commit

## 遗留 / 关注点

- 列表对每篇文档单独 `count` QA，文档量大时有 N+1；后续可改为聚合子查询。
- `failed` 时的可选 `reason` 未落库、未返回（brief 允许第一刀省略）。
- **下一刀**：Task 5 软删/恢复 + upload/publish 鉴权。
