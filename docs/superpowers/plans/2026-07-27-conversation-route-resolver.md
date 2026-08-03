# 对话路由收束（RouteResolver）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将意图识别与执行解耦：统一 `RouteResolver` → Dispatcher；消灭系统侧「kb 拼片段」捷径；绑 Agent 只走 AgentRuntime 并落 `meta.route`。

**Architecture:** `resolve_route` 包装现有 L2/L3/L4 漏斗产出 `RouteDecision`；`stream_mock_reply` 按「澄清 / 无 Agent SystemHandler / 有 Agent Runtime」三岔分发；System `kb_lookup` 改为检索 + 短合成 + D14 + 过程事件；L3 Mock 改为黄金用例 fixture。

**Tech Stack:** FastAPI runtime、现有 intent funnel、LiteLLM、pytest、过程可见 `process_narration`。

**Spec:** `docs/superpowers/specs/2026-07-27-conversation-route-resolver-design.md`

## Global Constraints

- 单租户，禁止 `tenant_id`
- L2 禁止再加「我是谁」类模糊口令 / 自我身份白名单
- 有 `agent_id`：**禁止**系统 kb/doc 拼片段捷径
- 澄清类（`clarify_kb` / `clarify_agent`）无论是否绑 Agent 先出卡
- 过程事件复用 `stage` / `thought_delta`，不落库过程字段
- `@author 赵振明`；注释时间东八区实时
- 本仓约定：**仅用户明确要求时 git commit**（下列 Commit 步骤默认跳过）

## File Structure

| 文件 | 职责 |
|---|---|
| `src/app/modules/conversation/route.py` | `RouteKind`、`RouteDecision`、`intent_to_route`、`resolve_route` |
| `tests/test_conversation_route.py` | Resolver 映射与分发策略单测 |
| `src/app/modules/conversation/handlers/kb_lookup.py` | System kb：检索 + 合成 + D14 + stage |
| `src/app/modules/conversation/handlers/__init__.py` | 导出 |
| `src/app/modules/conversation/runtime.py` | Dispatcher 瘦身；调用 resolve + handlers |
| `src/app/modules/intent/classifier.py` | L3 prompt 身份条款；Mock → fixture |
| `src/app/modules/intent/l3_fixtures.py` | 黄金用例表 |
| `src/app/modules/intent/funnel.py` | `evaluate_intent_funnel` → `evaluate_l2_only` 别名 |
| `tests/test_intent_l3_fixtures.py` | fixture 行为 |
| `tests/test_kb_lookup_handler.py` | 合成路径非纯拼接 |

---

### Task 1：RouteDecision + resolve_route

**Files:**
- Create: `src/app/modules/conversation/route.py`
- Create: `tests/test_conversation_route.py`
- Modify: `src/app/modules/intent/funnel.py`（可选：导出供 resolve 调用，不改语义）

**Interfaces:**
- Produces:
  - `RouteKind = Literal["kb_lookup","doc_analyze","ask_form","chitchat","clarify_kb","clarify_agent","reject"]`
  - `@dataclass RouteDecision`: `kind`, `query`, `confidence`, `layer`, `reason`, `slots: dict`, `features: list[str]`, `handler: str`（`system`|`agent`|`clarify`）
  - `def intent_to_route(intent: IntentDecision, *, agent_id: str | None) -> RouteDecision`
  - `async def resolve_route(user_content: str, *, agent_id: str | None = None, recent_summary: str = "", kb_names: list[str] | None = None) -> RouteDecision`
- 映射规则：
  - `intent.intent == "route_clarify"` 且 `slots.clarify_kind == "kb_confirm"` → `clarify_kb`，`handler=clarify`
  - `clarify_kind == "agent_pick"` → `clarify_agent`，`handler=clarify`
  - `ask_user_form` → `ask_form`；有无 Agent 均 `handler=system`（P0 系统卡）
  - `kb_lookup` / `doc_analyze` / `chitchat` / `reject`：无 `agent_id` → `handler=system`；有 `agent_id` → `handler=agent`
  - `skill_task` / `call_agent`：有 Agent → `handler=agent` kind 可映射为 `chitchat` 或保留经 slots；P0 映射为 `chitchat` + agent handler

