# 对话上下文分栏注入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.  
> **规格：** `docs/superpowers/specs/2026-07-27-context-source-boundary-design.md`（已批准）

**Goal:** 每轮对话开始时分栏注入登录身份、长期记忆、短记忆与来源边界；修掉 Plan-Execute 丢弃 `memory_access`；检索/技能观察标注为第三人资料。

**Architecture:** 新建 `build_turn_context_blocks` 统一组装；Plan-Execute 与 legacy 共用；边界规则一段替换症状式 `_RESPOND_SYSTEM` / `_IDENTITY_GUARD`；RAG/技能观察经 `label_third_party_observation` 加前缀。

**Tech Stack:** FastAPI、SQLAlchemy async、现有 memory 服务、LangGraph Plan-Execute、pytest。

## Global Constraints

- 单租户；禁止 `tenant_id`
- 身份只来自 `users` 表，禁止从 KB/短记忆推断姓名
- `memory_access=none` 不注入记忆块；短记忆与边界仍可注入
- LLM 只经 LiteLLM；单测 Mock
- 注释 `@author 赵振明` + 东八区实时时间
- **不要**主动 `git commit`（除非用户明确要求）

## File map

| 路径 | 职责 |
|---|---|
| `src/app/modules/conversation/context_blocks.py` | 新建：身份/记忆/短记忆/边界组装 + 第三人观察前缀 |
| `src/app/modules/agent/graph/plan_execute.py` | 状态带 context；respond/aggregate/RAG 观察用分栏 |
| `src/app/modules/agent/graph/build.py` | `run_agent_turn` 透传 `memory_access` / context |
| `src/app/modules/conversation/runtime.py` | `_stream_plan_execute` 真正加载记忆；legacy 复用组装器 |
| `tests/test_context_source_boundary.py` | 本刀主测 |
| `docs/superpowers/CHECKPOINT.md` | 断点更新 |

---

### Task 1：`build_turn_context_blocks` + 第三人观察前缀

**Files:**
- Create: `src/app/modules/conversation/context_blocks.py`
- Test: `tests/test_context_source_boundary.py`

**Interfaces:**
- Consumes: `list_long_memories`、`build_memory_system_prompt`、`load_short_memory`、`User`
- Produces:
  - `SOURCE_BOUNDARY_RULE: str`（固定边界短文）
  - `THIRD_PARTY_OBS_PREFIX: str`（`【知识库/技能观察·第三人资料】`）
  - `label_third_party_observation(text: str) -> str`
  - `async def build_turn_context_blocks(db, *, user_id, conversation_id, memory_access) -> TurnContextBlocks`
  - `TurnContextBlocks`：`identity_text`、`memory_text`、`short_turns`、`boundary_text`、`system_sections() -> list[str]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_context_source_boundary.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.context_blocks import (
    SOURCE_BOUNDARY_RULE,
    build_turn_context_blocks,
    label_third_party_observation,
)
from app.modules.memory.service import append_short_memory, upsert_memory


@pytest.mark.asyncio
async def test_identity_from_users_not_short_memory(db_session, seed_user):
    """身份块用 users.name；短记忆里的「尹庆为」不得进入身份块。"""
    append_short_memory(
        user_id=seed_user.id,
        conversation_id="c1",
        role="assistant",
        content="你好，尹庆为！",
    )
    blocks = await build_turn_context_blocks(
        db_session,
        user_id=seed_user.id,
        conversation_id="c1",
        memory_access="all",
    )
    assert seed_user.name in blocks.identity_text
    assert "尹庆为" not in blocks.identity_text
    assert SOURCE_BOUNDARY_RULE in blocks.boundary_text


@pytest.mark.asyncio
async def test_memory_access_none_skips_memory_block(db_session, seed_user):
    await upsert_memory(
        db_session,
        user_id=seed_user.id,
        memory_type="preference",
        memory_key="reply_style",
        memory_value="简洁",
        source="manual",
    )
    await db_session.commit()
    blocks = await build_turn_context_blocks(
        db_session,
        user_id=seed_user.id,
        conversation_id="c2",
        memory_access="none",
    )
    assert blocks.memory_text == ""
    joined = "\n".join(blocks.system_sections())
    assert "简洁" not in joined
    assert "【来源边界】" in joined or SOURCE_BOUNDARY_RULE in joined


@pytest.mark.asyncio
async def test_memory_access_all_includes_preference(db_session, seed_user):
    await upsert_memory(
        db_session,
        user_id=seed_user.id,
        memory_type="preference",
        memory_key="reply_style",
        memory_value="简洁优先",
        source="manual",
    )
    await db_session.commit()
    blocks = await build_turn_context_blocks(
        db_session,
        user_id=seed_user.id,
        conversation_id="c3",
        memory_access="all",
    )
    assert "简洁优先" in blocks.memory_text


def test_label_third_party_observation_prefix():
    out = label_third_party_observation("检索命中：尹庆为简历…")
    assert out.startswith("【")
    assert "第三人" in out
    assert "尹庆为简历" in out
```

