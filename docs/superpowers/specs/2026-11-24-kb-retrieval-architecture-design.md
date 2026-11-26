# 知识库检索架构契约（Scope / Gate / Metadata 增强）

> 状态：Phase A 已实现（2026-11-24；Phase B/C 未开始）  
> 日期：2026-11-24 14:51:28（修订 2026-11-24 14:56:35）  
> @author 赵振明  
> 范围策略：方案 1 分期 — Phase A 契约闭环 → Phase B 五道闸门 → Phase C 稳定与观测  
> 关联：`2026-11-23-kb-vector-first-metadata-design.md`（向量主召回 + 切块 Metadata 已落地）；主 PRD D13/D14；知识库 PRD §7  
> **本设计对知识库 PRD 的显式偏离**见 §13 / §14（空绑定、soft 回落）；实现以本文件 + 主 PRD 第十六章为准。

---

## 1. 背景与问题

### 1.1 市面成熟范式

企业 RAG（Azure AI Search Hybrid、Elastic 稠密+稀疏、LlamaIndex Retriever、Vertex Grounding）通常拆为：

- **范围/ACL**：检索前强制 filter  
- **召回**：多路或 cascading + 元数据进 ANN  
- **精排**：独立 Rerank  
- **可信交付**：groundedness / citation，**首 token 前**拦截  
- **降级**：基础设施降级 ≠ 语义放宽，且可观测  

### 1.2 源码级缺陷（严重度）

| ID | 严重度 | 问题 | 关键代码 |
|---|---|---|---|
| S0-1 | S0 | soft 最终 `document_ids=None` 全文，冲掉人名/分类意图 | `lookup.py` 156–167 |
| S0-2 | S0 | Agent 未绑 KB → `list_all_kb_ids` 全库 | `lookup.py` 35–47 |
| S0-3 | S0 | `visibility_override` 未进检索 | 模型有字段；`knowledge/` 检索 0 消费 |
| S1-1 | S1 | Agent 流式先 `content_delta` 再 D14 | `runtime.py` 1080–1091；`plan_execute._execute_respond` 598–611 |
| S1-2 | S1 | D14 仅 `len(citations)>0`，非答案绑定 | `runtime.evaluate_rag_citation_gate` |
| S1-3 | S1 | 生产路径残留 `rag_stub_has_citation` | `kb_lookup.py` 122；`runtime.py` 296–297 |
| S2-1 | S2 | filters / Milvus 专名 / prefer_hits 三套收窄冲突 | `retrieval_plan` / `search.py` / `entity_filter` |
| S2-2 | S2 | `document_ids` 未下推 Milvus expr | `build_milvus_filter_expr` vs hydrate |
| S2-3 | S2 | 专名混槽 OR（人/项目/标题共用 match_terms） | `search.py` 284–289 |
| S2-4 | S2 | PRD §7.6 五道闸门 / 并行 / 缓存未落地；阈值语义与 RRF 不一致 | 无 `quality_gate.py`；config 为相对阈值 |
| S3-* | S3 | Milvus 同步、无超时、SQL cap 无序、索引对账缺失 | `kb_milvus.search_kb_chunk_ids` 等 |

**判断**：向量主召回方向正确；缺的是 Scope / Gate / 降级三类契约。切块 Metadata（v1）已写入 SQL + Milvus，但检索未吃满。

---

## 2. 目标与非目标

### 2.1 目标

1. 抽出 **ScopeResolver**、**HybridRetriever（改造现有 search）**、**QualityGate**、**EvidencePack**。  
2. Phase A：范围正确、交付可拒、Metadata 增强召回（分槽 + 分类下推 + keywords 加权）。  
3. Phase B：对齐知识库 PRD §7.6 闸门链（可配置）。  
4. Phase C：超时、对账、BM25 中文、缓存；文档与实现单一真相。  

### 2.2 非目标

- 多租户、外部 A2A、OpenIM、Temporal  
- 另起检索微服务 / 上 ES  
- Phase A 上 HyDE、图谱增强、完整 G2–G5 NLI  
- 无倒排时宣称「三路并行 Hybrid」  