- [x] **Step 1: 写失败单测**

```python
"""RouteResolver 单测。

@author 赵振明
@date <东八区实时>
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.modules.conversation.route import intent_to_route, resolve_route
from app.modules.intent.decision import IntentDecision


def test_kb_without_agent_is_system_handler():
    d = IntentDecision(
        intent="kb_lookup",
        confidence=0.9,
        funnel_layer="L2",
        query="唐亮",
        reason="lexicon",
    )
    r = intent_to_route(d, agent_id=None)
    assert r.kind == "kb_lookup"
    assert r.handler == "system"


def test_kb_with_agent_is_agent_handler_not_system_shortcut():
    d = IntentDecision(
        intent="kb_lookup",
        confidence=0.9,
        funnel_layer="L2",
        query="唐亮",
        reason="lexicon",
    )
    r = intent_to_route(d, agent_id="ag_1")
    assert r.kind == "kb_lookup"
    assert r.handler == "agent"


def test_clarify_kb_always_clarify_handler_even_with_agent():
    d = IntentDecision(
        intent="route_clarify",
        confidence=0.6,
        funnel_layer="L4",
        query="q",
        reason="mid",
        slots={"clarify_kind": "kb_confirm"},
    )
    r = intent_to_route(d, agent_id="ag_1")
    assert r.kind == "clarify_kb"
    assert r.handler == "clarify"


@pytest.mark.asyncio
async def test_resolve_route_calls_funnel(monkeypatch):
    async def fake_funnel(text, **kwargs):
        return IntentDecision(
            intent="chitchat",
            confidence=0.8,
            funnel_layer="L3",
            query=text,
            reason="l3",
        )

    monkeypatch.setattr(
        "app.modules.conversation.route.evaluate_intent_funnel_async",
        fake_funnel,
    )
    r = await resolve_route("我是谁", agent_id=None, recent_summary="pref")
    assert r.kind == "chitchat"
    assert r.handler == "system"
```

- [ ] **Step 2: 跑测确认失败**

```powershell
cd D:\HermesWork\zeroAgent
$env:PYTHONPATH="src"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_conversation_route.py -v
```

Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `route.py`**

