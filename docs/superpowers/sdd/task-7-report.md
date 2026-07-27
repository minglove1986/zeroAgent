# Task 7 报告：CHECKPOINT + 回归

- **Status**: DONE（2026-07-23 09:33:59 东八区）
- **KB 回归**: `test_kb_admin_api` + `test_kb_d13_search` + `test_document_ingest` → **25 passed**（4.27s）
- **全量 pytest**: **153 passed**, 8 warnings（42.48s；Starlette httpx2 弃用 + PyMilvus ORM 弃用）
- **CHECKPOINT**: 第一刀 B 闭环完成；下一步 QA/hit_rate 流水线或拖拽/URL
- **Concerns**: Task 6 浏览器联调清单仍待人工；warnings 非阻塞
- **Path**: `docs/superpowers/CHECKPOINT.md`；`docs/superpowers/sdd/progress.md`

## Final-review fixes

- **Status**: DONE（2026-07-23 09:40:43 东八区）
- **Commands**:
  ```powershell
  & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_kb_admin_api.py tests/test_document_ingest.py -q
  # → 24 passed in 4.22s
  & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_document_publish_gate.py -q
  # → 4 passed in 1.32s
  ```
- **Fixed**:
  1. Critical：`POST /documents` 加 `_require_kb_read`，`created_by=actor.user_id`；无授权 403 测试
  2. 未软删 `recover` → 409 / `40901`「文档未软删，无法恢复」；ops 抛 `DocumentNotSoftDeletedError`
  3. 列表 KB 返回 `viewer.is_platform_admin`；前端专家只读权限（GET 可见，无增删保存）
  4. 发布闸门中文 message，码仍 `42201`
  5. Alembic `0018_document_fail_reason`；ingest 失败写 / 成功清；status 返回 `reason`
  6. Minor：移除 `put_permissions` 中不可达的 `_ALLOWED_SUBJECT_TYPES` 循环
- **Files**: `knowledge.py`、`document_ops.py`、`ingest.py`、`models/knowledge.py`、`0018_*.py`、`ingest_document.py`、`web/.../knowledge/page.tsx`、`test_kb_admin_api.py`、`test_document_publish_gate.py`
- **Concerns**:
  - 列表文档 `qa_count` 仍 N+1（未改，可后续批量 count）
  - 生产 MySQL 需执行 `alembic upgrade head`（`0018`）
  - Celery 重试耗尽写 `fail_reason=exception`（非详细栈）
