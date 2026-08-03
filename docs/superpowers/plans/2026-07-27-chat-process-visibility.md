# 系统对话过程可见 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 系统对话在流式过程中展示阶段胶囊 + 可折叠合成「思考过程」，类似豆包；过程不落库。

**Architecture:** 后端用 `process_narration` 合成 `stage` / `thought_delta` SSE；Plan-Execute 经 `graph.astream(updates)` 边跑边报；legacy/闲聊路径补同类事件。前端用纯函数归并过程态 + `ProcessPanel` 挂在助手气泡上方，历史加载不恢复。

**Tech Stack:** FastAPI SSE、LangGraph `astream`、pytest、Next.js `web/src/app/chat`。

**Spec:** `docs/superpowers/specs/2026-07-27-chat-process-visibility-design.md`

## Global Constraints

- 单租户，禁止 `tenant_id`
- 过程事件 **不写入** `messages.meta` / 新表
- `thought_delta` 仅合成人话：禁止 plan JSON、工具 arguments、观测全文、密钥
- LLM 只经 LiteLLM；不做 OpenIM；不做模型原生 reasoning token
- `@author 赵振明`；注释时间用东八区实时
- 本仓约定：**仅用户明确要求时 git commit**（下列 Commit 步骤默认跳过，除非用户指令）
- 一个 Task 一次：先测后写

## File Structure

| 文件 | 职责 |
|---|---|
| `src/app/modules/conversation/process_narration.py` | 阶段枚举、label、enter/done/error → SSE 载荷与叙述句 |
| `tests/test_process_narration.py` | 合成器单测 |
| `src/app/modules/agent/graph/plan_execute.py` | 新增 `stream_plan_execute`（astream）；`run_plan_execute` 包装兼容 |
| `src/app/modules/agent/graph/build.py` | `stream_agent_turn` 门面（可选薄封装） |
| `src/app/modules/conversation/runtime.py` | `_stream_plan_execute` / `_stream_skill_fc` / 闲聊路径 yield 过程事件 |
| `tests/test_chat_process_visibility.py` | SSE 事件顺序与「过程不入 meta」 |
| `docs/01-产品需求/API接口规范.md` | §10.1 增补 `stage` / `thought_delta` |
| `web/src/lib/chatProcess.ts` | 过程态归并纯函数 |
| `web/src/components/ProcessPanel.tsx` | 阶段胶囊 + 可折叠思考 |
| `web/src/app/chat/page.tsx` | SSE 接线与挂载 |
| `web/src/app/chat/chat.css` 或现有全局样式 | 过程区轻量样式（若样式在 page 旁 css / globals，跟现有习惯） |

---

### Task 1：过程叙述合成器 + API 文档

**Files:**
- Create: `src/app/modules/conversation/process_narration.py`
- Create: `tests/test_process_narration.py`
- Modify: `docs/01-产品需求/API接口规范.md`（§10.1 表）

**Interfaces:**
- Produces:
  - `StageId = Literal["understand", "plan", "retrieve", "skill", "respond"]`
  - `STAGE_LABELS: dict[StageId, str]`
  - `def stage_event(stage_id: StageId, status: Literal["running","done","error"]) -> dict[str, Any]`
  - `def thought_for(stage_id: StageId, action: Literal["enter","done","error"], *, skill_name: str | None = None) -> str`
  - `def iter_stage_enter(stage_id: StageId, *, skill_name: str | None = None) -> list[tuple[str, dict[str, Any]]]`  
    （返回 `[("stage", {...running}), ("thought_delta", {"delta": "..."})]`）
  - `def iter_stage_leave(stage_id: StageId, *, ok: bool = True, skill_name: str | None = None) -> list[tuple[str, dict[str, Any]]]`

- [ ] **Step 1: 写失败单测**

