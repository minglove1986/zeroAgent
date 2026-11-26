# 管理端知识库维护（B3 + C2 + 解析/版本/父子分块）设计

> 状态：波次 0–5 + 分类 CRUD 已落地；审计/缓存页仍可后置  
> 日期：2026-11-20  
> @author 赵振明

## 1. 裁定摘要

| 项 | 决策 |
|---|---|
| 入口 | **仅 admin-web**；员工端 `/knowledge` **下线（E3）** |
| 管理端范围 | **B3**：KB / 文档 / 权限 / 分类 / 审计·缓存（五模块） |
| 切块 | **C2**：`pending_review` 下手改 + 拆/合/调序/删；发布态须 reopen |
| 解析 | **Word（docx）+ Excel（xlsx）**；优先开源库 |
| 切块引擎 | **LlamaIndex** 父子分块为主路径；`native` 可回滚 |
| 版本 | 文档版本上传 / 列表 / 回滚 |
| 原则 | **优先开源，避免造轮子** |

## 2. 架构

```
admin-web/(admin)/knowledge/**
  → FastAPI /api/v1/knowledge-* | documents | chunks | doc-categories | …
  → MySQL / OSS / Celery ingest / Milvus
对话 RAG 仍只读 published（员工端 chat 不变）
```

### 开源选型（避免自研）

| 能力 | 选型 |
|---|---|
| PDF | 现有 `pypdf`（MinerU 另议） |
| Word | `python-docx` |
| Excel | `pandas` + `openpyxl` |
| 父子/智能切块 | `llama-index-core` node parsers（Hierarchical / Markdown 等） |
| 向量写入 | 先保留现有 Milvus 封装；后续可换 LlamaIndex VectorStore |

配置：`kb_chunker_backend = llamaindex | native`（默认 `llamaindex`）。

## 3. 波次交付

0. 路由/菜单骨架 + 员工端下线  
1. 管理端 KB/文档/权限/分类（对齐现 PDF 能力）  
2. 切块 C2 API + 管理端切块台  
3. docx/xlsx 解析接入 ingest  
4. 父子分块 + LlamaIndex chunker；检索嵌子块、答用父块上下文  
5. 文档版本 + 审计/缓存（无接口则占位）

本期不做：URL 抓取、PPT、五道闸门大改、用 LlamaIndex 全量替换 Hybrid 检索。

## 4. 切块 C2 + 父子块（要点）

- 表扩展：`document_chunks.parent_chunk_id`、`chunk_role`（`parent|child`）、可选 `version_id`
- 检索/嵌入：仅 **child**；命中后取父块喂 LLM（与知识库 PRD §6.3 一致）
- C2 操作仅 `pending_review`；合/拆后重算 `ordinal`
- 确认切块仍走 embed + Milvus upsert

## 5. 员工端

- 导航去掉「知识库上传」
- `/knowledge` 展示下线说明 + 管理端入口链接
- 不保留可写 UI

## 6. 风险

- 一期面大：必须按波次验收  
- LlamaIndex 依赖体积：锁定小范围导入 node_parser，勿一次拉全生态  
- 父子块与 C2 交互：禁止跨父块随意合并不加校验  