若仓库无现成 `seed_user` / `db_session` fixture，复用 `tests/conftest.py` 或同仓其它测里创建 User 的写法（例如 `tests/test_memory_*.py`），保持最小可跑。

- [ ] **Step 2: 跑测确认失败**

Run:

```powershell
cd D:\HermesWork\zeroAgent
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_context_source_boundary.py -v --tb=short
```

Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `context_blocks.py`**

```python
# src/app/modules/conversation/context_blocks.py
"""对话轮次上下文分栏（身份 / 记忆 / 短记忆 / 来源边界）。

@author 赵振明
@date <东八区实时>
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.memory.service import (
    build_memory_system_prompt,
    list_long_memories,
    load_short_memory,
)

SOURCE_BOUNDARY_RULE = (
    "称呼与「当前用户是谁」只依据【当前用户身份】与【用户记忆】；"
    "【本会话上下文】与带「第三人资料」标注的观察中出现的人名、经历、合同当事人，"
    "一律视为第三方或文档内容，不得当作当前用户身份。"
    "若用户追问为何被叫成某人/资料从哪来，应说明可能来自会话历史或检索混淆，"
    "并澄清：除非身份块或记忆已写明，否则不确定其真实姓名。"
)

THIRD_PARTY_OBS_PREFIX = "【知识库/技能观察·第三人资料】"


@dataclass
class TurnContextBlocks:
    identity_text: str
    memory_text: str
    short_turns: list[dict[str, str]] = field(default_factory=list)
    boundary_text: str = SOURCE_BOUNDARY_RULE

    def system_sections(self) -> list[str]:
        sections: list[str] = []
        if self.identity_text:
            sections.append(self.identity_text)
        if self.memory_text:
            sections.append(self.memory_text)
        if self.boundary_text:
            sections.append("【来源边界】\n" + self.boundary_text)
        return sections


def label_third_party_observation(text: str) -> str:
    """为 RAG/技能观察加第三人资料前缀（幂等）。"""
    raw = (text or "").strip()
    if not raw:
        return raw
    if raw.startswith(THIRD_PARTY_OBS_PREFIX):
        return raw
    return f"{THIRD_PARTY_OBS_PREFIX}\n{raw}"


async def build_turn_context_blocks(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    memory_access: str = "all",
) -> TurnContextBlocks:
    """每轮开聊前组装分栏上下文。"""
    user = (
        await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if user is None:
        identity = "【当前用户身份】\n姓名未提供"
    else:
        identity = (
            "【当前用户身份】\n"
            f"姓名：{user.name or '姓名未提供'}\n"
            f"账号：{user.username or ''}\n"
            f"职位：{user.position or ''}"
        ).rstrip()

    memory_text = ""
    if memory_access != "none":
        long_mem = await list_long_memories(db, user_id, memory_access=memory_access)
        raw = build_memory_system_prompt(long_mem)
        if raw:
            # 统一标题为分栏标签
            memory_text = raw.replace("# 用户记忆（跨会话）", "【用户记忆】", 1)

    short = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    return TurnContextBlocks(
        identity_text=identity,
        memory_text=memory_text,
        short_turns=short,
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
```

