# Summary 抽取 + Milvus 记忆去重设计

> **状态**：已批准（2026-07-22）  
> **作者**：赵振明  
> **日期**：2026-07-22 10:02:31（东八区）

## 范围（方案 A）

1. 对话 transcript 字符数 ≥ 阈值（默认 12000）时可抽 `summary`
2. LiteLLM embeddings（Mock 伪向量）
3. 写入前相似度 > 0.9 跳过
4. Milvus best-effort；失败/Mock 降级仅 MySQL + 本地伪向量去重

## 不做

冷热分层、定期扫描、精确 token、KB Hybrid RAG。