```python
"""过程叙述合成器单测。

@author 赵振明
@date <东八区实时>
"""

from app.modules.conversation.process_narration import (
    iter_stage_enter,
    iter_stage_leave,
    thought_for,
)


def test_enter_understand_emits_stage_and_thought():
    events = iter_stage_enter("understand")
    assert events[0][0] == "stage"
    assert events[0][1] == {
        "id": "understand",
        "label": "理解问题",
        "status": "running",
    }
    assert events[1][0] == "thought_delta"
    assert "理解" in events[1][1]["delta"]


def test_skill_enter_uses_display_name_not_json():
    events = iter_stage_enter("skill", skill_name="文档理解")
    joined = "".join(
        e[1].get("delta", "") for e in events if e[0] == "thought_delta"
    )
    assert "文档理解" in joined
    assert "{" not in joined
    assert "arguments" not in joined.lower()


def test_leave_error_status():
    events = iter_stage_leave("retrieve", ok=False)
    assert events[0] == (
        "stage",
        {"id": "retrieve", "label": "检索知识库", "status": "error"},
    )


def test_thought_templates_have_no_secret_shaped_leak():
    for sid in ("understand", "plan", "retrieve", "skill", "respond"):
        for action in ("enter", "done", "error"):
            t = thought_for(sid, action, skill_name="请假助手")
            assert "sk-" not in t
            assert "api_key" not in t.lower()
```

- [ ] **Step 2: 跑测确认失败**

```powershell
cd D:\HermesWork\zeroAgent
$env:PYTHONPATH="src"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_process_narration.py -v
```

Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `process_narration.py`**

```python
"""对话过程可见：阶段与合成叙述（不落库）。

@author 赵振明
@date <东八区实时>
"""

from __future__ import annotations

from typing import Any, Literal

StageId = Literal["understand", "plan", "retrieve", "skill", "respond"]
StageStatus = Literal["running", "done", "error"]
StageAction = Literal["enter", "done", "error"]

STAGE_LABELS: dict[StageId, str] = {
    "understand": "理解问题",
    "plan": "规划中",
    "retrieve": "检索知识库",
    "skill": "调用技能",
    "respond": "整理回答",
}

_ENTER_THOUGHT: dict[StageId, str] = {
    "understand": "正在理解你的问题…",
    "plan": "正在规划执行步骤…",
    "retrieve": "正在检索知识库…",
    "skill": "正在调用技能…",
    "respond": "正在整理回答…",
}

_DONE_THOUGHT: dict[StageId, str] = {
    "understand": "已理解问题。",
    "plan": "规划完成。",
    "retrieve": "检索完成。",
    "skill": "技能调用完成。",
    "respond": "回答已就绪。",
}

_ERROR_THOUGHT: dict[StageId, str] = {
    "understand": "理解问题失败。",
    "plan": "规划失败。",
    "retrieve": "检索未成功。",
    "skill": "技能调用失败。",
    "respond": "整理回答失败。",
}


def stage_event(stage_id: StageId, status: StageStatus) -> dict[str, Any]:
    """构造 stage SSE 载荷。"""
    return {
        "id": stage_id,
        "label": STAGE_LABELS[stage_id],
        "status": status,
    }


def thought_for(
    stage_id: StageId,
    action: StageAction,
    *,
    skill_name: str | None = None,
) -> str:
    """返回合成人话；skill 可用展示名，不拼 JSON。"""
    if action == "enter":
        base = _ENTER_THOUGHT[stage_id]
        if stage_id == "skill" and skill_name:
            return f"正在调用技能「{skill_name}」…"
        return base
    if action == "error":
        base = _ERROR_THOUGHT[stage_id]
        if stage_id == "skill" and skill_name:
            return f"技能「{skill_name}」调用失败。"
        return base
    base = _DONE_THOUGHT[stage_id]
    if stage_id == "skill" and skill_name:
        return f"技能「{skill_name}」调用完成。"
    return base


def iter_stage_enter(
    stage_id: StageId,
    *,
    skill_name: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """进入阶段：running + 一句 thought。"""
    return [
        ("stage", stage_event(stage_id, "running")),
        (
            "thought_delta",
            {"delta": thought_for(stage_id, "enter", skill_name=skill_name)},
        ),
    ]


def iter_stage_leave(
    stage_id: StageId,
    *,
    ok: bool = True,
    skill_name: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """离开阶段：done/error + 一句 thought。"""
    status: StageStatus = "done" if ok else "error"
    action: StageAction = "done" if ok else "error"
    return [
        ("stage", stage_event(stage_id, status)),
        (
            "thought_delta",
            {"delta": thought_for(stage_id, action, skill_name=skill_name)},
        ),
    ]
```

