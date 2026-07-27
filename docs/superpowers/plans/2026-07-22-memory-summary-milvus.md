# Summary + Milvus 记忆 Implementation Plan

> **For agentic workers:** TDD task-by-task.

**Goal:** summary 抽取 + Embedding 去重 + Milvus best-effort 入库。

**Architecture:** extract 扩展 summary → embed → cosine dedupe → MySQL → Milvus(optional)。

**Tech Stack:** LiteLLM embeddings、pymilvus（可选）、pytest

---

### Task 1：Red 单测

- [x] 解析允许 summary；阈值触发规则摘要
- [x] 伪向量高相似去重跳过
- [x] 运行失败后再实现

### Task 2：Green

- [x] Settings + embed + milvus store + persist 编排
- [x] 更新 extract / Celery / runtime
- [x] pymilvus 依赖；测试绿

### Task 3：CHECKPOINT
- [x] 已更新
