# Review package Task 1 (working tree; no commits)
## Files
src/app/modules/conversation/runtime.py
src/app/api/v1/messages.py
tests/test_dismiss_card.py
docs/01-产品需求/API接口规范.md
## Diff

### src/app/modules/conversation/runtime.py

diff --git a/src/app/modules/conversation/runtime.py b/src/app/modules/conversation/runtime.py
index f08c924..5dde1e0 100644
--- a/src/app/modules/conversation/runtime.py
+++ b/src/app/modules/conversation/runtime.py
@@ -1,7 +1,7 @@
 """瀵硅瘽杩愯鏃讹細璁板繂娉ㄥ叆 + 鎶€鑳?FC + Mock/鐪?LLM 娴?+ ask_user 鈫?鎻愰棶鍗°€? 
 @author 璧垫尟鏄?-@date 2026-07-27 10:12:09
+@date 2026-07-27 12:42:37
 """
 
 from __future__ import annotations
@@ -15,12 +15,12 @@ from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from app.models.conversation import Conversation, Message, MessageCard
-from app.modules.agent.graph.build import run_agent_turn
+from app.modules.agent.graph.build import run_agent_turn, stream_agent_turn
 from app.modules.agent.skill_prompt import build_agent_skill_system_prompt
 from app.modules.agent.skill_tools import load_agent_openai_tools