```python
"""对话路由：IntentDecision → RouteDecision。

@author 赵振明
@date <东八区实时>
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.modules.intent.decision import IntentDecision
from app.modules.intent.funnel import evaluate_intent_funnel_async

RouteKind = Literal[
    "kb_lookup",
    "doc_analyze",
    "ask_form",
    "chitchat",
    "clarify_kb",
    "clarify_agent",
    "reject",
]
HandlerKind = Literal["system", "agent", "clarify"]


@dataclass
class RouteDecision:
    kind: RouteKind
    query: str
    confidence: float
    layer: str
    reason: str
    handler: HandlerKind
    slots: dict[str, Any] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        return {
            "route": {
                "kind": self.kind,
                "handler": self.handler,
                "confidence": self.confidence,
                "layer": self.layer,
                "reason": self.reason,
                "query": self.query,
            }
        }


def intent_to_route(
    intent: IntentDecision,
    *,
    agent_id: str | None,
) -> RouteDecision:
    """将漏斗结果映射为路由决策。"""
    slots = dict(intent.slots or {})
    features = list(intent.features or [])
    q = str(intent.query or "")
    conf = float(intent.confidence)
    layer = str(intent.funnel_layer or "")
    reason = str(intent.reason or "")

    if intent.intent == "route_clarify":
        ck = str(slots.get("clarify_kind") or "")
        if ck == "agent_pick":
            kind: RouteKind = "clarify_agent"
        else:
            kind = "clarify_kb"
        return RouteDecision(
            kind=kind,
            query=q,
            confidence=conf,
            layer=layer,
            reason=reason,
            handler="clarify",
            slots=slots,
            features=features,
        )

    if intent.intent == "ask_user_form":
        return RouteDecision(
            kind="ask_form",
            query=q,
            confidence=conf,
            layer=layer,
            reason=reason,
            handler="system",
            slots=slots,
            features=features,
        )

    if intent.intent == "reject":
        return RouteDecision(
            kind="reject",
            query=q,
            confidence=conf,
            layer=layer,
            reason=reason,
            handler="system",
            slots=slots,
            features=features,
        )

    kind_map: dict[str, RouteKind] = {
        "kb_lookup": "kb_lookup",
        "doc_analyze": "doc_analyze",
        "chitchat": "chitchat",
        "skill_task": "chitchat",
        "call_agent": "chitchat",
    }
    kind = kind_map.get(str(intent.intent), "chitchat")
    handler: HandlerKind = "agent" if agent_id else "system"
    return RouteDecision(
        kind=kind,
        query=q,
        confidence=conf,
        layer=layer,
        reason=reason,
        handler=handler,
        slots=slots,
        features=features,
    )


async def resolve_route(
    user_content: str,
    *,
    agent_id: str | None = None,
    recent_summary: str = "",
    kb_names: list[str] | None = None,
) -> RouteDecision:
    """完整路由：漏斗 → RouteDecision。"""
    intent = await evaluate_intent_funnel_async(
        user_content,
        recent_summary=recent_summary,
        kb_names=kb_names,
    )
    return intent_to_route(intent, agent_id=agent_id)
```

- [ ] **Step 4: 跑测通过**

- [ ] **Step 5: Commit（仅用户要求时）**

---

### Task 2：L3 fixture Mock + 身份条款 prompt

**Files:**
- Create: `src/app/modules/intent/l3_fixtures.py`
- Modify: `src/app/modules/intent/classifier.py`
- Create: `tests/test_intent_l3_fixtures.py`
- Modify: 依赖 `classify_intent_mock` 软正则的旧测（改为 fixture 或 async 黄金句）

**Interfaces:**
- Produces: `def lookup_l3_fixture(text: str) -> IntentDecision | None`
- `classify_intent_mock`：先查 fixture；未命中 → `chitchat` conf=0.3，`features=["mock:fixture_miss"]`；**删除** `_MOCK_SOFT_PERSON` 作为主路径（可删净）
- `_L3_SYSTEM` 增加一条：`用户问自己是谁/自己叫什么 → chitchat，禁止 kb_lookup`

Fixture 最少包含：

| 用户话 | intent |
|---|---|
| `我是谁` / `我到底是谁啊` | chitchat conf≥0.8 |
| `唐亮是谁` / `帮我看看唐亮是谁` | kb_lookup query=唐亮 |
| `差旅报销怎么报？` | kb_lookup reason=policy_doc |
| `帮我搜索赵世龙曾经在职的公司` | kb_lookup query 含赵世龙 |
| `今天天气怎么样` | chitchat |

- [ ] **Step 1: 单测 fixture**

```python
def test_who_am_i_fixture_is_chitchat():
    from app.modules.intent.classifier import classify_intent_mock
    d = classify_intent_mock("我是谁")
    assert d.intent == "chitchat"
    assert "mock:fixture" in (d.features or [])


def test_unknown_utterance_is_low_chitchat_not_soft_person_regex():
    d = classify_intent_mock("随便说点别的 xyz123")
    assert d.intent == "chitchat"
    assert d.confidence <= 0.35
```

- [ ] **Step 2: 实现 fixture 表 + 改 mock + 改 prompt**