- [ ] **Step 4: 跑测确认通过**

Run: 同 Step 2  
Expected: PASS

---

### Task 2：Plan-Execute 接通分栏上下文

**Files:**
- Modify: `src/app/modules/agent/graph/plan_execute.py`
- Modify: `src/app/modules/agent/graph/build.py`
- Modify: `src/app/modules/conversation/runtime.py`（`_stream_plan_execute`）
- Test: `tests/test_context_source_boundary.py`（追加）

**Interfaces:**
- Consumes: `TurnContextBlocks`、`label_third_party_observation`、`SOURCE_BOUNDARY_RULE`
- Produces: `run_plan_execute(..., memory_access=...)`；state/configurable 含 `context_system: str`（`system_sections` join）；RAG/技能 `obs` 经 `label_third_party_observation`

- [ ] **Step 1: 写失败测试（断言不再丢弃 memory）**

```python
@pytest.mark.asyncio
async def test_plan_execute_respond_system_includes_memory(
    db_session, seed_user, monkeypatch
):
    """run_plan_execute 真路径：respond 收到的 system 须含偏好记忆。"""
    from app.modules.agent.graph import plan_execute as pe
    from app.modules.memory.service import upsert_memory

    await upsert_memory(
        db_session,
        user_id=seed_user.id,
        memory_type="preference",
        memory_key="reply_style",
        memory_value="务必简洁",
        source="manual",
    )
    await db_session.commit()

    captured: list[Any] = []

    class FakeModel:
        async def ainvoke(self, messages):
            captured.extend(messages)
            from langchain_core.messages import AIMessage
            return AIMessage(content="你好")

    monkeypatch.setattr(pe, "get_chat_model", lambda: FakeModel())
    monkeypatch.setattr(pe.get_settings(), "mock_external", False)
    # 若 get_settings 返回缓存对象，改为：
    # monkeypatch.setattr(pe, "get_settings", lambda: SimpleNamespace(mock_external=False, agent_plan_max_steps=4))

    # 强制单步 respond：mock planner
    async def fake_plan(user_content, *, skill_catalog, max_steps):
        return [{"kind": "respond", "args": {"query": user_content}}]

    monkeypatch.setattr(pe, "_plan_with_llm", fake_plan)

    result = await pe.run_plan_execute(
        db=db_session,
        agent_id="ag_dummy",  # 或测试里最小 seed agent；无技能也可
        user_content="你好",
        user_id=seed_user.id,
        conversation_id="c_pe",
        memory_access="all",
    )
    assert result.get("ok")
    sys_texts = "\n".join(
        str(getattr(m, "content", m)) for m in captured if m.__class__.__name__ == "SystemMessage" or getattr(m, "type", "") == "system"
    )
    # 兼容：检查 captured 里所有 SystemMessage
    from langchain_core.messages import SystemMessage
    sys_texts = "\n".join(m.content for m in captured if isinstance(m, SystemMessage))
    assert "务必简洁" in sys_texts
    assert "【当前用户身份】" in sys_texts or seed_user.name in sys_texts
```

若 seed agent 创建成本高：可只测 `_execute_respond` 在 state 含 `context_system` 时的行为（更小、更稳）：

