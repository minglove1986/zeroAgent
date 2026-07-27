# Task 3 Report — legacy / 闲聊路径统一分栏

**Status:** DONE  
**Time:** 2026-07-27 10:13:45（东八区）  
**Author:** 赵振明  
**Commits:** none（按指令未 git commit）

## Changes

- `src/app/modules/conversation/runtime.py`
  - 删除 `_IDENTITY_GUARD` 症状文案
  - `_build_llm_messages` 改为接收 `blocks: TurnContextBlocks`：system 用 `blocks.system_sections()`；短记忆作 chat roles（`short_turns[:-1]` + 当前 user）
  - `_stream_skill_fc` 与闲聊 LLM 路径：`await build_turn_context_blocks(...)`，去掉重复的 `list_long_memories` / `build_memory_system_prompt` / `load_short_memory`
- `tests/test_context_source_boundary.py`
  - 新增 `test_build_llm_messages_uses_boundary_not_symptom_only`（边界文案 + 短记忆 role 切面）

## Tests

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_context_source_boundary.py tests/test_chat_routing_hotfix.py -q --tb=line
```

**Result:** 13 passed

TDD：先红（`unexpected keyword argument 'blocks'`）后绿。

## Concerns

1. Plan-Execute `_execute_respond` 仍只注入 `context_system`（system 分栏），短记忆未作为 conversation role；与 legacy 行为尚未完全对称。
2. 若将来某调用点在 `append_short_memory(user)` **之前**调用 `_build_llm_messages`，`[:-1]` 会误切掉上一轮末条；当前仅 `stream_mock_reply` 入口先 append，与注释约定一致。

---

## Fix round（审查 Important 跟进）

**Time:** 2026-07-27 10:16:30（东八区）  
**Commits:** none

### 变更

- `tests/test_context_source_boundary.py`
  - `test_build_llm_messages_short_turns_append_contract`：锁定 `short_turns[:-1]` + `user_content` 契约，断言 `[user, assistant, user]` 仅末条 user 经 `user_content` 注入且无重复
  - `test_build_llm_messages_memory_access_none_smoke`：`build_turn_context_blocks(memory_access=none)` → `_build_llm_messages`，断言 system 不含 preference 文案

### 测试

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_context_source_boundary.py tests/test_chat_routing_hotfix.py -q --tb=line
```

**Result:** 15 passed

### 审查项关闭

| Important | 状态 |
|---|---|
| #1 `short[:-1]` 契约回归锁 | ✅ 单测 `test_build_llm_messages_short_turns_append_contract` |
| #2 legacy `memory_access=none` smoke | ✅ 单测 `test_build_llm_messages_memory_access_none_smoke` |