- [ ] **Step 4: 跑测通过**

同 Step 2 命令。Expected: PASS

- [ ] **Step 5: 更新 API 文档 §10.1**

在事件表中增加两行：

| `stage` | 过程阶段胶囊：`{id,label,status}`；`status`=`running`/`done`/`error`；仅流式，不落库 |
| `thought_delta` | 合成思考叙述增量：`{delta}`；仅流式，不落库 |

并在表下加一句：用户默认 UI 以 `stage`/`thought_delta` 为主；`tool_call`/`skill_call` 仍可选，默认不展示 arguments。

- [ ] **Step 6: Commit（仅用户要求时）**

---

### Task 2：Plan-Execute 流式出口（astream → 过程事件）

**Files:**
- Modify: `src/app/modules/agent/graph/plan_execute.py`
- Modify: `src/app/modules/agent/graph/build.py`（增加 `stream_agent_turn`）
- Modify: `tests/test_plan_execute_graph.py`（兼容：`run_plan_execute` 行为不变）
- Create/Modify: `tests/test_chat_process_visibility.py`（本 Task 写「stream 产出过程事件」单测）

**Interfaces:**
- Consumes: `iter_stage_enter` / `iter_stage_leave` from Task 1
- Produces:
  - `async def stream_plan_execute(...) -> AsyncIterator[tuple[str, dict[str, Any]]]`  
    过程中 yield `stage`/`thought_delta`；**最后** yield `("__result__", result_dict)`，其中 `result_dict` 与现 `run_plan_execute` 返回结构一致（`ok/answer/citations/plan/deferred_card?/error?`）
  - `async def run_plan_execute(...):` 改为消费 `stream_plan_execute`，只返回 `__result__` 的 dict（对外签名不变）
  - `async def stream_agent_turn(...)`：同参透传 `stream_plan_execute`

**映射规则（写入实现注释）：**

1. 启动：`understand` enter → leave(ok)
2. 在 `async for update in graph.astream(..., stream_mode="updates")` 前：`plan` enter
3. 收到节点 key `plan`：`plan` leave；若随后有 execute，按步骤 kind 再 enter 对应阶段
4. 收到 `execute`：看更新后 `plan` 列表中刚完成的那一步（`plan_cursor-1`）：
   - `rag_search` → 若尚未 enter retrieve 则先 enter，再 leave（ok 看 step.status）
   - `execute_skill` / `call_agent` → `skill`（`skill_name` 从 catalog 按 skill_id 取 `name`）
   - `respond` → `respond` enter/leave
5. 收到 `aggregate`：若尚未 `respond`，补 `respond` enter/leave
6. 循环结束：组装与现逻辑相同的 `result`，yield `("__result__", result)`
7. **禁止**把 observation / plan 原文放进 `thought_delta`

- [ ] **Step 1: 写失败单测（流式过程事件）**

在 `tests/test_chat_process_visibility.py`：

