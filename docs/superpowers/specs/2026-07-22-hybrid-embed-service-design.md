# Hybrid 检索 + 独立 Embedding/Rerank 服务设计

@author 赵振明
@date 2026-07-22 15:19:31

## 范围（已批准）

1. **独立 Docker 服务** `embed-rerank`：本机 CPU 跑小维度 Embedding + 轻量 Rerank  
2. 主系统只认 **HTTP 契约**，模型可随时更换  
3. 检索：**稠密 ∥ BM25 → 合并 → Rerank → Top-k**  
4. Mock / 无服务时降级：伪向量 + 本地关键词，测试可绿  

## 不做

- 本刀上完整 BGE-M3 稀疏 / 超大 BGE-Rerank  
- `kg_ids`、改 D13 语义  

## 设计原则：服务切分

主应用（API / Celery）**禁止**直接 `import` 具体模型库。

| 边界 | 约定 |
|---|---|
| 配置 | `EMBED_SERVICE_URL`、`RERANK_SERVICE_URL`、`EMBED_DIM`、`EMBED_MODEL`（仅文档/服务侧） |
| 客户端 | `modules/vector/embed_client.py`、`rerank_client.py`：HTTP + 超时 + Mock 回落 |
| 契约版本 | URL 路径带 `/v1/`，响应含 `model` 字段便于观测 |

更换更好模型时：**只改 embed-rerank 镜像/环境变量**，主仓库契约不变。

## HTTP 契约（稳定面）

### `POST /v1/embeddings`

请求：`{"input": ["文1", "文2"]}`  
响应：`{"model": "...", "data": [{"index": 0, "embedding": [float, ...]}, ...]}`  
维度：默认 **512**（`bge-small-zh-v1.5`）

### `POST /v1/rerank`

请求：`{"query": "...", "documents": ["段1", ...], "top_n": 5}`  
响应：`{"model": "...", "results": [{"index": 0, "score": 0.9}, ...]}`（按分数降序）

### `GET /health`

探活。

## 默认模型（可换）

| 能力 | 默认 | 维度/说明 |
|---|---|---|
| Embedding | `BAAI/bge-small-zh-v1.5` | 512，CPU |
| Rerank | 轻量 cross-encoder（可配置；失败则跳过 Rerank 用合并分） | CPU |
| 稀疏/关键词 | Milvus BM25（正文）或本地 BM25 回落 | 不绑死某一 Embedding 模型 |

## 主系统改动

1. **`embed_texts`**：非 Mock 时优先调 `EMBED_SERVICE_URL`；失败再 LiteLLM / 伪向量  
2. **入库**：切块后用新 Embedding；Milvus 集合改用可配置维 + 存 `content` 供 BM25（新集合名如 `za_kb_chunks_v2`，避免与旧 16 维冲突）  
3. **`search_kb_chunks`**：稠密 + BM25 并行 → RRF 合并 → Rerank（有服务时）→ hydrate  
4. **Compose**：`profile: embed` 启动 `embed-rerank`；CHECKPOINT 写清启动与换模型方式  

## 降级

| 条件 | 行为 |
|---|---|
| `MOCK_EXTERNAL=true` | 伪向量 + 本地关键词，不调服务 |
| Embedding 服务挂 | 打日志，回落 LiteLLM 或伪向量 |
| Rerank 服务挂 | 跳过，用 RRF 分排序 |
| Milvus 不可用 | 本地稠密余弦 ∥ 本地 BM25 |

## 测试

- 契约：Mock HTTP 服务测 client  
- Hybrid：本地路径关键词命中 + 向量命中合并  
- Rerank：mock 打乱顺序后重排  
- 既有 D13 / kb_lookup / ingest 回归  

## 验收

1. 不启大模型库，仅起 `embed-rerank` + 主 API，能入库并 Hybrid 检索  
2. 更换服务内模型名后，主代码零改或仅改配置  
3. Mock 下全量 pytest 绿  
