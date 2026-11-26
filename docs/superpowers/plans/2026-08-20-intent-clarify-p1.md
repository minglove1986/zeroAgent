# 意图链路 · P1

> **Goal:** 办理 vs 咨询澄清卡；`skill_id` 路由可观测对齐。  
> **不做：** L3 管理端 UI（规格标可选，本期跳过）。

**Spec:** `2026-08-20-intent-clarify-architecture.md` P1

### Tasks

1. `needs_handle_or_ask` + L4 中置信出 `clarify_kind=handle_or_ask`
2. 出卡文案/选项；card-action：办理→请假/技能路径，咨询→kb，闲聊→跳过
3. `intent_to_route` / meta 保留 `skill_id`；有 skill_id+agent 进 PE
4. 单测 + CHECKPOINT