```python
"""对话过程可见：SSE 过程事件。

@author 赵振明
@date <东八区实时>
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.modules.agent.graph.plan_execute import stream_plan_execute


@pytest.mark.asyncio
async def test_stream_plan_execute_emits_stages_before_result(monkeypatch):
    """Mock astream：先 plan 节点，再 execute(rag)，再 aggregate。"""

    async def fake_astream(*_a, **_k):
        yield {
            "plan": {
                "plan": [
                    {"id": "s1", "kind": "rag_search", "status": "pending"},
                    {"id": "s2", "kind": "respond", "status": "pending"},
                ],
                "plan_cursor": 0,
            }
        }
        yield {
            "execute": {
                "plan": [
                    {
                        "id": "s1",
                        "kind": "rag_search",
                        "status": "done",
                        "observation": "obs",
                    },
                    {"id": "s2", "kind": "respond", "status": "pending"},
                ],
                "plan_cursor": 1,
                "citations": [{"title": "t", "snippet": "s"}],
            }
        }
        yield {
            "execute": {
                "plan": [
                    {
                        "id": "s1",
                        "kind": "rag_search",
                        "status": "done",
                        "observation": "obs",
                    },
                    {
                        "id": "s2",
                        "kind": "respond",
                        "status": "done",
                        "observation": "最终答案",
                    },
                ],
                "plan_cursor": 2,
                "final_answer": "最终答案",
                "citations": [{"title": "t", "snippet": "s"}],
            }
        }
        yield {"aggregate": {"final_answer": "最终答案", "ok": True}}

    class FakeGraph:
        def astream(self, *_a, **_k):
            return fake_astream()

    monkeypatch.setattr(
        "app.modules.agent.graph.plan_execute.get_plan_execute_graph",
        lambda: FakeGraph(),
    )
    monkeypatch.setattr(
        "app.modules.agent.graph.plan_execute.load_agent_skill_catalog",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.modules.agent.graph.plan_execute.build_turn_context_blocks",
        AsyncMock(
            return_value=type(
                "B",
                (),
                {"system_sections": lambda self: []},
            )()
        ),
    )

    db = AsyncMock()
    events: list[tuple[str, dict]] = []
    result = None
    async for ev, data in stream_plan_execute(
        db=db,
        agent_id="ag_x",
        user_content="查知识库：差旅",
        user_id="u1",
        conversation_id="c1",
    ):
        if ev == "__result__":
            result = data
        else:
            events.append((ev, data))

    kinds = [e[0] for e in events]
    assert "stage" in kinds
    assert "thought_delta" in kinds
    stage_ids = [e[1]["id"] for e in events if e[0] == "stage"]
    assert "understand" in stage_ids
    assert "plan" in stage_ids
    assert "retrieve" in stage_ids
    assert result is not None
    assert result["answer"] == "最终答案"
    # 叙述不含 observation 原文泄漏策略：至少不含完整 obs 作为唯一内容时可放宽
    thoughts = "".join(
        e[1].get("delta", "") for e in events if e[0] == "thought_delta"
    )
    assert "arguments" not in thoughts.lower()
```

注意：若 `build_turn_context_blocks` mock 方式与真实返回类型不兼容，改为 patch `stream_plan_execute` 内部在无 user_id 时跳过 blocks（实现里已有 `if user_id and conversation_id`），本测可传齐 id 或传 `user_id=None` 简化。

- [ ] **Step 2: 跑测确认失败**

```powershell
cd D:\HermesWork\zeroAgent
$env:PYTHONPATH="src"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_chat_process_visibility.py::test_stream_plan_execute_emits_stages_before_result -v
```

Expected: FAIL（无 `stream_plan_execute`）

- [ ] **Step 3: 实现 `stream_plan_execute`，并让 `run_plan_execute` 调用它**

要点（实现时保持现有 catalog/context_system/config 组装逻辑，仅把 `ainvoke` 换成 `astream`）：

