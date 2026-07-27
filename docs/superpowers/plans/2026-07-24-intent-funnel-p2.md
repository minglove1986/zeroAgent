# 意图漏斗 P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 中置信带下发澄清卡（是否查知识库 / Agent 候选），card-action 续跑对应路径，避免误进 RAG。

**Architecture:** L4 将 `τ_low ≤ conf < τ_high` 的 `kb_lookup` 改为 `route_clarify`（kb_confirm）；runtime 下发卡片；`stream_after_card_action` 按选项续跑 RAG 或闲聊。Agent 多候选时 `options` 为 Agent 列表。

**Tech Stack:** FastAPI runtime、message_cards、pytest、现有 SSE card / card-action。

## Global Constraints

- 澄清卡由路由模块直接发，**不经** `ask_user`（D33 / PRD）  
- 单租户；D14 仍强制；LLM 仅 LiteLLM  
- `@author 赵振明`；东八区实时注释时间  
- 对齐 `docs/superpowers/specs/2026-07-23-intent-funnel-design.md` §5 中间带 / §6.4 / §10 P2  

---

### Task 1：L4 中置信 → route_clarify

**Files:**
- Modify: `src/app/modules/intent/decision.py`（`agent_candidates`）
- Modify: `src/app/modules/intent/funnel.py`
- Create: `tests/test_intent_funnel_p2.py`

- [x] 测：L3 返回 kb_lookup conf=0.6 → 裁决为 `route_clarify`，slots 含 `clarify_kind=kb_confirm` 与 query
- [x] 测：conf≥0.75 的 kb_lookup 仍直通
- [x] 实现 L4 中间带转换；`to_meta` 带上 clarify 相关字段

### Task 2：runtime 下发澄清卡 + card-action 续跑

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`
- Create/Modify: `tests/test_route_clarify_p2.py`

- [x] 测：中置信问法 SSE 出 `card.type=route_clarify`，`status=awaiting_card`
- [x] 测：选择 `kb_lookup` → 续跑走 RAG/D14；选择 `chitchat` → 不查库
- [x] 实现 `build_route_clarify_card`；`stream_mock_reply` 处理 `route_clarify`；增强 `stream_after_card_action`（读卡 payload.meta）

### Task 3：文档

- [x] 更新设计状态 P2；CHECKPOINT；计划勾选