---

## 3. 分期边界

| 阶段 | 目标 | 核心产物 | 明确不做 |
|---|---|---|---|
| **A** | 范围正确、交付可拒、Metadata 吃进 ANN | `scope.py`、`evidence` 结构、Gate 前置、lookup/search/runtime 改造 | G2–G5 NLI、语义缓存、真三路并行 |
| **B** | 可信度闸门 | `quality_gate.py`；G1+D14 常开；G2 默认开；G3–G5 默认关 | 倒排/缓存大基建 |
| **C** | 稳定与观测 | 超时异步、对账、BM25 分词、精确缓存；PRD 第七章表述对齐 | 无倒排不宣称并行 |

目标调用链：

```text
kb_lookup / rag_search / tool.kb_lookup
  → ScopeResolver
  → HybridRetriever
  → QualityGate（A: G1 + 简化 D14）
  → EvidencePack
  → 合成 / respond（仅 Gate pass 可 stream 正文）
```

硬规则：

1. 语义降级默认不上「全文」  
2. 有 `agent_id` 且未绑 KB → 空范围  
3. 任一 `content_delta` 前必须完成 Gate  

---

## 4. ScopeResolver 与降级

### 4.1 契约

```text
输入: actor, agent_id?, kb_ids?, intent_filters?, query
输出: RetrievalScope
  kb_ids: list[str]
  document_ids: list[str] | None   # None=不缩文档；[]=空结果
  milvus_expr: str
  focus: {persons[], projects[], titles[], keywords[]}
  degrade_level: none | drop_meta | drop_category
  reason_codes: list[str]
```

规则：

1. **绑定**：有 `agent_id` 且 `AgentKb` 空 → `kb_ids=[]`（禁止全库）。**偏离**知识库 PRD §7.2/§8.3「未绑定→全部 KB」。无 `agent_id` 的系统对话：`kb_ids = list_accessible_kb_ids`（用户并集），不得先 `list_all_kb_ids` 再交权限碰运气。  
2. **权限**：`∩ list_accessible_kb_ids`（platform_admin 跳过）。  
3. **可见性**（按知识库 PRD §8.2，禁止写成单纯 ∩）：  
   - `null`：跟随 KB 授权结果；  
   - `department`：即使 KB public，也按用户部门收窄（可能从命中集剔除）；  
   - `public`：即使 KB 为 department，本文档对「已通过 KB 并集鉴权的用户」仍可见（**扩大** document 集合，不是再交一次 ∩）。  
   实现落点：`apply_document_visibility(kb_ids, actor) -> document_ids | None`（与 PRD 命名对齐）。  
4. **意图 filters**：category / metadata → 优先算出 `document_ids`（SQL/分类表可靠）；`milvus_expr` 下推**适合标量等值**的字段（见 §5.3），分类多值以 `document_id in [...]` 下推，避免对 CSV 标量做假精确匹配。  
5. **降级上限**：默认最高 `drop_category`；禁止静默全文。兼容旧数据仅当 `filter_fallback="legacy_full"` + 审计打标。  

`run_kb_lookup` 变薄编排；`search_kb_chunks` 只消费 `RetrievalScope`，禁止函数内私自放宽专名。

### 4.2 DegradeLevel

| 级别 | 含义 |
|---|---|
| `none` | 全量 filters + 分槽专名 |
| `drop_meta` | 去掉 metadata 精确谓词，保留分类 |
| `drop_category` | 分类也放宽，仍限 `kb_ids`（及可见性） |
| （禁止默认）全文 | 仅 `legacy_full` |

---

## 5. Metadata 增强检索（Phase A，基于已有字段）

切块核心字段（已存在）：`title` / `doc_type` / `person_name` / `project_name` / `keywords` / `category_codes` / `chunk_role`（SQL + Milvus v3 标量）。

### 5.1 要做

