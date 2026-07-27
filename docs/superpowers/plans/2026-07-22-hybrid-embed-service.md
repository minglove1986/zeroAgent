# Hybrid + 独立 Embedding/Rerank 服务 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 可替换的独立 Embedding/Rerank HTTP 服务 + 主系统 Hybrid（稠密∥BM25→Rerank）检索。

**Architecture:** `services/embed_rerank` 独立进程；主仓仅 HTTP client；`search_kb_chunks` 编排 Hybrid；Milvus 新集合可配置维。

**Tech Stack:** FastAPI、sentence-transformers / FlagEmbedding（服务内）、pymilvus、httpx、pytest

## Global Constraints

- 主应用不 import 模型库；只认 `/v1/embeddings`、`/v1/rerank`  
- 默认 512 维小模型；Mock 可测  
- `@author 赵振明`；东八区时间；无 git 跳过 commit  
- 保留 D13 / agent_kbs 过滤不变  

---

### Task 1: embed-rerank 服务骨架 + 契约测试

**Create:** `services/embed_rerank/`（`app.py`、`Dockerfile`、`requirements.txt`、`README.md`）

- [x] `/health`、`/v1/embeddings`、`/v1/rerank`  
- [x] 环境变量 `EMBED_MODEL`、`RERANK_MODEL`、`DEVICE=cpu`  
- [x] 无模型权重时可用「确定性伪向量」模式 `EMBED_BACKEND=mock` 便于 CI  
- [x] 主仓 `tests/test_embed_rerank_contract.py` 用 httpx/ASGI 或 mock 验契约  

### Task 2: 主仓 HTTP 客户端

**Create:** `modules/vector/embed_client.py`、`rerank_client.py`  
**Modify:** `config.py`（`embed_service_url`、`rerank_service_url`、`embed_dim=512`）  
**Modify:** `memory/embedding.py` 的 `embed_texts` 优先 HTTP  

- [x] TDD client；超时/失败回落  
- [x] Mock_EXTERNAL 不调外网  

### Task 3: 本地 BM25 + Hybrid 编排

**Create:** `modules/knowledge/bm25.py`（或 sparse 本地）  
**Modify:** `search.py` — dense ∥ bm25 → RRF → optional rerank  

- [x] 单测：专有词靠 BM25 抬升  
- [x] Rerank client 接入；失败跳过  

### Task 4: Milvus 集合 v2 + 入库

**Modify:** `kb_milvus.py` — 集合名/维可配置；写入 content 字段（若用 Milvus BM25）或仅 dense+本地 BM25  

- [x] 本刀若 Milvus BM25 复杂：先 **dense(Milvus/本地) ∥ 本地 BM25**，接口预留 sparse  
- [x] ingest 仍调统一 `embed_texts`  

### Task 5: Compose + CHECKPOINT + 全量测

- [x] `docker-compose` profile `embed`  
- [x] CHECKPOINT 启动与换模型说明  
- [x] `pytest -q` 全绿  

---

## Spec

`docs/superpowers/specs/2026-07-22-hybrid-embed-service-design.md`
