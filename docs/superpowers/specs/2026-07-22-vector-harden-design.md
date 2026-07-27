# 向量库完善设计（记忆硬化 + KB 稠密入库）

@author 赵振明
@date 2026-07-22 12:08:34

## 范围（已批准 · 方案 A）

1. **公共向量层**：连接复用、启停、维数约定、双 collection  
2. **记忆 Milvus 硬化**：与 `embed_texts` 维数对齐；删记忆时 best-effort 删向量  
3. **知识库稠密入库**：切块 → MySQL `document_chunks` → Embedding → `za_kb_chunks`  
4. **检索 API**：`search_kb_chunks`（稠密 top-k）；**本刀不改**对话 RAG / `kb_lookup` 热路径  

## 不做

- Hybrid / BM25 / 重排序  
- 对话 citation 全链路改接  
- 真云 OSS SDK、历史文档批量回填 CLI  
- 冷热分层、图谱  

## 架构

```
embed_texts (LiteLLM | Mock 16维)
        │
        ├─ persist_extracted_memories ─► za_user_memories
        │
        └─ ingest_document_sync
              decode → chunk → MySQL document_chunks
                            └─► za_kb_chunks (best-effort)
```

| Collection | 用途 | 主键 |
|---|---|---|
| `za_user_memories` | 用户记忆去重/检索 | memory_id |
| `za_kb_chunks` | 知识块稠密检索 | chunk_id |

**维数**：Mock / `mock_external` → 16；真 Embedding → 以首次成功返回维为准，配置默认 `embed_dim=1536`。两 collection **禁止混用不同维**；若已建表维不匹配 → 打日志并跳过写入（不自动 drop）。

## 1. 公共层 `src/app/modules/vector/`

| 模块 | 职责 |
|---|---|
| `client.py` | `milvus_enabled()`；`get_collection(name, dim, fields)`；连接单例（进程内） |
| `embeddings.py` | 薄封装：复用现有 `memory.embedding.embed_texts`（不复制逻辑） |

配置（`Settings`）：

- `milvus_uri: str = ""`（已有）  
- `embed_dim: int = 1536`（真模型期望维；Mock 仍用 16，不以该字段建 Mock 表）  
- `kb_chunk_size: int = 800`  
- `kb_chunk_overlap: int = 100`  

记忆侧 `milvus_store.py` 改为调用公共 `client`；删除逻辑新增 `delete_memory_vector(memory_id)`。

## 2. 记忆硬化

- upsert/search 走公共连接；集合不存在则按**当前向量维**建表  
- `persist` 成功写 `embedding_id`（已有）  
- 用户删除单条 / clear 全部记忆时：MySQL 删行后 best-effort `delete` 向量  
- 失败仅打日志，不影响 API 成功  

## 3. KB 切块与入库

### 表 `document_chunks`（Alembic 新修订，接在 0015 之后）

| 列 | 类型 | 说明 |
|---|---|---|
| id | varchar(32) PK | `chk_...` |
| document_id | varchar(32) | |
| kb_id | varchar(32) | |
| ordinal | int | 块序 |
| content | text | |
| embedding_id | varchar(32) null | 通常 = id |
| created_at | datetime | |

### 切块

- 输入：ingest 已解码的全文  
- 算法：按字符窗口 `kb_chunk_size`，重叠 `kb_chunk_overlap`；空文本 → 无 chunk、文档仍可 `ready`（或 `failed` reason=`empty_text`，取 **empty → failed**）  
- 扩展名策略不变（仅 txt/md/json/无后缀）  

### ingest 流程（修订）

1. get_object + decode（现有）  
2. chunk → 删该 document 旧 chunks（幂等重跑）→ 插入新 chunks  
3. `embed_texts` 批量（可分批）→ 有 Milvus 则 upsert `za_kb_chunks`（字段：id, document_id, kb_id, embedding）  
4. `status=ready`；Milvus 失败不阻断 ready（与记忆 best-effort 一致）  
5. 业务失败路径不变（unsupported / oss_missing）  

### Milvus `za_kb_chunks` schema

- id (VARCHAR PK), document_id, kb_id, embedding (FLOAT_VECTOR)  
- 索引：IVF_FLAT + IP（与记忆一致）  

## 4. 检索 API（模块级）

```python
async def search_kb_chunks(
    *,
    kb_ids: list[str],
    query: str,
    top_k: int = 5,
) -> list[dict]:  # {chunk_id, document_id, kb_id, score, content?}
```

- 无 Milvus：回落 MySQL——对指定 kb 的 chunk 做简易词重叠打分（或返回空并由调用方处理）；**推荐**：无 Milvus 时用本地伪向量对 chunk content 算余弦 top-k（不依赖服务），保证单测可绿  
- 有 Milvus：向量搜 + 回表补 `content`  
- **不**修改 `runtime` / `kb_lookup` / citation 桩（另开刀接线）  

## 5. Compose / 运维

- CHECKPOINT：补充 `docker compose --profile full up -d milvus`（及 etcd/minio-milvus 依赖）与 `MILVUS_URI=http://127.0.0.1:19530`  
- Worker 与 API 共用 URI；向量在 Milvus 内，不依赖进程内存  

## 6. 测试

| 用例 | 断言 |
|---|---|
| 切块 | 长度/重叠边界 |
| ingest → chunks | upload/eager 后 MySQL 有 chunk，status=ready |
| Milvus off | 仍 ready + chunks；search 本地回落有结果 |
| 记忆删 | mock delete_memory_vector 被调用（或 enabled 时） |
| 维数 | Mock 路径 16 维不炸 |
| 回归 | 既有记忆 / celery ingest / 用户记忆测试绿 |

## 验收标准

1. 文本上传入库后：`ready` 且存在 ≥1 条 `document_chunks`  
2. `MILVUS_URI` 空或 Mock：功能不报错，记忆去重与 KB chunk 仍可用  
3. `search_kb_chunks` 单测可返回命中  
4. 对话记忆热路径仍为请求内同步；无 KB Hybrid  

## 与既有决策

| 文档 | 关系 |
|---|---|
| celery-harden | ingest 从「仅 status」升级为切块+向量 |
| memory-summary-milvus | 记忆 collection 迁公共 client；范围不扩大到 Hybrid |
| 对话 RAG 桩 | 本刀不接线 |