1. **分槽过滤**：query → `focus` 分槽；Milvus expr 按槽精确匹配。  
2. **分类双通道一致**：`category_codes` / `doc_type` 进 `milvus_expr`，与 SQL `document_ids` 对齐。  
3. **keywords 加权**：候选含 focus 词则加分/`prefer`；无命中**不清空**整表（避免空 metadata 误杀）。  
4. **空标量**：专名 0 命中 → 升 `degrade_level` 并打标；**删除** `search.py`「退回仅 kb_id 再召回」默认行为。  
5. **`document_ids` 下推**：写入 milvus expr（过长则分批 ANN 或先 SQL 再向量）。  
6. **`chunk_role`**：现有父子策略显式写入 scope。  

### 5.2 不做（A）

HyDE / 多查询改写 / 图谱；不改 Milvus schema（keywords 仍 VARCHAR）。

### 5.3 Milvus 标量能力边界（实现约束）

| 字段 | 存储形态 | ANN expr 策略 |
|---|---|---|
| `person_name` / `project_name` / `title` / `doc_type` / `kb_id` / `document_id` | 单值 VARCHAR | 可精确 `==` / `in` |
| `category_codes` / `keywords` | **逗号拼接 CSV** | **禁止** `category_codes == "hr.resume"` 当真多值；分类过滤以 SQL→`document_ids`→`document_id in` 下推；keywords 仅回表后加权 |
| 超长 `document_id in` | — | 分批 ANN 或「先 SQL 缩文档再向量」 |

---

## 6. HybridRetriever

改造 `search_kb_chunks`，不另起服务。

```text
消费 RetrievalScope
  → embed(query)
  → Milvus ANN(scope.milvus_expr, candidate_n)
  → hydrate(published ∩ scope)
  → BM25 on candidates + RRF（cascading hybrid，文档如实描述）
  → optional Rerank
  → family dedupe
  → keywords/focus 加权
  → drop_low_score（相对阈值；RRF 不用绝对 0.55）
  → hits
```

**Infra 降级**（与语义降级分开）：Milvus/embed 失败或超时 → 受限 SQL 候选（仍受 `document_ids`）+ `degrade=infra_*`。

分数语义：RRF 用 `kb_hit_score_relative_min`；Rerank 后才可启用绝对分下限。

---

## 7. QualityGate 与流式时序

### 7.1 Phase A 最小闸门

| 闸门 | 条件 | 错误码 |
|---|---|---|
| G1 | EvidencePack.hits 空（Retriever 内 `drop_low_score` 之后） | `rejected_no_recall` |
| D14 简 | `used_rag` 且 citations 空 | `rejected_no_citation` |

说明：相对低分丢弃留在 Retriever（`kb_hit_score_relative_min`）；Gate G1 **不重复算分**，只判「无可交付证据」。避免 Gate 与 `drop_low` 双重阈值打架。

- 系统路径：`execute_system_kb_lookup` 合成**前** Gate；删除 `rag_stub_has_citation` 生产分支。  
- Agent：`rag_search` 结束后若 hits/citations 空 → **禁止**进入流式 `respond`；写入终端态：`final_answer=拒展文案`（preset，走非 LLM 或单次非流式固定稿），`status=rejected_*`；**禁止**因空引用触发无限 `should_replan`（replan 黑名单或「rag 已失败则不再 rag_search」）。  
- `runtime` 事后 D14 仅作兜底；主修复在图内。单测：无 citation 时 SSE 无正文 delta（拒展文案可 delta，但不得先泄模型胡答再改口）。  

### 7.2 Phase B

落地 `quality_gate.py`：G1+D14 常开；G2 默认开；G3/G4/G5 默认关可配。闸门只消费 EvidencePack；拒展在首个正文 delta 前。

### 7.3 EvidencePack（最小字段）

`hits` / `citations` / `degrade_level` / `gate` / `kb_ids_count` / `document_scope_count` / `used_milvus` / `reason_codes`。  
`turn_trace`：`scope_resolved` / `gate_rejected`（禁止密钥）。

---

## 8. 调用点

| 入口 | 改造 |
|---|---|
| `run_kb_lookup` | Scope → Retriever → Gate → citations |
| `_execute_rag_search` | 同上；失败 observation + 空 cites + 短路 |
| `tool/executor` kb_lookup | 同一 `run_kb_lookup` |
| `handle_system_kb_lookup` | 合成前 Gate；去 stub |