```python
async def stream_plan_execute(...) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    # ... 组装 catalog / context_system / initial state / config（同现 run_plan_execute）
    for item in iter_stage_enter("understand"):
        yield item
    for item in iter_stage_leave("understand", ok=True):
        yield item

    for item in iter_stage_enter("plan"):
        yield item

    final_state: dict[str, Any] = dict(initial)
    graph = get_plan_execute_graph()
    async for update in graph.astream(initial, config=config, stream_mode="updates"):
        # update: dict[node_name, partial_state]
        for node_name, partial in update.items():
            final_state.update(partial or {})
            if node_name == "plan":
                for item in iter_stage_leave("plan", ok=True):
                    yield item
            elif node_name == "execute":
                plan = list(final_state.get("plan") or [])
                cursor = int(final_state.get("plan_cursor") or 0)
                if cursor <= 0:
                    continue
                step = plan[cursor - 1]
                kind = str(step.get("kind") or "")
                ok = str(step.get("status") or "") != "failed"
                skill_name = None
                if kind == "execute_skill":
                    sid = step.get("skill_id")
                    for c in catalog:
                        if c.get("id") == sid:
                            skill_name = str(c.get("name") or sid)
                            break
                stage_id = {
                    "rag_search": "retrieve",
                    "execute_skill": "skill",
                    "call_agent": "skill",
                    "respond": "respond",
                }.get(kind)
                if stage_id:
                    for item in iter_stage_enter(stage_id, skill_name=skill_name):
                        yield item
                    for item in iter_stage_leave(
                        stage_id, ok=ok, skill_name=skill_name
                    ):
                        yield item
            elif node_name == "aggregate":
                # 若尚无 respond 阶段，可补一轮 respond enter/leave
                ...

    result = {
        "ok": bool(final_state.get("ok", True)) and not final_state.get("error"),
        "answer": str(final_state.get("final_answer") or ""),
        "citations": list(final_state.get("citations") or []),
        "plan": list(final_state.get("plan") or []),
    }
    # deferred_card / error 同现逻辑
    yield ("__result__", result)


async def run_plan_execute(...) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "answer": "", "citations": [], "plan": []}
    async for ev, data in stream_plan_execute(...):
        if ev == "__result__":
            result = data
    return result
```

`build.py` 增加：

```python
async def stream_agent_turn(...) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    async for item in stream_plan_execute(...):
        yield item
```

- [ ] **Step 4: 跑本测 + 原 plan_execute 回归**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_chat_process_visibility.py::test_stream_plan_execute_emits_stages_before_result tests/test_plan_execute_graph.py -v
```

Expected: PASS

- [ ] **Step 5: Commit（仅用户要求时）**

---

### Task 3：runtime 对接 Plan-Execute 过程事件

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`（`_stream_plan_execute`）
- Modify: `tests/test_chat_process_visibility.py`（增加 HTTP SSE 或直接测 `_stream_plan_execute`）

**Interfaces:**
- Consumes: `stream_agent_turn` / `stream_plan_execute`（推荐从 `build.stream_agent_turn`）
- Produces: `_stream_plan_execute` 在 `content_delta` 之前透传所有非 `__result__` 事件；`persist` 的 `meta` **不得**含 `stage`/`thought` 列表

- [ ] **Step 1: 写失败/待实现断言**

```python
@pytest.mark.asyncio
async def test_stream_plan_execute_runtime_forwards_stages(monkeypatch):
    async def fake_stream(**_kwargs):
        yield ("stage", {"id": "understand", "label": "理解问题", "status": "running"})
        yield ("thought_delta", {"delta": "正在理解你的问题…"})
        yield (
            "__result__",
            {
                "ok": True,
                "answer": "你好",
                "citations": [],
                "plan": [{"kind": "respond", "status": "done"}],
            },
        )

    monkeypatch.setattr(
        "app.modules.conversation.runtime.stream_agent_turn",
        fake_stream,
    )
    # 再 mock persist_assistant_and_card / append_short_memory / _enqueue_extract
    ...
    events = []
    async for ev, data in _stream_plan_execute(...最小参数...):
        events.append((ev, data))
    assert events[0][0] == "stage"
    assert any(e[0] == "content_delta" for e in events)
    assert events[-1][0] == "message_end"
    # 抓 persist 调用的 meta
    meta = persist_mock.await_args.kwargs.get("meta") or persist_mock.call_args[1]["meta"]
    assert "thoughts" not in meta
    assert "stages" not in meta
```

实现时按项目现有 mock 风格补全（可参考 `tests/test_plan_execute_graph.py` 的 `_parse_sse` + ASGI，或直接测 async generator）。

- [ ] **Step 2: 跑测确认失败**（若仍用 `run_agent_turn` 整包返回则断言失败）

- [ ] **Step 3: 改写 `_stream_plan_execute`**

