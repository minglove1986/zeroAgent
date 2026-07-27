# kb_lookup 接 search_kb_chunks + citation 设计

@author 赵振明
@date 2026-07-22 14:35:48

## 范围（用户「执行」批准）

1. `kb_lookup` 工具：调用 `search_kb_chunks`，产出真实 `citations` 并 SSE 下发  
2. 对话「查知识库：…」RAG 路径：同样走检索 + D14；`（无引用）` 仍强制空引用拒答  
3. citation 字段：`doc_id` / `title` / `snippet`（兼容现前端）；附 `chunk_id`/`score` 可选  

## 不做

- Agent `kb_ids` 持久化表（API 现只回显未落库）→ 本刀检索范围为**全部 KnowledgeBase id**（单租户 MVP）  
- Hybrid / 重排序  
- 改 D14 语义  

## 方案

- 新增 `knowledge/lookup.py`：`hits_to_citations` + `async run_kb_lookup(db, query, kb_ids=None, top_k=5)`  
- `executor`：`kb_lookup` 同步桩改为委托说明「须 async」；运行时对 `kb_lookup` 走 `run_kb_lookup`  
- RAG 桩：解析 `查知识库` 后 query；无「无引用」则 `run_kb_lookup`；无命中 → `rejected_no_citation`  

## 测试

- 更新 `test_rag_citation_gate`：正向用例先 seed KB/document/chunks  
- 新增 `test_kb_lookup_tool`：seed 后调用 `run_kb_lookup` 有 citation  
- 既有「无引用」拒答仍绿  