- [ ] **Step 3: 跑**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_intent_l3_fixtures.py tests/test_intent_funnel_p0.py tests/test_intent_funnel_p1.py tests/test_chat_routing_hotfix.py -v
```

修断裂单测：凡依赖「Mock 软正则猜人物」的，改为 fixture 句或 L2 显式口令。

- [ ] **Step 4: Commit（仅用户要求时）**

---

### Task 3：Dispatcher 改造 stream_mock_reply

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`
- Modify: `tests/test_conversation_route.py`（增 dispatch 行为测，可 mock handlers）
- Modify: 现有 `test_plan_execute_graph.py` / `test_route_clarify_p2.py` 等回归

**Interfaces:**
- Consumes: `resolve_route`、`RouteDecision.to_meta()`
- `stream_mock_reply` 伪代码顺序：

```python
# 1) short memory append + lexicon refresh（保持）
summary = _short_memory_summary(...)  # 近轮 user/assistant 拼几句，可极简
route = await resolve_route(
    user_content,
    agent_id=agent_id,
    recent_summary=summary,
    kb_names=None,  # P0 可暂空；有现成 API 则传入
)
route_meta = route.to_meta()

if route.handler == "clarify":
    # 复用现 route_clarify / build_route_clarify_card 逻辑
    ...
    return

if route.handler == "agent" and agent_id and settings.agent_runtime == "langgraph":
    async for ev in _stream_plan_execute(..., msg_meta={**(msg_meta or {}), **route_meta}):
        yield ev
    return

if route.handler == "agent" and agent_id and tools:
    async for ev in _stream_skill_fc(..., msg_meta={**(msg_meta or {}), **route_meta}):
        yield ev
    return

# system handlers
if route.kind == "ask_form":
    ...  # 现请假卡
elif route.kind == "doc_analyze":
    ...  # 现 doc_analyze 块
elif route.kind == "kb_lookup":
    async for ev in handle_system_kb_lookup(...):  # Task4
        yield ev
elif route.kind == "reject":
    ...
else:  # chitchat
    ...  # 现闲聊 LLM 块
```

**硬约束：** 当 `route.handler == "agent"` 时，**不得**进入原 `intent.intent == "kb_lookup"` 拼片段分支。

- [ ] **Step 1: 单测（mock resolve + 断言走 agent 而非 kb handler）**

```python
@pytest.mark.asyncio
async def test_agent_bound_kb_route_skips_system_kb(monkeypatch):
    # resolve 返回 handler=agent kind=kb_lookup
    # mock _stream_plan_execute 记录调用
    # mock handle_system_kb_lookup 若被调用则 fail
    ...
```

- [ ] **Step 2: 改造 runtime Dispatcher**

- [ ] **Step 3: 回归**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_conversation_route.py tests/test_route_clarify_p2.py tests/test_plan_execute_graph.py tests/test_message_card_action.py -v
```

- [ ] **Step 4: Commit（仅用户要求时）**

---

### Task 4：System kb_lookup Handler（检索 + 合成）

**Files:**
- Create: `src/app/modules/conversation/handlers/__init__.py`
- Create: `src/app/modules/conversation/handlers/kb_lookup.py`
- Create: `tests/test_kb_lookup_handler.py`
- Modify: `runtime.py` 改为调用 handler

**Interfaces:**
- Produces:

```python
async def handle_system_kb_lookup(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
    user_content: str,
    route: RouteDecision,
    agent_id: str | None,
    department_ids: list[str] | None,
    role_ids: list[str] | None,
    is_platform_admin: bool,
    memory_access: str,
    allow_memory_write: bool,
    msg_meta: dict | None,
) -> AsyncIterator[tuple[str, dict]]:
    ...