```python
async def _stream_plan_execute(...) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    result: dict[str, Any] | None = None
    async for ev, data in stream_agent_turn(...同参...):
        if ev == "__result__":
            result = data
            continue
        yield ev, data

    assert result is not None
    plan = list(result.get("plan") or [])
    # 以下保持现有 D14 / citation / content_delta / persist / card / message_end 逻辑
    # 若 D14 拒展：在 notice 前可 iter_stage_leave("retrieve", ok=False) 或 respond error（与规格 §5.4 对齐）
    ...
```

D14 分支建议：在吐拒展文案前 `yield` `iter_stage_leave("retrieve", ok=False)` 与/或 `respond` error 一句（若本轮用过 rag）。

- [ ] **Step 4: 跑测通过 + 回归**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_chat_process_visibility.py tests/test_plan_execute_graph.py tests/test_context_source_boundary.py -v
```

- [ ] **Step 5: Commit（仅用户要求时）**

---

### Task 4：legacy 技能 FC + 闲聊路径补过程事件

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`（`_stream_skill_fc`、闲聊/直答分支）
- Modify: `tests/test_chat_process_visibility.py`

**Interfaces:**
- Consumes: `iter_stage_enter` / `iter_stage_leave`
- 行为：
  - `_stream_skill_fc` 开头：`understand` enter/leave
  - 每轮有 `tool_calls` 且非仅收尾：对每个非 `ask_user` 工具 `skill` enter（展示名=tool name）→ 现有 `tool_call` yield → 执行后 leave；`ask_user`：leave 当前/`skill` done + thought「需要你补充信息」→ 再 card
  - 无工具直接正文：`respond` enter → content_delta → leave
  - 闲聊路径（`path=chitchat` 等直答）：同样 `understand` + `respond`

- [ ] **Step 1: 单测**

```python
@pytest.mark.asyncio
async def test_chitchat_emits_understand_and_respond(monkeypatch):
    # mock intent → chitchat，mock LLM 返回固定句
    # 解析 SSE 或直接收集 stream_mock_reply 事件
    stage_ids = [d["id"] for e, d in events if e == "stage"]
    assert stage_ids.count("understand") >= 1
    assert "respond" in stage_ids
```

```python
@pytest.mark.asyncio
async def test_skill_fc_ask_user_has_need_info_thought(monkeypatch):
    # AGENT_RUNTIME=legacy；mock chat_completion_with_tools 返回 ask_user
    thoughts = "".join(d.get("delta","") for e,d in events if e=="thought_delta")
    assert "补充信息" in thoughts
    assert any(e == "card" for e, _ in events)
```

- [ ] **Step 2: 实现最小插入 yield（勿改 FC 业务语义）**

- [ ] **Step 3: 跑测**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_chat_process_visibility.py tests/test_message_card_action.py tests/test_route_clarify_p2.py -v
```

- [ ] **Step 4: Commit（仅用户要求时）**

---

### Task 5：前端过程态 + ProcessPanel

**Files:**
- Create: `web/src/lib/chatProcess.ts`
- Create: `web/src/components/ProcessPanel.tsx`
- Modify: `web/src/app/chat/page.tsx`
- Modify: 现有 chat 样式文件（检索 `chat-stream` / `msg-assistant` 所在 css，跟仓内习惯追加 `.process-panel` 等）

**Interfaces:**
- Produces (`chatProcess.ts`):

```typescript
export type StageStatus = "running" | "done" | "error";
export type ProcessStage = { id: string; label: string; status: StageStatus };
export type LiveProcess = {
  stages: ProcessStage[];
  thought: string;
  collapsed: boolean;
};

