# 向量主召回 + 切块统一 Metadata（1A / 2A）

> 状态：已实现  
> 日期：2026-11-23 16:35:26  
> @author 赵振明

## 目标

1. 检索主路径：Milvus ANN（+ 标量过滤）→ `chunk_id` → MySQL 回表正文/发布态 → 候选 BM25/RRF → 可选 Rerank → 低分丢弃。  
2. 切块统一检索核心 metadata（写入 SQL + Milvus 标量）；文档专有字段仍在 `documents.metadata_json`。  
3. 管理端切块台可查看/编辑核心 metadata；支持同步与回填重建向量。

## 非目标

- 不上 ES/OpenSearch。  
- 不把 schema 专有字段全集摊进 Milvus。  
- 不改发布闸门与 D48。

## 检索流

```text
Query → 专名/焦点
      → Milvus ANN + expr(kb_id, person/project/title…)
      → MySQL IN (chunk_id) JOIN published
      → 候选 BM25 + RRF → Rerank? → drop_low → top-k
```

Milvus 不可用时：focus 收窄文档后受限加载（`kb_search_fallback_chunk_cap`，默认 2000），禁止无脑全库。

## 切块 Metadata（schema_version=1）

| 字段 | 说明 |
|---|---|
| title / doc_type / category_codes | 文档派生 |
| person_name / project_name / keywords | 文档 meta ∪ 块内轻量词 |
| source | inherit \| manual |

`source=manual` 时同步/回填不覆盖非空手改键。

## 集合

- MySQL：`document_chunks.metadata_json`（迁移 0061）  
- Milvus：`za_kb_chunks_v3`（无回答正文；标量协助过滤）

## 管理端

- ChunkWorkbench：单块编辑 metadata；「同步 Metadata」「回填并重建向量」  
- API：`PUT .../chunks/{id}` 支持 metadata；`sync-metadata`；`backfill-metadata`
