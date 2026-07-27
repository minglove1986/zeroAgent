# KB 问答生成与命中测试（设计）

> **日期**：2026-07-23  
> **状态**：已批准（用户确认：本刀做生成问答+真检索命中+失败明细；**多切分 / 完整预问答工作台后续另开**）  
> **权威对齐**：PRD D7；API §7；库表 `document_qa_pairs` / `documents.hit_rate`；现有 `evaluate_publish_gate`、`search_kb_chunks`

## 1. 目标

文档 `ready` 后可：

1. **自动生成** ≥5 条问答（LiteLLM；Mock 规则回落）  
2. **真检索命中测试**（限定本文档 chunks）并写回 `hit_rate`  
3. 展示**未命中明细**，支持改问答后重测 / 重新生成  
4. 发布仍走 D7 闸门（`qa_count≥5` 且 `hit_rate≥0.8`）

## 2. 非目标（本刀不做）

- 多种切分策略 / SmartChunker / 改 `chunk_text`  
- 入库 Celery 内静默自动生成  
- 超管强制绕过发布闸门  
- MinerU / OCR 增强  

## 3. API

| 方法 | 路径 | 行为 |
|---|---|---|
| `PUT` | `/api/v1/documents/{id}/qa-pairs` | body `{ items: [{ question, expected_chunk_hint? }] }` **全量替换**；鉴权同文档写（`_require_kb_read`） |
| `POST` | `/api/v1/documents/{id}/generate-qa` | query `run_hit_test` 默认 `true`；文档须 `ready`（或已有 chunks）；生成默认 5 条并替换；可选接着命中测试 |
| `POST` | `/api/v1/documents/{id}/hit-test` | 文档须有 chunks；对每条 QA 在**本文档** chunks 上 Hybrid 检索 top_k=5；写 `hit_rate`；返回明细 |
| `GET` | `/api/v1/documents/{id}/qa-pairs` | 列出当前问答（供前端编辑） |

### 命中判定

- 检索范围：仅 `document_chunks.document_id == id`（在现有 `search_kb_chunks` 结果上过滤，或先取本文档 chunks 再检索——实现取「本文档 chunks 集合上的 hybrid」，避免他文档污染）  
- 有 `expected_chunk_hint`：top-k 任一条 `content` **包含** hint（去空白后子串）→ 命中  
- 无 hint：top-k 非空 → 命中  
- `hit_rate = hits / total`（total=0 时不写、返回 422）

### 生成问答

- 输入：拼接本文档 chunks（截断总长，如 12k 字符）  
- 真模型：`chat_completion_json`，要求 JSON 数组 `[{question, expected_chunk_hint}]`，目标 5 条；hint 须摘自原文短句  
- `MOCK_EXTERNAL`：从各 chunk 取首句/前 40 字作 hint，生成「这段说了什么：…」类 question，凑满 5 条  
- 解析失败 → 42201

## 4. 前端（`/knowledge`）

- 文档操作：「生成问答并测命中」「问答/命中」展开编辑  
- 展示 `qa_count`、`hit_rate`；未达标文案明确  
- 命中结果区：未命中条目 + 召回预览  
- 动作：保存问答、重跑命中、重新生成  
- 发布按钮行为不变（42201 中文）

## 5. 失败路径（未达 80%）

- 不发布；展示比率与未命中列表  
- 用户可改 hint/题、重测，或重新生成  
- 文档质量问题：提示重新上传（切分后续再增强）

## 6. 测试

- PUT/GET qa-pairs 替换与鉴权  
- hit-test：mock embed/search 或内存 chunks，断言 hit_rate 与 details  
- generate-qa：`MOCK_EXTERNAL=true` 生成 ≥5 并可挂 hit-test  
- 发布闸门回归仍通过  

## 7. 后续切片（备忘）

- `chunk_strategy`：fixed / paragraph / markdown / semantic  
- 预切块预览 + 预问答工作台（试跑不落库确认流）
