# Task 3 报告：document_chunks 迁移 + ORM

**日期：** 2026-07-22 12:29:00  
**状态：** 完成

## 交付物

| 文件 | 操作 |
|---|---|
| `migrations/versions/0016_document_chunks.py` | 新建 |
| `src/app/models/knowledge.py` | 新增 `DocumentChunk` |
| `src/app/models/__init__.py` | 导出 `DocumentChunk` |

## 迁移

- `revision`: `0016_document_chunks`
- `down_revision`: `0015_conversation_tokens`
- `alembic heads` → `0016_document_chunks (head)` ✓

## 表结构

| 列 | 类型 | 说明 |
|---|---|---|
| id | varchar(32) PK | |
| document_id | varchar(32) NOT NULL | |
| kb_id | varchar(32) NOT NULL | |
| ordinal | int NOT NULL default 0 | 块序 |
| content | text NOT NULL | |
| embedding_id | varchar(32) NULL | 通常 = id |
| created_at | datetime | CURRENT_TIMESTAMP |

## 验证

- Alembic：`alembic heads` 确认 head 为 `0016_document_chunks`
- 单测：本 Task 以 schema 为主；Task 4 再用 `metadata.create_all` / ingest 集成测试
- 未执行 `alembic upgrade`（需本地 MySQL 连接）
- 未 git commit（按任务要求）

## 下一步

Task 4：切块 + ingest 写 chunks + KB milvus upsert
