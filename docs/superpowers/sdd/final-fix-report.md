# Final-fix report（celery-harden）

**时间**：2026-07-22 12:10:00（东八区）  
**范围**：全分支终审 Important 三项修复  
**状态**：DONE

## 摘要

| # | 问题 | 处置 |
|---|---|---|
| 1 | `MOCK_EXTERNAL=false` 时 `put_object` 未落盘，Worker 无法 `get_object` | `put_object` 始终镜像 `.data/oss/{key}` |
| 2 | 入库重试耗尽 Document 卡在 `processing` | 最终尝试标记 `failed` 再抛出 |
| 3 | `expire_approvals` 缺 AsyncEngine 线程桥 | 对齐 ingest 的 `_run_async` 模式 |

## 测试

- 覆盖：`test_oss_get` / `test_document_ingest` / `test_celery_expire_beat` → **11 passed**
- 全量：`pytest -q` → **91 passed**（1 warning）

## 报告

详情见 `docs/superpowers/sdd/task-5-report.md` → `## Final-review fixes`。

## 未做

- 真 OSS SDK、DB 引擎 per-task 重设计、记忆同步热路径改动、git commit。