---

## 9. Phase C

- Milvus/embed/rerank 统一 timeout；同步调用 `asyncio.to_thread`  
- MySQL ↔ Milvus 对账；软删立即不可查  
- BM25 中文分词 + 命中测试回归  
- 精确缓存优先；语义缓存可选  
- 知识库 PRD §7.4「三路并行」改为 cascading，或具备倒排后再并行  

---

## 10. 验收清单

### Phase A

- [ ] 有 `agent_id` 未绑 KB → hit=0  
- [ ] 默认 soft 不上全文；`legacy_full` 才全文且有 degrade 标  
- [ ] `visibility_override` 生效  
- [ ] Milvus expr 含分槽专名 + 分类/`doc_type`；`document_ids` 下推或等价约束  
- [ ] keywords 加权；空 keywords 不误杀  
- [ ] 删除 `rag_stub_has_citation` 生产分支  
- [ ] used_rag 无 citation → SSE 无正文 delta  
- [ ] `turn_trace` 可见 `scope_resolved` / `gate_rejected`  

### Phase B

- [ ] G2 可拒主题偏离  
- [ ] G3–G5 关闭时行为与 A 一致  

### Phase C

- [ ] 超时降级可观测  
- [ ] 对账能修孤儿向量  
- [ ] BM25 回归不差于基线  

---

## 11. 风险与应对

| 风险 | 应对 |
|---|---|
| Metadata 未回填导致过严空召回 | degrade 上限 + 运维回填；禁止默默全文 |
| Gate 误杀 | A 仅 G1+D14简；B 高阶默认关 |
| milvus expr 过长 | document_id 分批或先 SQL 再 ANN |
| 流式已推 thought | thought 可保留；正文必须 Gate 后 |

---

## 12. 实现顺序（设计约束，非工期）

1. 单测先写：空绑定、soft 上限、Gate 流式时序、分槽 expr。  
2. `RetrievalScope` + Resolver。  
3. `search_kb_chunks` 消费 Scope + Metadata 下推/加权。  
4. Gate 前置（系统 + Agent）。  
5. 删 stub；观测字段。  
6. 再开 Phase B / C 独立计划。  

实现须遵循仓库：先测后写、端口 8000/3000、单租户、更新 `CHECKPOINT.md`；新增 Web 接口时同步 API 规范。

---

## 13. 与既有设计关系

- **不废止** `2026-11-23-kb-vector-first-metadata-design.md`：本设计是其检索契约补全与质量面补齐。  
- **显式偏离知识库 PRD（实现以本 spec 为准，后续应回写 PRD）**：  
  - §7.2/§8.3「未绑定 → 全部 KB」→ 改为空绑定空范围；  
  - §7.3「空结果回落全文」→ 默认 **bounded**；`legacy_full` 兼容。  
- 主 PRD D13 并集、D14 强制引用、无答案引导：保持；阈值分数语义以相对分为准（与现行 `kb_hit_score_relative_min` 对齐），避免对 RRF 名次分套绝对 0.55。  
- 主 PRD D14：Phase A =「无有效 citation 不得交付模型正文」；答案-证据 NLI 属 Phase B G5。  

---

## 14. 二次自检结论（2026-11-24）

| 检查项 | 结果 |
|---|---|
| 占位符 / TBD | 无 |
| visibility 写成单纯 ∩ | **已修正**为 §8.2 三态（含 public 扩大） |
| category_codes CSV 假精确 | **已修正**为 SQL→document_id 下推 |
| 与 PRD 冲突未标明 | **已标明**空绑定 / soft 为故意偏离 |
| G1 与 drop_low 双重阈值 | **已澄清** Gate 只判空证据 |
| Gate 失败后 replan / 无用户可见拒展 | **已补**终端 preset + 禁无限 replan |
| Phase A 范围是否可独立交付 | 是；B/C 另计划 |
| 是否需要再拆 spec | 否；实现计划仅含 Phase A |