```python
@pytest.mark.asyncio
async def test_execute_respond_uses_context_system(monkeypatch):
    from app.modules.agent.graph import plan_execute as pe
    from langchain_core.messages import SystemMessage, AIMessage

    captured = []

    class FakeModel:
        async def ainvoke(self, messages):
            captured.extend(messages)
            return AIMessage(content="ok")

    monkeypatch.setattr(pe, "get_chat_model", lambda: FakeModel())
    state = {
        "user_content": "你好",
        "context_system": "【当前用户身份】\n姓名：测试员\n【用户记忆】\n- reply_style: 简洁\n【来源边界】\n" + pe.SOURCE_BOUNDARY_RULE
        if hasattr(pe, "SOURCE_BOUNDARY_RULE")
        else "【用户记忆】\n- reply_style: 简洁",
    }
    # 直接从 context_blocks 导入边界常量拼 state
    from app.modules.conversation.context_blocks import SOURCE_BOUNDARY_RULE
    state["context_system"] = (
        "【当前用户身份】\n姓名：测试员\n"
        "【用户记忆】\n- reply_style: 简洁\n"
        "【来源边界】\n" + SOURCE_BOUNDARY_RULE
    )
    out = await pe._execute_respond(state, {"kind": "respond", "args": {}})
    assert out == "ok"
    assert any(isinstance(m, SystemMessage) and "简洁" in m.content for m in captured)
    assert any(isinstance(m, SystemMessage) and "测试员" in m.content for m in captured)
```

优先采用**小测 `_execute_respond`** + **另测 `runtime` 调用链传入 memory_access**（见 Step 3 后补测 `label` 在 RAG 路径）。

- [ ] **Step 2: 跑测确认失败**

Run: `pytest tests/test_context_source_boundary.py::test_execute_respond_uses_context_system -v`  
Expected: FAIL（当前 `_RESPOND_SYSTEM` 无记忆）

- [ ] **Step 3: 接线实现**

1. `AgentState` 增加 `context_system: str`（默认 `""`）。
2. `run_plan_execute` / `run_agent_turn` 增加参数 `memory_access: str = "all"`；在 invoke 前：

```python
from app.modules.conversation.context_blocks import build_turn_context_blocks

context_system = ""
if user_id and conversation_id:
    blocks = await build_turn_context_blocks(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        memory_access=memory_access,
    )
    context_system = "\n\n".join(blocks.system_sections())
# 初始 state 写入 context_system
# configurable 也可放一份备用
```

3. `_execute_respond`：用 `state["context_system"]` 或 `SOURCE_BOUNDARY_RULE` 作为 SystemMessage；**删除**症状式 `_RESPOND_SYSTEM` 长文（或仅保留一句「企业助手，简洁友好」拼在 context 前）。

4. `_execute_rag_search` / `_execute_skill_step` 返回的 `obs`：`obs = label_third_party_observation(obs)`。

5. `_node_aggregate`：system 追加 `state.get("context_system")` 或至少追加边界规则，避免汇总时把检索第三人当「你」。

6. `runtime._stream_plan_execute`：

```python
# 删除：_ = memory_access
result = await run_agent_turn(
    db,
    agent_id,
    user_content,
    user_id=user_id,
    conversation_id=conversation_id,
    department_ids=department_ids,
    role_ids=role_ids,
    is_platform_admin=is_platform_admin,
    memory_access=memory_access,
)
```

`build.py` 同步透传 `memory_access`。

- [ ] **Step 4: 跑测通过 + 相关回归**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_context_source_boundary.py tests/test_plan_execute_graph.py tests/test_chat_routing_hotfix.py -q --tb=line
```

Expected: 全部 PASS

---

### Task 3：Legacy / 闲聊路径统一分栏

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`（`_build_llm_messages`、`_stream_skill_fc`、闲聊分支）
- Test: `tests/test_context_source_boundary.py`

**Interfaces:**
- Consumes: `build_turn_context_blocks`、`TurnContextBlocks.system_sections`
- Produces: `_build_llm_messages` 以分栏 system 列表开头，不再使用 `_IDENTITY_GUARD` 症状文案

- [ ] **Step 1: 写失败测试**

