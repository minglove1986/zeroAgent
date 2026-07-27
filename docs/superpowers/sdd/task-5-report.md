# Task 5 报告：soft_delete + recover + auth

- **Status**: DONE（2026-07-23 09:24:30 东八区）
- **Tests**: `tests/test_kb_admin_api.py` — **15 passed**（含软删/恢复 ops+API、upload/publish 鉴权）；相关回归 6 passed
- **Concerns**: recover 后 `status=ready` 但无切块/向量，检索需重新上传入库；`delete_kb_vectors_by_document` 单测已 mock
- **Path**: `src/app/modules/knowledge/document_ops.py`；`src/app/api/v1/knowledge.py`；`tests/test_kb_admin_api.py`
- **Next**: Task 6 — 重做 `web/src/app/knowledge/page.tsx`