```

行为：

1. `iter_stage_enter/leave`：understand → retrieve  
2. `run_kb_lookup`（query=`route.query` or parse）  
3. D14 失败：retrieve error + 拒展文案 + message_end  
4. 成功：retrieve done → respond enter → **合成答案**  
5. 合成策略（P0）：
   - `MOCK_EXTERNAL=true`：模板  
     `根据知识库资料，简要说明如下：\n- {title}: {snippet前80字}…`  
     **禁止**把原始 OCR 超长串无裁剪直接整段甩出；snippet 截断 120 字；最多 3 条  
   - 非 mock：`chat_completion` 短 system「仅基于引用作答，禁止编造」+ citations 文本  
6. yield citation 事件 + content_delta + persist（meta 含 `route.to_meta()`）+ message_end  
7. 过程 `respond` leave  

- [ ] **Step 1: 单测**

```python
@pytest.mark.asyncio
async def test_system_kb_answer_is_not_raw_ocr_dump(monkeypatch):
    # mock run_kb_lookup 返回超长 OCR snippet
    # 收集 content_delta
    # assert "根据知识库资料" in text or 合成前缀
    # assert len(text) < len(raw_snippet)  # 截断生效
    # assert 出现 stage retrieve
```

- [ ] **Step 2: 实现 handler 并接线**

- [ ] **Step 3: 跑测 + 旧 `test_chat_process_visibility::test_kb_lookup_path_emits_retrieve_stages` 适配新文案**

- [ ] **Step 4: Commit（仅用户要求时）**

---

### Task 5：recent_summary + evaluate_l2_only 命名

**Files:**
- Modify: `src/app/modules/intent/funnel.py`
- Modify: `src/app/modules/conversation/runtime.py`（`_build_recent_summary`）
- Modify: 所有 `evaluate_intent_funnel` 引用（测试可保留别名）

**Interfaces:**
- `evaluate_l2_only =` 原同步函数体；`evaluate_intent_funnel = evaluate_l2_only` 保留兼容别名并在 docstring 写明 **仅 L2，禁止用于生产 runtime**
- `_build_recent_summary(user_id, conversation_id) -> str`：从 `load_short_memory` 取最近 ≤6 条，格式 `user:…\nassistant:…`，总长截断 500

- [ ] **Step 1: 单测 summary 截断与 resolve 传入（mock funnel 捕获 kwargs）**

- [ ] **Step 2: 实现**

- [ ] **Step 3: 跑意图相关测**

- [ ] **Step 4: Commit（仅用户要求时）**

---

### Task 6：回归收口 + 规格状态

**Files:**
- Modify: `docs/superpowers/specs/2026-07-27-conversation-route-resolver-design.md`（状态 → 已实现）
- Modify: `docs/superpowers/CHECKPOINT.md`
- Modify: 本计划勾选

- [ ] **Step 1: 跑回归包**

```powershell
cd D:\HermesWork\zeroAgent
$env:PYTHONPATH="src"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest `
  tests/test_conversation_route.py `
  tests/test_intent_l3_fixtures.py `
  tests/test_kb_lookup_handler.py `
  tests/test_chat_process_visibility.py `
  tests/test_chat_routing_hotfix.py `
  tests/test_intent_funnel_p0.py `
  tests/test_intent_funnel_p1.py `
  tests/test_route_clarify_p2.py `
  tests/test_plan_execute_graph.py `
  tests/test_context_source_boundary.py `
  tests/test_message_card_action.py -v
```

Expected: 全部 PASS

- [ ] **Step 2: 更新 CHECKPOINT；规格标已实现**

- [ ] **Step 3: Commit（仅用户要求时）**

---

## Self-Review

| 规格条目 | Task |
|---|---|
| RouteDecision / Resolver | T1 |
| 有 Agent 不走系统 kb 捷径 | T3 |
| 澄清优先 | T1 映射 + T3 |
| System kb 合成 + D14 + stage | T4 |
| L3 fixture + 身份 prompt | T2 |
| recent_summary / l2_only 命名 | T5 |
| 回归 | T6 |

无 TBD；P1 Planner hint 明确不做。