```python
def test_build_llm_messages_uses_boundary_not_symptom_only():
    from app.modules.conversation.runtime import _build_llm_messages
    from app.modules.conversation.context_blocks import SOURCE_BOUNDARY_RULE

    msgs = _build_llm_messages(
        user_content="你好",
        tpl_block="",
        skill_block="",
        mem_block="【用户记忆】\n- reply_style: 简洁",
        short=[],
        identity_block="【当前用户身份】\n姓名：测试员",
        boundary_block=SOURCE_BOUNDARY_RULE,
    )
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    joined = "\n".join(systems)
    assert "测试员" in joined
    assert "简洁" in joined
    assert "第三人" in joined or "来源" in joined or SOURCE_BOUNDARY_RULE in joined
```

按实现选择：要么扩展 `_build_llm_messages` 签名，要么改为接收 `TurnContextBlocks`。

- [ ] **Step 2: 跑测确认失败**

Expected: FAIL（签名/内容不匹配）

- [ ] **Step 3: 改造 `_build_llm_messages`**

推荐签名：

```python
def _build_llm_messages(
    *,
    user_content: str,
    tpl_block: str,
    skill_block: str,
    blocks: TurnContextBlocks,
) -> list[dict[str, Any]]:
    llm_messages: list[dict[str, Any]] = [
        {"role": "system", "content": sec} for sec in blocks.system_sections()
    ]
    if tpl_block:
        llm_messages.append({"role": "system", "content": tpl_block})
    if skill_block:
        llm_messages.append({"role": "system", "content": skill_block})
    for turn in blocks.short_turns[:-1] if blocks.short_turns else []:
        # 注意：若当前轮已 append_short_memory，保持与现逻辑一致（short[:-1]）
        llm_messages.append({"role": turn["role"], "content": turn["content"]})
    llm_messages.append({"role": "user", "content": user_content})
    return llm_messages
```

调用处：先 `blocks = await build_turn_context_blocks(...)`，再传入；删除重复的 `list_long_memories` + `_IDENTITY_GUARD`。

短记忆切片：与现网一致——若调用前已 `append_short_memory` 本轮用户句，继续 `short[:-1]`；把该细节写进函数注释。

- [ ] **Step 4: 跑测**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_context_source_boundary.py tests/test_chat_routing_hotfix.py -q --tb=line
```

Expected: PASS

---

### Task 4：收尾 CHECKPOINT + 规格状态

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`
- Modify: `docs/superpowers/specs/2026-07-27-context-source-boundary-design.md`（状态改为「已批准 / 已实现」）

- [ ] **Step 1: 全量本刀回归**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_context_source_boundary.py tests/test_plan_execute_graph.py tests/test_chat_routing_hotfix.py tests/test_route_clarify_p2.py -q --tb=line
```

Expected: PASS

- [ ] **Step 2: 更新 CHECKPOINT**

顶部「当前断点」覆盖为：上下文分栏已落地；下一步新开对话验证称呼与记忆偏好。  
底部「断点日志」追加一条（东八区实时时间；禁止密钥）。

- [ ] **Step 3: 规格文首状态改为已实现**

---

## Spec coverage（自检）

| 规格条目 | Task |
|---|---|
| 每轮加载长期记忆 / 修 `_ = memory_access` | Task 2 |
| 身份 / 记忆 / 短记忆 / 边界分栏 | Task 1–3 |
| 身份仅 users 表 | Task 1 |
| `memory_access=none` 跳过记忆 | Task 1 |
| RAG/技能第三人前缀 | Task 1–2 |
| 替换症状式 respond/identity guard | Task 2–3 |
| 测试要点 1–5 | Task 1–3 + 热修回归 |
| CHECKPOINT | Task 4 |

记忆写入闸门：规格写「若现有抽取已只看用户原话则不动」——本计划不改抽取。

## Placeholder scan

无 TBD /「类似 Task N」占位。