-from app.modules.llm.client import (
-    chat_completion_with_tools,
-    stream_chat_completion_with_fallback,
+from app.modules.llm.gateway import (
+    chat_with_tools as chat_completion_with_tools,
+    stream_chat as stream_chat_completion_with_fallback,
 )
 from app.modules.llm.prompt_template import load_agent_prompt_template
 from app.modules.llm.tokens import (
@@ -32,11 +32,14 @@ from app.modules.conversation.context_blocks import (
     TurnContextBlocks,
     build_turn_context_blocks,
 )
+from app.modules.conversation.process_narration import (
+    iter_stage_enter,
+    iter_stage_leave,
+)
 from app.modules.memory.service import (
     append_short_memory,
-    extract_memories_from_transcript,
-    persist_extracted_memories,
 )
+from app.modules.conversation.route import resolve_route
 from app.modules.intent.funnel import evaluate_intent_funnel, evaluate_intent_funnel_async
 from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
 from app.modules.knowledge.doc_analyze import run_doc_analyze
@@ -51,12 +54,27 @@ ASK_USER_TOOL = ASK_USER
 TZ_CN = timezone(timedelta(hours=8))
 
 
-def _context_info(messages: list[dict[str, Any]]) -> dict[str, Any]:
-    from app.core.config import get_settings
+def _context_info(
+    messages: list[dict[str, Any]],
+    *,
+    model_name: str | None = None,
+    window_tokens: int | None = None,
+) -> dict[str, Any]:
+    """浼扮畻褰撳墠 messages 鍗犵敤锛屽苟闄勫甫褰撳墠搴旂敤妯″瀷鐨勪笂涓嬫枃绐椼€? 
+    @author 璧垫尟鏄?+    @date 2026-07-30 13:36:32
+    """
+    from app.modules.llm.model_resolve import resolve_window_tokens
+
+    window = (
+        int(window_tokens)
+        if window_tokens is not None and int(window_tokens) > 0
+        else resolve_window_tokens(model_name)
+    )
     return {
         "tokens": estimate_messages_tokens(messages),
-        "window_tokens": int(get_settings().context_window_tokens),
+        "window_tokens": window,
     }
 
 
@@ -115,12 +133,25 @@ def mock_leave_ask_user_args() -> dict[str, Any]:
 
 
 def build_route_clarify_card(intent: Any) -> dict[str, Any]:
-    """璺敱婢勬竻鍗★紙涓嶇粡 ask_user锛汥33 / PRD route_clarify锛夈€?""
-    slots = getattr(intent, "slots", None) or {}
-    kind = str(slots.get("clarify_kind") or "agent_pick")
+    """璺敱婢勬竻鍗★紙涓嶇粡 ask_user锛汥33 / PRD route_clarify锛夈€?+
+    鍏煎 IntentDecision 涓?RouteDecision銆?+    """
+    slots = dict(getattr(intent, "slots", None) or {})
+    route_kind = getattr(intent, "kind", None)
+    if route_kind == "clarify_kb":
+        kind = "kb_confirm"
+    elif route_kind == "clarify_agent":
+        kind = "agent_pick"
+    else:
+        kind = str(slots.get("clarify_kind") or "agent_pick")
     query = str(getattr(intent, "query", "") or "")
     conf = float(getattr(intent, "confidence", 0.5) or 0.5)
-    candidates = list(getattr(intent, "agent_candidates", None) or [])
+    candidates = list(
+        getattr(intent, "agent_candidates", None)
+        or slots.get("agent_candidates")
+        or []
+    )
 
     if kind == "kb_confirm":
         title = "鏄惁妫€绱㈢煡璇嗗簱锛?
@@ -260,6 +291,39 @@ async def has_pending_required_card(db: AsyncSession, conversation_id: str) -> b
     return row is not None
 
 
+async def cancel_pending_cards(
+    db: AsyncSession,
+    *,
+    conversation_id: str,
+    card_id: str | None = None,
+) -> list[str]:
+    """灏?pending 鍗℃爣涓?cancelled锛涜繑鍥炲疄闄呬綔搴熺殑 id 鍒楄〃銆?+
+    @author 璧垫尟鏄?+    @date 2026-07-30 14:41:54
+    """
+    stmt = select(MessageCard).where(
+        MessageCard.conversation_id == conversation_id,
+        MessageCard.status == "pending",
+    )
+    if card_id:
+        stmt = stmt.where(MessageCard.id == card_id)
+    rows = list((await db.execute(stmt)).scalars().all())
+    now = datetime.now(timezone.utc).replace(tzinfo=None)
+    ids: list[str] = []
+    for row in rows:
+        row.status = "cancelled"
+        row.submitted_at = now
+        row.result = json.dumps(
+            {"dismissed": True, "reason": "user_supersede"},
+            ensure_ascii=False,
+        )
+        ids.append(row.id)
+    if ids:
+        await db.commit()
+    return ids
+
+
 async def persist_assistant_and_card(
     db: AsyncSession,
     *,
@@ -309,19 +373,32 @@ async def _enqueue_extract(
     conversation_id: str,
     transcript: str,
     allow_memory_write: bool = True,
+    route_reason: str = "",
+    route_kind: str = "",
+    model_name: str | None = None,
 ) -> None:
-    """瀵硅瘽缁撴潫鍚庢娊鍙栧苟钀藉簱銆?+    """瀵硅瘽缁撴潫鍚庡紓姝ヨ皟搴﹁蹇嗘娊鍙栦笌涓婁笅鏂囧帇缂╋紙绂佹 await LLM锛夈€? 
-    蹇呴』鍦ㄨ姹傚唴鍚屾钀藉簱锛岄伩鍏嶄粎渚濊禆 Celery Worker 鏃躲€屾柊瀵硅瘽澶卞繂銆嶃€?-    conversation_id 淇濈暀渚涘悗缁璁?寮傛琛ユ娊銆?+    @author 璧垫尟鏄?+    @date 2026-07-30 14:03:22
     """
-    if not allow_memory_write:
-        return
-    _ = conversation_id
-    items = await extract_memories_from_transcript(transcript)
-    if not items:
-        return
-    await persist_extracted_memories(db, user_id=user_id, items=items)
+    _ = db
+    from app.modules.conversation.compress_scheduler import schedule_context_compress
+    from app.modules.memory.extract_scheduler import schedule_memory_extract
+
+    schedule_memory_extract(
+        user_id=user_id,
+        conversation_id=conversation_id,
+        transcript=transcript,
+        allow_memory_write=allow_memory_write,
+        route_reason=route_reason,
+        route_kind=route_kind,
+    )
+    schedule_context_compress(
+        user_id=user_id,
+        conversation_id=conversation_id,
+        model_name=model_name,
+    )
 
 
 def _build_llm_messages(
@@ -330,23 +407,36 @@ def _build_llm_messages(
     tpl_block: str,
     skill_block: str,
     blocks: TurnContextBlocks,
+    model_name: str | None = None,
+    max_input_tokens: int | None = None,
+    max_output_tokens: int | None = None,
 ) -> list[dict[str, Any]]:
-    """鐢?TurnContextBlocks 缁勮 legacy/闂茶亰 LLM messages銆?+    """鐢?TurnContextBlocks 缁勮 LLM messages锛屽苟鎸変笂涓嬫枃绐椾紭鍏堢骇鎴柇銆? 
     鐭蹇嗗垏闈細璋冪敤鏂硅嫢宸插湪鏈疆 append_short_memory(user)锛屽垯 short_turns
     鏈潯鍗冲綋鍓嶇敤鎴峰彞锛岄』 short_turns[:-1] 鍐嶈拷鍔犳湰杞?user锛岄伩鍏嶉噸澶嶃€?     """
-    llm_messages: list[dict[str, Any]] = [
-        {"role": "system", "content": sec} for sec in blocks.system_sections()
+    from app.modules.llm.context_budget import pack_turn_messages
+    from app.modules.llm.model_resolve import resolve_window_tokens
+
+    history = [
+        {"role": turn["role"], "content": turn["content"]}
+        for turn in (blocks.short_turns[:-1] if blocks.short_turns else [])
     ]
-    if tpl_block:
-        llm_messages.append({"role": "system", "content": tpl_block})
-    if skill_block:
-        llm_messages.append({"role": "system", "content": skill_block})
-    for turn in blocks.short_turns[:-1] if blocks.short_turns else []:
-        llm_messages.append({"role": turn["role"], "content": turn["content"]})
-    llm_messages.append({"role": "user", "content": user_content})
-    return llm_messages
+    extra = [b for b in (tpl_block, skill_block) if b]
+    win = max_input_tokens
+    if win is None or int(win) <= 0:
+        win = resolve_window_tokens(model_name)
+    packed = pack_turn_messages(
+        model_name=model_name or "default",
+        sections=blocks.system_sections(),
+        history=history,
+        user_content=user_content,
+        max_input_tokens=win,
+        max_output_tokens=max_output_tokens,
+        extra_system=extra,
+    )
+    return packed.messages
 
 
 async def _stream_skill_fc(
@@ -377,23 +467,31 @@ async def _stream_skill_fc(
         user_id=user_id,
         conversation_id=conversation_id,
         memory_access=memory_access,
+        agent_id=agent_id,
     )
     skill_block = await build_agent_skill_system_prompt(db, agent_id)
     tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
+    primary = (model_ids or [None])[0]
+    primary = str(primary).strip() if primary else None
     llm_messages = _build_llm_messages(
         user_content=user_content,
         tpl_block=tpl_block,
         skill_block=skill_block,
         blocks=blocks,
+        model_name=primary,
     )
 
-    primary = (model_ids or [None])[0]
     max_rounds = max(1, int(get_settings().skill_fc_max_rounds))
     model_used: str | None = None
     tools_used: list[str] = []
     fc_rounds = 0
     usage_acc: dict[str, Any] | None = None
 
+    for item in iter_stage_enter("understand"):
+        yield item
+    for item in iter_stage_leave("understand", ok=True):
+        yield item
+
     for round_idx in range(1, max_rounds + 1):
         fc_rounds = round_idx
         try:
@@ -425,12 +523,16 @@ async def _stream_skill_fc(
         usage_acc = merge_usage(usage_acc, result.get("usage"))
         model_used = result.get("model") or model_used
         tool_calls = result.get("tool_calls") or []
-        ctx = _context_info(llm_messages)
+        ctx = _context_info(llm_messages, model_name=primary)
 
         if not tool_calls:
+            for item in iter_stage_enter("respond"):
+                yield item
             text = str(result.get("content") or "")
             for ch in text:
                 yield "content_delta", {"delta": ch}
+            for item in iter_stage_leave("respond", ok=True):
+                yield item
             meta = {**(msg_meta or {}), "usage": usage_acc, "context": ctx}
             msg_id, _ = await persist_assistant_and_card(
                 db,
@@ -461,21 +563,34 @@ async def _stream_skill_fc(
                 conversation_id=conversation_id,
                 transcript=user_content,
                 allow_memory_write=allow_memory_write,
+                model_name=primary,
             )
             return
 
         for tc in tool_calls:
+            tname = str(tc.get("name") or "")
+            if tname and tname != ASK_USER_TOOL:
+                for item in iter_stage_enter("skill", skill_name=tname):
+                    yield item
             yield "tool_call", {
                 "id": tc.get("id"),
                 "name": tc.get("name"),
                 "arguments": tc.get("arguments") or {},
                 "round": round_idx,
             }
-            if tc.get("name"):
-                tools_used.append(str(tc["name"]))
+            if tname:
+                tools_used.append(tname)
+            if tname and tname != ASK_USER_TOOL:
+                for item in iter_stage_leave("skill", ok=True, skill_name=tname):
+                    yield item
 
         ask = next((tc for tc in tool_calls if tc.get("name") == ASK_USER_TOOL), None)
         if ask is not None:
+            for item in iter_stage_enter("skill", skill_name="鍚戠敤鎴锋彁闂?):
+                yield item
+            yield "thought_delta", {"delta": "闇€瑕佷綘琛ュ厖淇℃伅銆?}
+            for item in iter_stage_leave("skill", ok=True, skill_name="鍚戠敤鎴锋彁闂?):
+                yield item
             lead = str(result.get("content") or "璇疯ˉ鍏呬俊鎭€?)
             for ch in lead:
                 yield "content_delta", {"delta": ch}
@@ -584,6 +699,7 @@ async def _stream_skill_fc(
                 conversation_id=conversation_id,
                 transcript=user_content,
                 allow_memory_write=allow_memory_write,
+                model_name=primary,
             )
             return
 
@@ -601,9 +717,15 @@ async def _stream_plan_execute(
     department_ids: list[str] | None = None,
     role_ids: list[str] | None = None,
     is_platform_admin: bool = False,
+    model: str | None = None,
 ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
-    """Plan-Execute 涓诲浘 SSE锛歝itations + answer + 鍙€?deferred_card銆?""
-    result = await run_agent_turn(
+    """Plan-Execute 涓诲浘 SSE锛氳繃绋嬩簨浠?+ citations + answer + 鍙€?deferred_card銆?+
+    @author 璧垫尟鏄?+    @date 2026-07-30 13:03:49
+    """
+    result: dict[str, Any] | None = None
+    async for ev, data in stream_agent_turn(
         db,
         agent_id,
         user_content,
@@ -613,13 +735,23 @@ async def _stream_plan_execute(
         role_ids=role_ids,
         is_platform_admin=is_platform_admin,
         memory_access=memory_access,
-    )
+        model=model,
+    ):
+        if ev == "__result__":
+            result = data
+            continue
+        yield ev, data
+
+    if result is None:
+        result = {"ok": False, "answer": "", "citations": [], "plan": [], "error": "empty_result"}
 
     plan = list(result.get("plan") or [])
     used_rag = any(str(s.get("kind") or "") == "rag_search" for s in plan)
     citations = list(result.get("citations") or [])
 
     if used_rag and not evaluate_rag_citation_gate(used_rag=True, citations=citations):
+        for item in iter_stage_leave("retrieve", ok=False):
+            yield item
         notice = "鏈疆妫€绱㈡湭浜х敓鏈夋晥寮曠敤锛屽凡鎷掔粷灞曠ず鏈€缁堢瓟妗堬紙D14锛夈€?
         for ch in notice:
             yield "content_delta", {"delta": ch}
@@ -651,7 +783,7 @@ async def _stream_plan_execute(
     deferred_card = result.get("deferred_card")
     msgs = [{"role": "user", "content": user_content}]
     usage = estimate_turn_usage(msgs, answer)
-    ctx = _context_info(msgs)
+    ctx = _context_info(msgs, model_name=model)
     meta = {
         **(msg_meta or {}),
         "usage": usage,
@@ -698,9 +830,29 @@ async def _stream_plan_execute(
             conversation_id=conversation_id,
             transcript=user_content,
             allow_memory_write=allow_memory_write,
+            model_name=model,
         )
 
 
+def _build_recent_summary(*, user_id: str, conversation_id: str) -> str:
+    """杩戣疆鎽樿渚?L3锛氣墹6 鏉★紝鎬婚暱鎴柇 500銆?""
+    from app.modules.memory.service import load_short_memory
+
+    turns = load_short_memory(user_id=user_id, conversation_id=conversation_id)
+    # 鍘绘帀鏈疆鍒?append 鐨?user锛岄伩鍏嶆憳瑕佽嚜鎸?+    if turns and turns[-1].get("role") == "user":
+        turns = turns[:-1]
+    lines: list[str] = []
+    for t in turns[-6:]:
+        role = str(t.get("role") or "")
+        content = str(t.get("content") or "").strip().replace("\n", " ")
+        if not content:
+            continue
+        prefix = "user" if role == "user" else "assistant"
+        lines.append(f"{prefix}:{content[:120]}")
+    return "\n".join(lines)[:500]
+
+
 async def stream_mock_reply(
     db: AsyncSession,
     *,
@@ -716,25 +868,71 @@ async def stream_mock_reply(
     role_ids: list[str] | None = None,
     is_platform_admin: bool = False,
 ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
-    """瀵硅瘽娴侊細鎶€鑳?FC / 璁板繂娉ㄥ叆 / ask_user 鎹峰緞 / RAG / 鏅€?LLM銆?""
+    """瀵硅瘽娴侊細RouteResolver 鈫?Dispatcher锛堟緞娓?/ System / Agent锛夈€?""
     append_short_memory(
         user_id=user_id, conversation_id=conversation_id, role="user", content=user_content
     )
-    msg_meta = {"retry_of": retry_of} if retry_of else None
+    msg_meta: dict[str, Any] | None = {"retry_of": retry_of} if retry_of else None
     try:
         from app.modules.intent.lexicon import refresh_lexicon_if_stale
 
         await refresh_lexicon_if_stale(db)
     except Exception:  # noqa: BLE001
         pass
-    intent = await evaluate_intent_funnel_async(user_content)
-    intent_meta = intent.to_meta()
 
     from app.core.config import get_settings
 
     settings = get_settings()
+    summary = _build_recent_summary(user_id=user_id, conversation_id=conversation_id)
+    primary = None
+    if model_ids:
+        for mid in model_ids:
+            name = str(mid or "").strip()
+            if name:
+                primary = name
+                break
+    route = await resolve_route(
+        user_content,
+        agent_id=agent_id,
+        recent_summary=summary,
+        kb_names=None,
+        model=primary,
+    )
+    route_meta = route.to_meta()
+    msg_meta = {**(msg_meta or {}), **route_meta}
+
+    if route.handler == "clarify":
+        lead = "闇€瑕佹偍纭涓€涓嬫剰鍥撅紝璇烽€夋嫨锛?
+        for ch in lead:
+            yield "content_delta", {"delta": ch}
+        card = build_route_clarify_card(route)
+        msgs = [{"role": "user", "content": user_content}]
+        usage = estimate_turn_usage(msgs, lead)
+        ctx = _context_info(msgs, model_name=primary)
+        meta = {**(msg_meta or {}), "usage": usage, "context": ctx}
+        msg_id, _ = await persist_assistant_and_card(
+            db,
+            conversation_id=conversation_id,
+            assistant_text=lead,
+            card_payload=card,
+            meta=meta,
+        )
+        append_short_memory(
+            user_id=user_id, conversation_id=conversation_id, role="assistant", content=lead
+        )
+        yield "card", card
+        yield "message_end", {
+            "message_id": msg_id,
+            "status": "awaiting_card",
+            "path": "route_clarify",
+            "usage": usage,
+            "context": ctx,
+            **route_meta,
+        }
+        return
+
     tools = await load_agent_openai_tools(db, agent_id)
-    if agent_id and settings.agent_runtime == "langgraph":
+    if route.handler == "agent" and agent_id and settings.agent_runtime == "langgraph":
         async for ev in _stream_plan_execute(
             db,
             conversation_id=conversation_id,
@@ -747,11 +945,12 @@ async def stream_mock_reply(
             department_ids=department_ids,
             role_ids=role_ids,
             is_platform_admin=is_platform_admin,
+            model=primary,
         ):
             yield ev
         return
 
-    if agent_id and tools:
+    if route.handler == "agent" and agent_id and tools:
         async for ev in _stream_skill_fc(
             db,
             conversation_id=conversation_id,
@@ -770,15 +969,15 @@ async def stream_mock_reply(
             yield ev
         return
 
-    if intent.intent == "ask_user_form":
+    if route.kind == "ask_form":
         lead = "濂界殑锛岃鍏堢‘璁よ鍋囩被鍨嬨€?
         for ch in lead:
             yield "content_delta", {"delta": ch}
         card = ask_user_to_card_payload(mock_leave_ask_user_args())
         msgs = [{"role": "user", "content": user_content}]
         usage = estimate_turn_usage(msgs, lead)
-        ctx = _context_info(msgs)
-        meta = {**(msg_meta or {}), "usage": usage, "context": ctx, **intent_meta}
+        ctx = _context_info(msgs, model_name=primary)
+        meta = {**(msg_meta or {}), "usage": usage, "context": ctx}
         msg_id, _ = await persist_assistant_and_card(
             db,
             conversation_id=conversation_id,
@@ -796,7 +995,7 @@ async def stream_mock_reply(
             "tool": ASK_USER_TOOL,
             "usage": usage,
             "context": ctx,
-            **intent_meta,
+            **route_meta,
         }
         await _enqueue_extract(
             db,
@@ -804,43 +1003,16 @@ async def stream_mock_reply(
             conversation_id=conversation_id,
             transcript=user_content,
             allow_memory_write=allow_memory_write,
+            route_reason=str(route.reason or ""),
+            route_kind=str(route.kind or ""),
+            model_name=primary,
         )
         return
 
-    if intent.intent == "route_clarify":
-        lead = "闇€瑕佹偍纭涓€涓嬫剰鍥撅紝璇烽€夋嫨锛?
-        for ch in lead:
-            yield "content_delta", {"delta": ch}
-        card = build_route_clarify_card(intent)
-        msgs = [{"role": "user", "content": user_content}]
-        usage = estimate_turn_usage(msgs, lead)
-        ctx = _context_info(msgs)
-        meta = {**(msg_meta or {}), "usage": usage, "context": ctx, **intent_meta}
-        msg_id, _ = await persist_assistant_and_card(
-            db,
-            conversation_id=conversation_id,
-            assistant_text=lead,
-            card_payload=card,
-            meta=meta,
-        )
-        append_short_memory(
-            user_id=user_id, conversation_id=conversation_id, role="assistant", content=lead
-        )
-        yield "card", card
-        yield "message_end", {
-            "message_id": msg_id,
-            "status": "awaiting_card",
-            "path": "route_clarify",
-            "usage": usage,
-            "context": ctx,
-            **intent_meta,
-        }
-        return
-
-    if intent.intent == "doc_analyze":
-        task = str((intent.slots or {}).get("task") or "summarize")
-        analyze_query = intent.query or user_content
-        doc_id = str((intent.slots or {}).get("doc_id") or "")
+    if route.kind == "doc_analyze":
+        task = str((route.slots or {}).get("task") or "summarize")
+        analyze_query = route.query or user_content
+        doc_id = str((route.slots or {}).get("doc_id") or "")
         if not doc_id:
             doc_id = await _resolve_doc_id_for_analyze(
                 db,
@@ -860,13 +1032,13 @@ async def stream_mock_reply(
                 conversation_id=conversation_id,
                 assistant_text=notice,
                 card_payload=None,
-                meta={**(msg_meta or {}), **intent_meta},
+                meta={**(msg_meta or {})},
             )
             yield "message_end", {
                 "message_id": msg_id,
                 "status": "doc_not_found",
                 "path": "doc_analyze",
-                **intent_meta,
+                **route_meta,
             }
             return
 
@@ -876,6 +1048,7 @@ async def stream_mock_reply(
             task=task,  # type: ignore[arg-type]
             query=analyze_query,
             user_id=user_id,
+            model=primary,
         )
         if not result.get("ok"):
             err = str(result.get("error") or "doc_analyze_failed")
@@ -887,13 +1060,13 @@ async def stream_mock_reply(
                 conversation_id=conversation_id,
                 assistant_text=notice,
                 card_payload=None,
-                meta={**(msg_meta or {}), **intent_meta},
+                meta={**(msg_meta or {})},
             )
             yield "message_end", {
                 "message_id": msg_id,
                 "status": "failed",
                 "path": "doc_analyze",
-                **intent_meta,
+                **route_meta,
             }
             return
 
@@ -907,13 +1080,13 @@ async def stream_mock_reply(
                 conversation_id=conversation_id,
                 assistant_text=notice,
                 card_payload=None,
-                meta={**(msg_meta or {}), **intent_meta},
+                meta={**(msg_meta or {})},
             )
             yield "message_end", {
                 "message_id": msg_id,
                 "status": "rejected_no_citation",
                 "reason": "D14",
-                **intent_meta,
+                **route_meta,
             }
             return
 
@@ -924,12 +1097,11 @@ async def stream_mock_reply(
             yield "content_delta", {"delta": ch}
         msgs = [{"role": "user", "content": user_content}]
         usage = estimate_turn_usage(msgs, answer)
-        ctx = _context_info(msgs)
+        ctx = _context_info(msgs, model_name=primary)
         meta = {
             **(msg_meta or {}),
             "usage": usage,
             "context": ctx,
-            **intent_meta,
             "doc_analyze_stats": result.get("stats"),
         }
         msg_id, _ = await persist_assistant_and_card(
@@ -948,7 +1120,7 @@ async def stream_mock_reply(
             "path": "doc_analyze",
             "usage": usage,
             "context": ctx,
-            **intent_meta,
+            **route_meta,
         }
         await _enqueue_extract(
             db,
@@ -956,79 +1128,59 @@ async def stream_mock_reply(
             conversation_id=conversation_id,
             transcript=user_content,
             allow_memory_write=allow_memory_write,
+            route_reason=str(route.reason or ""),
+            route_kind=str(route.kind or ""),
+            model_name=primary,
         )
         return
 
-    if intent.intent == "kb_lookup":
-        citations: list[dict[str, Any]] = []
-        if rag_stub_has_citation(user_content):
-            lookup = await run_kb_lookup(
-                db,
-                query=intent.query or parse_rag_query(user_content),
-                agent_id=agent_id,
-                top_k=5,
-                user_id=user_id,
-                department_ids=department_ids,
-                role_ids=role_ids,
-                is_platform_admin=is_platform_admin,
-                filters=(intent.slots or {}).get("filters"),
-            )
-            citations = list(lookup.get("citations") or [])
-        if not evaluate_rag_citation_gate(used_rag=True, citations=citations):
-            notice = "鏈疆妫€绱㈡湭浜х敓鏈夋晥寮曠敤锛屽凡鎷掔粷灞曠ず鏈€缁堢瓟妗堬紙D14锛夈€?
-            for ch in notice:
-                yield "content_delta", {"delta": ch}
-            msg_id, _ = await persist_assistant_and_card(
-                db,
-                conversation_id=conversation_id,
-                assistant_text=notice,
-                card_payload=None,
-                meta={**(msg_meta or {}), **intent_meta},
-            )
-            yield "message_end", {
-                "message_id": msg_id,
-                "status": "rejected_no_citation",
-                "reason": "D14",
-                **intent_meta,
-            }
-            return
+    if route.kind == "kb_lookup":
+        from app.modules.conversation.handlers.kb_lookup import handle_system_kb_lookup
 
-        for c in citations:
-            yield "citation", c
-        # 鏃?LLM锛氱敤鍛戒腑鐗囨鎷肩畝绛旓紙D14 宸叉湁寮曠敤锛?-        snippets = [str(c.get("snippet") or "") for c in citations if c.get("snippet")]
-        answer = "鏍规嵁鐭ヨ瘑搴擄細" + ("锛?.join(snippets[:3]) if snippets else "宸叉壘鍒扮浉鍏虫潯鐩€?)
-        for ch in answer:
+        async for ev in handle_system_kb_lookup(
+            db,
+            conversation_id=conversation_id,
+            user_id=user_id,
+            user_content=user_content,
+            route=route,
+            agent_id=agent_id,
+            department_ids=department_ids,
+            role_ids=role_ids,
+            is_platform_admin=is_platform_admin,
+            memory_access=memory_access,
+            allow_memory_write=allow_memory_write,
+            msg_meta=msg_meta,
+            model=primary,
+        ):
+            yield ev
+        return
+
+    if route.kind == "reject":
+        notice = "璇ヨ姹傛殏鏃舵棤娉曞鐞嗭紝璇锋崲涓€绉嶈娉曟垨鑱旂郴绠＄悊鍛樸€?
+        for ch in notice:
             yield "content_delta", {"delta": ch}
         msgs = [{"role": "user", "content": user_content}]
-        usage = estimate_turn_usage(msgs, answer)
-        ctx = _context_info(msgs)
-        meta = {**(msg_meta or {}), "usage": usage, "context": ctx, **intent_meta}
+        usage = estimate_turn_usage(msgs, notice)
+        ctx = _context_info(msgs, model_name=primary)
+        meta = {**(msg_meta or {}), "usage": usage, "context": ctx}
         msg_id, _ = await persist_assistant_and_card(
             db,
             conversation_id=conversation_id,
-            assistant_text=answer,
+            assistant_text=notice,
             card_payload=None,
             meta=meta,
         )
         append_short_memory(
-            user_id=user_id, conversation_id=conversation_id, role="assistant", content=answer
+            user_id=user_id, conversation_id=conversation_id, role="assistant", content=notice
         )
         yield "message_end", {
             "message_id": msg_id,
-            "status": "completed",
-            "path": "rag",
+            "status": "rejected",
+            "path": "reject",
             "usage": usage,
             "context": ctx,
-            **intent_meta,
+            **route_meta,
         }
-        await _enqueue_extract(
-            db,
-            user_id=user_id,
-            conversation_id=conversation_id,
-            transcript=user_content,
-            allow_memory_write=allow_memory_write,
-        )
         return
 
     blocks = await build_turn_context_blocks(
@@ -1036,6 +1188,7 @@ async def stream_mock_reply(
         user_id=user_id,
         conversation_id=conversation_id,
         memory_access=memory_access,
+        agent_id=agent_id,
     )
     skill_block = await build_agent_skill_system_prompt(db, agent_id)
     tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
@@ -1044,8 +1197,16 @@ async def stream_mock_reply(
         tpl_block=tpl_block,
         skill_block=skill_block,
         blocks=blocks,
+        model_name=primary,
     )
 
+    for item in iter_stage_enter("understand"):
+        yield item
+    for item in iter_stage_leave("understand", ok=True):
+        yield item
+    for item in iter_stage_enter("respond"):
+        yield item
+
     text_parts: list[str] = []
     model_used: str | None = None
     usage_acc: dict[str, Any] | None = None
@@ -1072,6 +1233,8 @@ async def stream_mock_reply(
                 text_parts.append(ch)
                 yield "content_delta", {"delta": ch}
     except Exception as exc:  # noqa: BLE001
+        for item in iter_stage_leave("respond", ok=False):
+            yield item
         reason = "llm_fallback_exhausted" if "fallback" in str(exc).lower() else "llm_upstream"
         notice = f"妯″瀷璋冪敤澶辫触锛歿exc}"
         for ch in notice:
@@ -1090,6 +1253,9 @@ async def stream_mock_reply(
         }
         return
 
+    for item in iter_stage_leave("respond", ok=True):
+        yield item
+
     text = "".join(text_parts)
     replaced = sanitize_assistant_if_tool_leak(text)
     if replaced is not None:
@@ -1100,7 +1266,7 @@ async def stream_mock_reply(
         text = replaced
     if usage_acc is None:
         usage_acc = estimate_turn_usage(llm_messages, text)
-    ctx = _context_info(llm_messages)
+    ctx = _context_info(llm_messages, model_name=primary)
     meta_out = {**(msg_meta or {}), "usage": usage_acc, "context": ctx}
     msg_id, _ = await persist_assistant_and_card(
         db,
@@ -1117,6 +1283,7 @@ async def stream_mock_reply(
         "status": "completed",
         "usage": usage_acc,
         "context": ctx,
+        **route_meta,
     }
     if model_used:
         end_payload["model_used"] = model_used
@@ -1127,6 +1294,9 @@ async def stream_mock_reply(
         conversation_id=conversation_id,
         transcript=user_content,
         allow_memory_write=allow_memory_write,
+        route_reason=str(route.reason or ""),
+        route_kind=str(route.kind or ""),
+        model_name=primary,
     )
 
 
@@ -1141,10 +1311,22 @@ async def stream_after_card_action(
     department_ids: list[str] | None = None,
     role_ids: list[str] | None = None,
     is_platform_admin: bool = False,
+    model_ids: list[str] | None = None,
 ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
-    """鍗＄墖鍥炰紶鍚庣画璺戯細璇峰亣纭 / 鐭ヨ瘑搴撴緞娓?/ Agent 閫夋嫨銆?""
+    """鍗＄墖鍥炰紶鍚庣画璺戯細璇峰亣纭 / 鐭ヨ瘑搴撴緞娓?/ Agent 閫夋嫨銆?+
+    @author 璧垫尟鏄?+    @date 2026-07-30 13:36:32
+    """
     selected = payload.get("selected_option_ids") or []
     choice = str(selected[0]) if selected else ""
+    primary: str | None = None
+    if model_ids:
+        for mid in model_ids:
+            name = str(mid or "").strip()
+            if name:
+                primary = name
+                break
 
     card_payload: dict[str, Any] = {}
     if card is not None and card.payload:
@@ -1209,7 +1391,7 @@ async def stream_after_card_action(
                 yield "content_delta", {"delta": ch}
             msgs = [{"role": "user", "content": query}]
             usage = estimate_turn_usage(msgs, answer)
-            ctx = _context_info(msgs)
+            ctx = _context_info(msgs, model_name=primary)
             meta_out = {**intent_meta, "usage": usage, "context": ctx}
             msg_id, _ = await persist_assistant_and_card(
                 db,

### src/app/api/v1/messages.py

diff --git a/src/app/api/v1/messages.py b/src/app/api/v1/messages.py
index a112a15..5868942 100644
--- a/src/app/api/v1/messages.py
+++ b/src/app/api/v1/messages.py
@@ -21,12 +21,14 @@ from app.core.actor import get_actor, is_department_admin, is_platform_admin
 from app.core.response import fail, ok
 from app.models.conversation import Conversation, Message, MessageCard, MessageFeedback
 from app.modules.conversation.runtime import (
+    cancel_pending_cards,
     has_pending_required_card,
     stream_after_card_action,
     stream_mock_reply,
 )
 from app.modules.knowledge.permissions import load_user_department_ids
-from app.modules.llm.model_chain import resolve_agent_model_chain
+from app.modules.llm.gateway import llm_gateway
+from app.modules.llm.model_resolve import ModelResolveError
 from app.modules.llm.tokens import estimate_messages_tokens
 from app.modules.memory.service import load_short_memory, resolve_agent_memory_policy
 from app.modules.usage.redact import redact_text
@@ -36,6 +38,25 @@ from app.core.config import get_settings
 router = APIRouter(prefix="/api/v1", tags=["messages"])
 
 
+async def _resolve_model_ids(
+    db: AsyncSession, conv: Conversation | None
+) -> list[str] | JSONResponse:
+    """缁?Gateway 瑙ｆ瀽浼氳瘽妯″瀷閾撅紱澶辫触杩斿洖 400 JSONResponse銆?""
+    target = conv
+    if target is None:
+
+        class _EmptyConv:
+            agent_id = None
+            selected_model = None
+
+        target = _EmptyConv()  # type: ignore[assignment]
+    try:
+        resolved = await llm_gateway.resolve_for_conversation(db, target)
+    except ModelResolveError as exc:
+        return JSONResponse(status_code=400, content=fail(40031, str(exc)))
+    return resolved.as_chain()
+
+
 class ConversationCreate(BaseModel):
     title: str | None = None
     agent_id: str | None = None
@@ -44,6 +65,18 @@ class ConversationCreate(BaseModel):
 class MessageSend(BaseModel):
     conversation_id: str
     content: str
+    supersede_pending_card: bool = False
+
+
+class DismissCardBody(BaseModel):
+    """浣滃簾浼氳瘽涓?pending 浜や簰鍗°€?+
+    @author 璧垫尟鏄?+    @date 2026-07-30 14:41:54
+    """
+
+    conversation_id: str
+    card_id: str | None = None
 
 
 class CardAction(BaseModel):
@@ -93,11 +126,22 @@ async def list_conversations(
     user_id: str | None = None,
     db: AsyncSession = Depends(get_db),
 ) -> dict:
-    """瀵硅瘽鍒楄〃銆傞儴闂ㄧ鐞嗗憳锛氬唴瀹硅劚鏁忓彧璇伙紙D26锛夈€?""
+    """瀵硅瘽鍒楄〃銆傞儴闂ㄧ鐞嗗憳锛氬唴瀹硅劚鏁忓彧璇伙紙D26锛夈€傚凡鍒犻櫎浼氳瘽涓嶈繑鍥炪€?""
     actor = get_actor(request)
-    stmt = select(Conversation).order_by(Conversation.updated_at.desc())
+    stmt = (
+        select(Conversation)
+        .where(Conversation.status == "active")
+        .order_by(Conversation.updated_at.desc())
+    )
+    # 鏅€氱敤鎴峰彧鐪嬭嚜宸辩殑锛涘钩鍙扮鐞嗗憳鍙紶 user_id 鎴栫湅鍏ㄩ儴
     if user_id:
+        if not is_platform_admin(actor) and user_id != actor.user_id:
+            return JSONResponse(
+                status_code=403, content=fail(40301, "cannot list other users")
+            )
         stmt = stmt.where(Conversation.user_id == user_id)
+    elif not is_platform_admin(actor):
+        stmt = stmt.where(Conversation.user_id == actor.user_id)
     convs = (await db.execute(stmt)).scalars().all()
     items: list[dict[str, Any]] = []
     for c in convs:
@@ -129,6 +173,26 @@ async def list_conversations(
     return ok({"items": items})
 
 
+@router.delete("/conversations/{conversation_id}", response_model=None)
+async def delete_conversation(
+    conversation_id: str,
+    request: Request,
+    db: AsyncSession = Depends(get_db),
+) -> dict | JSONResponse:
+    """杞垹浼氳瘽锛歴tatus=deleted锛涗粎鏈汉鎴栧钩鍙扮鐞嗗憳銆?""
+    actor = get_actor(request)
+    conv = await db.get(Conversation, conversation_id)
+    if conv is None or conv.status == "deleted":
+        return JSONResponse(status_code=404, content=fail(40401, "conversation not found"))
+    if conv.user_id != actor.user_id and not is_platform_admin(actor):
+        return JSONResponse(
+            status_code=403, content=fail(40301, "cannot delete others conversation")
+        )
+    conv.status = "deleted"
+    await db.commit()
+    return ok({"id": conversation_id, "deleted": True})
+
+
 @router.get("/conversations/{conversation_id}")
 async def get_conversation(
     conversation_id: str,
@@ -138,7 +202,7 @@ async def get_conversation(
     """鍗曚細璇濊鎯咃細娑堟伅 + 寰呯瓟鍗＄墖锛堜緵鍓嶇鍒囬〉鍚庢仮澶嶏級銆?""
     actor = get_actor(request)
     conv = await db.get(Conversation, conversation_id)
-    if conv is None:
+    if conv is None or conv.status == "deleted":
         return JSONResponse(status_code=404, content=fail(40401, "conversation not found"))
 
     msgs = (
@@ -199,11 +263,21 @@ async def get_conversation(
         [{"role": t.get("role"), "content": t.get("content")} for t in short]
     )
     window = int(get_settings().context_window_tokens)
+    try:
+        resolved = await llm_gateway.resolve_for_conversation(db, conv)
+        if resolved.max_input_tokens and int(resolved.max_input_tokens) > 0:
+            window = int(resolved.max_input_tokens)
+    except ModelResolveError:
+        from app.modules.llm.model_resolve import resolve_window_tokens
+
+        window = resolve_window_tokens(getattr(conv, "selected_model", None))
 
     return ok(
         {
             "id": conv.id,
             "title": conv.title,
+            "agent_id": conv.agent_id,
+            "selected_model": getattr(conv, "selected_model", None),
             "messages": messages,
             "pending_cards": pending_cards,
             "feedbacks": feedback_map,
@@ -229,10 +303,13 @@ async def send_message(
         return JSONResponse(status_code=404, content=fail(40401, "conversation not found"))
 
     if await has_pending_required_card(db, body.conversation_id):
-        return JSONResponse(
-            status_code=422,
-            content=fail(42213, "pending required card; submit card-action first"),
-        )
+        if body.supersede_pending_card:
+            await cancel_pending_cards(db, conversation_id=body.conversation_id)
+        else:
+            return JSONResponse(
+                status_code=422,
+                content=fail(42213, "pending required card; submit card-action first"),
+            )
 
     db.add(
         Message(
@@ -248,7 +325,9 @@ async def send_message(
     memory_access, allow_memory_write = await resolve_agent_memory_policy(
         db, conv.agent_id
     )
-    model_ids = await resolve_agent_model_chain(db, conv.agent_id)
+    model_ids = await _resolve_model_ids(db, conv)
+    if isinstance(model_ids, JSONResponse):
+        return model_ids
     dept_ids = await load_user_department_ids(
         db, actor.user_id, extra_department_id=actor.department_id
     )
@@ -279,6 +358,29 @@ async def send_message(
     )
 
 
+@router.post("/messages/dismiss-card")
+async def dismiss_card(
+    body: DismissCardBody,
+    request: Request,
+    db: AsyncSession = Depends(get_db),
+):
+    """浣滃簾浼氳瘽 pending 浜や簰鍗★紙鍙寚瀹?card_id锛涘箓绛夛級銆?+
+    @author 璧垫尟鏄?+    @date 2026-07-30 14:41:54
+    """
+    actor = get_actor(request)
+    conv = await db.get(Conversation, body.conversation_id)
+    if conv is None:
+        return JSONResponse(status_code=404, content=fail(40401, "conversation not found"))
+    if conv.user_id != actor.user_id and not is_platform_admin(actor):
+        return JSONResponse(status_code=403, content=fail(40301, "forbidden"))
+    dismissed = await cancel_pending_cards(
+        db, conversation_id=body.conversation_id, card_id=body.card_id
+    )
+    return ok({"dismissed_ids": dismissed})
+
+
 @router.post("/messages/card-action")
 async def card_action(
     body: CardAction,
@@ -316,6 +418,9 @@ async def card_action(
     dept_ids = await load_user_department_ids(
         db, actor.user_id, extra_department_id=actor.department_id
     )
+    model_ids = await _resolve_model_ids(db, conv)
+    if isinstance(model_ids, JSONResponse):
+        return model_ids
 
     return StreamingResponse(
         _sse_from_events(
@@ -329,6 +434,7 @@ async def card_action(
                 department_ids=dept_ids,
                 role_ids=[] if admin else [actor.role],
                 is_platform_admin=admin,
+                model_ids=model_ids,
             )
         ),
         media_type="text/event-stream",
@@ -441,7 +547,9 @@ async def retry_message(
     memory_access, allow_memory_write = await resolve_agent_memory_policy(
         db, conv.agent_id if conv else None
     )
-    model_ids = await resolve_agent_model_chain(db, conv.agent_id if conv else None)
+    model_ids = await _resolve_model_ids(db, conv)
+    if isinstance(model_ids, JSONResponse):
+        return model_ids
     dept_ids = await load_user_department_ids(
         db, actor.user_id, extra_department_id=actor.department_id
     )

### tests/test_dismiss_card.py


#### FULL FILE (untracked)

"""dismiss-card / supersede_pending_card銆?
@author 璧垫尟鏄?@date 2026-07-30 14:40:55
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.shared.db import Base, get_db


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """瑙ｆ瀽 SSE 鏂囨湰涓?(event, payload) 鍒楄〃銆?""
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        elif line == "" and data_lines:
            payload = json.loads("\n".join(data_lines))
            events.append((event_name, payload))
            event_name = "message"
            data_lines = []
    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_send_blocked_without_supersede(client: AsyncClient) -> None:
    """鍚岀幇鏈夛細璇峰亣瑙﹀彂鍗″悗鐩存帴 send 鈫?42213銆?""
    conv = await client.post("/api/v1/conversations", json={"title": "璇峰亣"})
    cid = conv.json()["data"]["id"]
    await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "鎴戣璇峰亣"})
    blocked = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": cid, "content": "鍐嶅彂涓€鏉?},
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == 42213


@pytest.mark.asyncio
async def test_supersede_allows_send_and_cancels_card(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "璇峰亣"})
    cid = conv.json()["data"]["id"]
    await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "鎴戣璇峰亣"})
    ok = await client.post(
        "/api/v1/messages/send",
        json={
            "conversation_id": cid,
            "content": "鏀归棶鍒殑",
            "supersede_pending_card": True,
        },
    )
    assert ok.status_code == 200
    detail = await client.get(f"/api/v1/conversations/{cid}")
    pending = detail.json()["data"].get("pending_cards") or []
    assert pending == []


@pytest.mark.asyncio
async def test_dismiss_card_idempotent(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "璇峰亣"})
    cid = conv.json()["data"]["id"]
    first = await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "鎴戣璇峰亣"})
    assert first.status_code == 200
    # 浠?SSE 鍙?card_id锛屾垨 dismiss 鐪佺暐 card_id
    r1 = await client.post(
        "/api/v1/messages/dismiss-card",
        json={"conversation_id": cid},
    )
    assert r1.status_code == 200
    assert len(r1.json()["data"]["dismissed_ids"]) >= 1
    r2 = await client.post(
        "/api/v1/messages/dismiss-card",
        json={"conversation_id": cid},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["dismissed_ids"] == []


### docs/01-产品需求/API接口规范.md

diff --git "a/docs/01-\344\272\247\345\223\201\351\234\200\346\261\202/API\346\216\245\345\217\243\350\247\204\350\214\203.md" "b/docs/01-\344\272\247\345\223\201\351\234\200\346\261\202/API\346\216\245\345\217\243\350\247\204\350\214\203.md"
index e946fbd..471f985 100644
--- "a/docs/01-\344\272\247\345\223\201\351\234\200\346\261\202/API\346\216\245\345\217\243\350\247\204\350\214\203.md"
+++ "b/docs/01-\344\272\247\345\223\201\351\234\200\346\261\202/API\346\216\245\345\217\243\350\247\204\350\214\203.md"
@@ -39,7 +39,7 @@
 | 42210 | 422 | 鍗＄墖閲嶅鎻愪氦锛堝悓涓€ `card_id`锛?|
 | 42211 | 422 | 鍗＄墖宸茶繃鏈?/ 宸插彇娑?|
 | 42212 | 422 | 鍗＄墖 payload 鏍￠獙澶辫触锛堢己蹇呭～閫夐」/瀛楁锛?|
-| 42213 | 422 | 浼氳瘽瀛樺湪鏈畬鎴愮殑蹇呭～鍗＄墖锛岀姝㈢洿鎺?send锛堥』鍏?card-action锛?|
+| 42213 | 422 | 浼氳瘽瀛樺湪鏈畬鎴愮殑蹇呭～鍗＄墖锛岀姝㈢洿鎺?send锛堥』鍏?card-action锛屾垨 send 鏃朵紶 `supersede_pending_card=true` 浣滃簾鍚庣户缁級 |
 | 42901 | 429 | 鐢ㄦ埛閰嶉 |
 | 50002 | 502/500 | LLM fallback 鐢ㄥ敖 |
 
@@ -227,8 +227,10 @@ Web 绯荤粺瀵硅瘽椤电粦瀹氭湰缁勬帴鍙ｃ€? | 鏂规硶 | 璺緞 |
 |---|---|
 | POST | `/conversations` | `{agent_id?, title}`锛沗agent_id` 鍙┖鍒欒蛋鏅鸿兘璺敱 |
-| GET | `/conversations` 路 `.../messages` |
-| POST | `/messages/send` | SSE 娴佸紡锛堣涓嬶級 |
+| GET | `/conversations` 路 `.../messages` | 鍒楄〃浠?`status=active`锛涙櫘閫氱敤鎴蜂粎鏈汉 |
+| DELETE | `/conversations/{id}` | 杞垹锛坄status=deleted`锛夛紱浠呮湰浜烘垨骞冲彴绠＄悊鍛?|
+| POST | `/messages/send` | SSE 娴佸紡锛堣涓嬶級锛涘彲閫?`supersede_pending_card` |
+| POST | `/messages/dismiss-card` | 浣滃簾 pending 浜や簰鍗★紙`{conversation_id, card_id?}` 鈫?`{dismissed_ids}`锛?|
 | POST | `/messages/card-action` | 鐢ㄦ埛鎻愪氦鍗＄墖缁撴灉锛岀画璺戝璇濓紙鍙啀寮€ SSE锛?|
 | POST | `/messages/{id}/feedback` | `up`/`down` |
 | POST | `/messages/{id}/retry` | 鍘熸ā鍨嬮噸璇?|
@@ -239,11 +241,32 @@ Web 绯荤粺瀵硅瘽椤电粦瀹氭湰缁勬帴鍙ｃ€? |---|---|
 | `content_delta` | 鏂囨湰澧為噺 |
 | `citation` | RAG 寮曠敤 |
+| `stage` | 杩囩▼闃舵鑳跺泭锛歚{id,label,status}`锛沗status`=`running`/`done`/`error`锛涗粎娴佸紡锛屼笉钀藉簱 |
+| `thought_delta` | 鍚堟垚鎬濊€冨彊杩板閲忥細`{delta}`锛涗粎娴佸紡锛屼笉钀藉簱 |
 | `tool_call` / `skill_call` | 鎶€鑳?宸ュ叿璋冪敤杩涘害锛堝彲閫夊睍绀猴級 |
 | `card` | **浜や簰鍗＄墖**锛堢粨鏋勫寲 JSON锛岃 10.2锛?|
 | `route_clarify` | 鍙苟鍏?`card.type=route_clarify`锛涘吋瀹逛繚鐣?|
 | `message_end` | 鏈疆缁撴潫锛堣嫢瀛樺湪寰呯瓟蹇呭～鍗★紝`status=awaiting_card`锛?|
 
+鐢ㄦ埛榛樿 UI 浠?`stage` / `thought_delta` 涓轰富锛沗tool_call` / `skill_call` 浠嶅彲閫夛紝榛樿涓嶅睍绀?arguments銆?+
+`POST /messages/send` 璇锋眰浣擄細`{conversation_id, content, supersede_pending_card?}`銆? 
+鑻ヤ細璇濆瓨鍦?pending 蹇呭～鍗★細鏈紶 / `false` 浠嶈繑鍥?**42213**锛沗supersede_pending_card=true` 鏃跺厛浣滃簾鍏ㄩ儴 pending 鍗″啀鍙戦€併€? 
+`POST /messages/{id}/retry` **涓嶆敮鎸?* supersede锛屾湁 pending 蹇呭～鍗℃椂浠嶈繑鍥?42213銆?+
+### 10.1.1 浣滃簾鍗＄墖锛坄/messages/dismiss-card`锛?+
+```json
+{
+  "conversation_id": "conv_xxx",
+  "card_id": "crd_xxx"
+}
+```
+
+- `card_id` 鍙渷鐣ワ細浣滃簾璇ヤ細璇濆叏閮?`status=pending` 鍗°€?+- 鎴愬姛锛歚{ "dismissed_ids": ["crd_xxx", ...] }`锛涙棤鍙綔搴熷崱鏃惰繑鍥炵┖鏁扮粍锛堝箓绛夛級銆?+- 浠呬細璇濇湰浜烘垨骞冲彴绠＄悊鍛樸€?+
 ### 10.2 鍗＄墖杞借嵎锛坄card`锛? 
 ```json
@@ -331,12 +354,61 @@ Web 绯荤粺瀵硅瘽椤电粦瀹氭湰缁勬帴鍙ｃ€? |---|---|
 | `/providers` | LiteLLM 鍖呰鐨?Provider/妯″瀷锛涘崟浠峰彲閰?|
 | `/prompt-templates` | 妯℃澘鐗堟湰鍖?|
+| `/intent/l2-keywords` | L2 鎰忓浘鍏抽敭璇?CRUD锛堝钩鍙扮鐞嗗憳锛涘啓搴撳悗鍒?Redis锛?|
+| `/memory/extract-fields` | 璁板繂鎶藉彇瀛楁鐧藉悕鍗?CRUD锛堝钩鍙扮鐞嗗憳锛涘啓搴撳悗鍒?Redis锛?|
+| `/system/persona` | 绯荤粺浜烘牸 CRUD / 璇曡亰 / 鎭㈠榛樿锛堝钩鍙扮鐞嗗憳锛涘啓搴撳悗鍒?Redis锛?|
+| `/admin/llm-models` | LLM 妯″瀷鐩綍鍚屾/鍚仠/绯荤粺鐧藉悕鍗?Agent 缁戝畾锛堝钩鍙扮鐞嗗憳锛?|
+| `/llm-models/available` | 鍛樺伐绔寜浼氳瘽/Agent 鍙€夋ā鍨嬪垪琛?|
 | `/system-config/sensitive-words` | 鏁忔劅璇?|
 | `/system-config/webhooks` | 鍛婅 Webhook 鍒楄〃 |
 | `/api-keys` | OpenAPI Key 閰嶉 |
 
 LLM 璋冪敤涓€寰嬬粡鏈湴/闆嗙兢 **LiteLLM Proxy**锛屼笟鍔＄姝㈢洿杩炲巶鍟嗐€? 
+### 12.1 L2 鍏抽敭璇?`/intent/l2-keywords`
+
+鏉冮檺锛氫粎 `platform_admin` / `super_admin`銆傚啓鎿嶄綔鎴愬姛鍚庡叏閲忓埛鏂?Redis `za:intent:l2_catalog:v1`銆?+
+| 鏂规硶 | 璺緞 | 璇存槑 |
+|---|---|---|
+| GET | `/intent/l2-keywords` | 鍒嗛〉鍒楄〃锛圖B锛夛紱鍙€?`category` |
+| POST | `/intent/l2-keywords` | 鏂板锛沚ody: category/phrase/match_mode/enabled/priority/remark |
+| PATCH | `/intent/l2-keywords/{id}` | 鏇存柊 |
+| DELETE | `/intent/l2-keywords/{id}` | 杞垹 |
+| POST | `/intent/l2-keywords/reload-cache` | 寮哄埗 DB鈫扲edis |
+
+`match_mode`锛歚contains` \| `equals` \| `prefix`锛堢姝㈣嚜瀹氫箟 regex锛夈€?+
+### 12.2 绯荤粺浜烘牸 `/system/persona`
+
+鏉冮檺锛氫粎 `platform_admin` / `super_admin`銆傚啓鎿嶄綔鎴愬姛鍚庡埛鏂?Redis `za:system:persona:v1`銆傚钩鍙板畨鍏ㄦ涓轰唬鐮佸父閲忥紝绠＄悊绔彧璇汇€?+
+| 鏂规硶 | 璺緞 | 璇存槑 |
+|---|---|---|
+| GET | `/system/persona` | 璇婚厤缃?+ 缂撳瓨鐘舵€?+ `platform_safety` |
+| PUT | `/system/persona` | 鏇存柊 title/system_prompt/enabled锛涗箰瑙傞攣 `expected_revision` |
+| POST | `/system/persona/reload-cache` | 寮哄埗 DB鈫扲edis |
+| POST | `/system/persona/reset-default` | 鎭㈠绉嶅瓙 title/prompt锛沞nabled 淇濇寔 |
+| POST | `/system/persona/test` | 鏃犲壇浣滅敤璇曡亰锛沚ody: `message`, 鍙€?`system_prompt` |
+
+璇曡亰浠呮嫾锛氬钩鍙板畨鍏?+ 浜烘牸 + 鏋佺畝韬唤锛涗笉鍐欒蹇?浼氳瘽锛涘璁?`action=test`銆?+
+### 12.3 LLM 妯″瀷娌荤悊
+
+鏉冮檺锛氱鐞嗙浠?`platform_admin` / `super_admin`銆傜洰褰?MySQL 鏉冨▉锛孯edis `za:llm:models:v1` 鐑紦瀛樸€備笟鍔?LLM 璋冪敤缁熶竴缁?`LlmGateway`銆?+
+| 鏂规硶 | 璺緞 | 璇存槑 |
+|---|---|---|
+| GET | `/admin/llm-models` | 鐩綍鍒楄〃锛堝惈 `source_status`锛?|
+| POST | `/admin/llm-models/sync` | 浠?LiteLLM 鍚屾 |
+| PATCH | `/admin/llm-models/{id}` | 鍚仠銆佽ˉ `max_input_tokens`銆佺郴缁熺櫧鍚嶅崟 |
+| GET | `/admin/agents/{agent_id}/llm-models` | 璇?Agent 缁戝畾 |
+| PUT | `/admin/agents/{agent_id}/llm-models` | 鍏ㄩ噺鏇挎崲缁戝畾锛堝惈榛樿锛?|
+| GET | `/llm-models/available` | 鍛樺伐绔彲閫夊垪琛紱`conversation_id` 鎴?`agent_id` |
+| PATCH | `/conversations/{id}` | 鏇存柊 `selected_model`锛堢櫧鍚嶅崟鏍￠獙锛沗null` 娓呯┖锛?|
+
+`source_status`锛歚active` \| `incomplete` \| `missing_in_litellm`銆侺iteLLM 缂哄け寮哄埗 `enabled=false`锛涚鐞嗗憳鍏抽棴涓嶅悓姝ヨ嚜鍔ㄦ墦寮€銆傞潪娉曢€夋ā杩斿洖涓氬姟鐮?`40031`銆?+
 ---
 
 ## 13. 鐢ㄩ噺 `/usage` 路 瀹¤ `/audit-logs`
@@ -368,6 +440,10 @@ LLM 璋冪敤涓€寰嬬粡鏈湴/闆嗙兢 **LiteLLM Proxy**锛屼笟鍔＄姝㈢洿杩炲巶鍟嗐€? 
 | 鐗堟湰 | 璇存槑 |
 |---|---|
+| v0.8.3 | 杩炵画鍙戦€侊細`dismiss-card` + `supersede_pending_card`锛?2213 鏈?supersede 鏃朵粛杩斿洖 |
+| v0.8.2 | LLM 妯″瀷娌荤悊锛歚/admin/llm-models`銆佸憳宸ョ鍙€夊垪琛ㄤ笌浼氳瘽 `selected_model`锛涚粡 LlmGateway |
+| v0.8.1 | 绯荤粺浜烘牸 `/system/persona`锛堝畨鍏ㄦ鍙銆佽瘯鑱娿€佹仮澶嶉粯璁わ級锛涘榻?PRD D43鈥揇47 |
+| v0.7.5 | L2 鍏抽敭璇?`/intent/l2-keywords`锛圖B+Redis锛夛紱鍚﹀畾绾犳闂ㄧ |
 | v0.7.4 | 鍗＄墖閿欒鐮?42210鈥?2213锛沗ask_user` 鏄犲皠锛涘榻?D33 |
 | v0.7.3 | 浜や簰鍗＄墖 SSE `card` + `/messages/card-action`锛汚gent 鎻愰棶绫诲瀷锛涘榻?D31鈥揇32 |
 | v0.7.2 | 鍘绘帀 `/im/*`锛涘璇濅富鍏ュ彛鏄庣‘锛涢€氱煡/瀹℃壒璧?Web锛涘榻?PRD D27鈥揇30 |

### tests/test_dismiss_card.py (untracked full)
```python
"""dismiss-card / supersede_pending_card銆?
@author 璧垫尟鏄?@date 2026-07-30 14:40:55
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.shared.db import Base, get_db


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """瑙ｆ瀽 SSE 鏂囨湰涓?(event, payload) 鍒楄〃銆?""
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        elif line == "" and data_lines:
            payload = json.loads("\n".join(data_lines))
            events.append((event_name, payload))
            event_name = "message"
            data_lines = []
    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_send_blocked_without_supersede(client: AsyncClient) -> None:
    """鍚岀幇鏈夛細璇峰亣瑙﹀彂鍗″悗鐩存帴 send 鈫?42213銆?""
    conv = await client.post("/api/v1/conversations", json={"title": "璇峰亣"})
    cid = conv.json()["data"]["id"]
    await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "鎴戣璇峰亣"})
    blocked = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": cid, "content": "鍐嶅彂涓€鏉?},
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == 42213


@pytest.mark.asyncio
async def test_supersede_allows_send_and_cancels_card(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "璇峰亣"})
    cid = conv.json()["data"]["id"]
    await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "鎴戣璇峰亣"})
    ok = await client.post(
        "/api/v1/messages/send",
        json={
            "conversation_id": cid,
            "content": "鏀归棶鍒殑",
            "supersede_pending_card": True,
        },
    )
    assert ok.status_code == 200
    detail = await client.get(f"/api/v1/conversations/{cid}")
    pending = detail.json()["data"].get("pending_cards") or []
    assert pending == []


@pytest.mark.asyncio
async def test_dismiss_card_idempotent(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "璇峰亣"})
    cid = conv.json()["data"]["id"]
    first = await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "鎴戣璇峰亣"})
    assert first.status_code == 200
    # 浠?SSE 鍙?card_id锛屾垨 dismiss 鐪佺暐 card_id
    r1 = await client.post(
        "/api/v1/messages/dismiss-card",
        json={"conversation_id": cid},
    )
    assert r1.status_code == 200
    assert len(r1.json()["data"]["dismissed_ids"]) >= 1
    r2 = await client.post(
        "/api/v1/messages/dismiss-card",
        json={"conversation_id": cid},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["dismissed_ids"] == []
```
