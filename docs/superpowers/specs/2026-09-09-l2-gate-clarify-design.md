# L2 候选门槛 + 澄清卡（P0–P2）设计

> 状态：已实现（待热更验收）  
> 日期：2026-09-09  
> 作者：赵振明  
> 成功标准：**关键词只提名；过本地门槛才执行；不过则出澄清卡（方案 B）**

## 1. 产品裁定

| 项 | 裁定 |
|---|---|
| 模型 | 命中 = `IntentDecision` 候选；`apply_gates` 纯规则/检索，**不再调 LLM** |
| 门槛失败 | **B：出澄清卡**（`route_clarify`） |
| 无文档时选项 | `先去知识库找`（`kb_lookup`） / `随便聊聊`（`chitchat`）+ 可选自由文本 |
| 范围 | P0 文档门槛 + P1 结构 + P2 `doc_pick`/弱查库/试跑，一次交付 |
| 不做 | 门槛调 LLM；完整多轮槽位状态机重写；管理端配任意正则门槛 |

## 2. 漏斗

```text
match_l2_rules → 候选
       │
apply_gates(candidate, GateContext)
  ├─ pass     → 短路执行（slots 可带 doc_id）
  ├─ clarify  → route_clarify（含 doc_pick / kb_confirm 等）
  └─ soft_miss→ 视为未命中 → L3 → L4
```

## 3. 结构（P1）

- **候选**：继续用 `IntentDecision`（不另造平行类型，避免双轨）
- **`GateContext`**：`doc_candidates` + `docs_resolved`
- **`GateResult`**：`action ∈ {pass,clarify,soft_miss}` + `decision` + `gate_reason`
- **`apply_gates`**：`src/app/modules/intent/gates.py`

## 4. 门槛规则（P0）

### 4.1 `doc_analyze`

| 条件 | 结果 |
|---|---|
| `docs_resolved` 且唯一 `doc_id` | pass，`slots.doc_id` |
| 多篇 | clarify `doc_pick`，候选=文档标题 +「随便聊聊」 |
| 0 篇 | clarify `doc_pick`，选项=`kb_lookup` / `chitchat` |
| 未解析上下文 | 按 0 篇澄清（禁止假装可执行） |

### 4.2 `kb_lookup`（弱查库，P2）

剥口令后实质 query 过空 → clarify `kb_confirm`（复用既有卡）。

### 4.3 请假 / 纠正

既有金句门禁与咨询口吻已在 `match_l2_rules` / funnel；本迭代不改语义，仅保证 gate 对无副作用意图 `pass`。

## 5. 澄清与续跑（P2）

- `build_route_clarify_card` 支持 `clarify_kind=doc_pick`
- `card-action`：选 `doc:{id}` → `doc_analyze`；`kb_lookup` → 检索；`chitchat` → 系统助手续答；自由文本 → 既有 suppress 续跑
- meta 带上 `task` / `original_user_content` / 文档候选

## 6. 接线

- `evaluate_intent_funnel_async(..., gate_context=)`：L2 高置信先 gate
- `intent_node`：从 `configurable.db` 解析文档候选再漏斗
- `resolve_doc_candidates`：基于 `run_kb_lookup` 去重 `doc_id`+title
- 管理端试跑：展示 `gate_action` / `would_short_circuit` / `clarify_kind`

## 7. 风险

- 文档解析依赖检索质量：宁可多澄清，不可误绑错误 doc
- 试跑无会话权限上下文时只能预测门槛，不能保证与生产完全一致（文案标明）