export function emptyProcess(): LiveProcess;
export function applyProcessEvent(
  prev: LiveProcess,
  event: string,
  data: Record<string, unknown>,
): LiveProcess;
export function collapseProcess(prev: LiveProcess): LiveProcess;
```

`applyProcessEvent`：
- `stage`：按 `id` upsert `label/status`
- `thought_delta`：`thought += String(data.delta ?? "")`（可自动在句间加 `\n` 若 delta 不以换行结尾且 thought 非空）
- 其他 event：原样返回 prev

- [ ] **Step 1: 实现 `chatProcess.ts`（纯函数，便于手工推理）**

```typescript
export function applyProcessEvent(
  prev: LiveProcess,
  event: string,
  data: Record<string, unknown>,
): LiveProcess {
  if (event === "stage") {
    const id = String(data.id ?? "");
    const label = String(data.label ?? id);
    const status = data.status as StageStatus;
    const stages = [...prev.stages];
    const idx = stages.findIndex((s) => s.id === id);
    if (idx >= 0) stages[idx] = { id, label, status };
    else stages.push({ id, label, status });
    return { ...prev, stages, collapsed: false };
  }
  if (event === "thought_delta") {
    const delta = String(data.delta ?? "");
    const thought =
      prev.thought && !prev.thought.endsWith("\n")
        ? `${prev.thought}\n${delta}`
        : `${prev.thought}${delta}`;
    return { ...prev, thought, collapsed: false };
  }
  return prev;
}
```

- [ ] **Step 2: 实现 `ProcessPanel.tsx`**

- props: `process: LiveProcess`；`onToggle: () => void`
- 渲染阶段胶囊 + `<button>` 折叠标题「思考过程」+ 纯文本 `<pre>`/`<div className="process-thought">`（**不要**走 `MarkdownBody`）
- `process.collapsed === true` 时隐藏 thought 正文，仍可显示阶段行（或一并收起 thought 仅留标题——规格：折叠块收起；阶段行可保留）

- [ ] **Step 3: 接入 `page.tsx`**

1. 扩展 assistant `ChatItem`：可选 `process?: LiveProcess`
2. `sendText` / retry / card-action 的 SSE 回调：
   - 对新一轮开始时：旧 assistant 的 `process` 可删掉（仅保留 busy 一轮）
   - `stage`/`thought_delta`：`flushSync` 更新当前 assistant 的 `process`（若尚无 assistant 条，先 push 空 text 的 assistant + process）
   - `message_end`：`collapseProcess`
3. `messagesToItems` / 加载历史：**不**附加 process
4. 渲染：`item.kind==="assistant"` 时在 `MarkdownBody` **上方**挂 `<ProcessPanel />`

- [ ] **Step 4: 手工验收清单（本仓 web 无 vitest）**

- [ ] 走 RAG/技能问题：可见阶段推进 + 思考展开，再出正文
- [ ] `message_end` 后思考自动折叠，可再点开
- [ ] 刷新后过程区消失
- [ ] 过程区无 JSON/arguments
- [ ] 提问卡 / D14 拒展仍正常

- [ ] **Step 5: Commit（仅用户要求时）**

---

### Task 6：回归收口 + CHECKPOINT

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`
- Modify: `docs/superpowers/specs/2026-07-27-chat-process-visibility-design.md`（状态 → 已实现）
- Modify: 本计划勾选框

- [ ] **Step 1: 跑回归包**

```powershell
cd D:\HermesWork\zeroAgent
$env:PYTHONPATH="src"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest `
  tests/test_process_narration.py `
  tests/test_chat_process_visibility.py `
  tests/test_plan_execute_graph.py `
  tests/test_context_source_boundary.py `
  tests/test_chat_routing_hotfix.py `
  tests/test_route_clarify_p2.py `
  tests/test_message_card_action.py -v
```

Expected: 全部 PASS

- [ ] **Step 2: 更新 CHECKPOINT**（顶部覆盖 + 日志追加）；规格状态改「已实现」

- [ ] **Step 3: Commit（仅用户要求时）**

---

## Self-Review（写计划时已核对）

| 规格条目 | 对应 Task |
|---|---|
| stage / thought_delta 协议 | T1 |
| 合成人话、不落库 | T1 / T3 meta 断言 |
| Plan-Execute astream | T2–T3 |
| legacy FC / 闲聊 / ask_user 叙述 | T4 |
| 前端过程面板与历史不恢复 | T5 |
| 测试与验收 / CHECKPOINT | T6 |
| API 文档 §10.1 | T1 |

无 TBD；`__result__` 哨兵事件仅内部使用，不写入 API 文档。
