# 系统对话连续发送队列 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 聊天页支持流式中排队连发、停止生成、发送作废 pending 卡，并在每次发送后自动聚焦输入框。

**Architecture:** 后端用 `message_cards.status=cancelled` + `dismiss-card` / `supersede_pending_card` 解除 42213；前端本会话 FIFO 队列串行调现有 SSE；`postSse` 支持 AbortSignal；焦点在发送与流结束边界恢复。

**Tech Stack:** FastAPI、SQLAlchemy AsyncSession、pytest/httpx；Next.js React、`web/src/lib/sse.ts`、`web/src/app/chat/page.tsx`。

**Spec:** `docs/superpowers/specs/2026-07-30-chat-send-queue-design.md`

## Global Constraints

- 单租户；不做服务端持久队列 / 并行多 SSE / 服务端强杀 LLM。
- 队列上限 **5**；同会话串行一轮。
- 库表已有 `cancelled`，**禁止**为卡片作废新建 migration。
- 注释：`@author 赵振明`；时间用东八区实时 `yyyy-MM-dd HH:mm:ss`。
- 提交：仅当用户明确要求时 commit；计划中的 Commit 步默认跳过。
- 本地端口：API `:8000`，Web `:3000`。

## File map

| 文件 | 职责 |
|---|---|
| `src/app/modules/conversation/runtime.py` | `cancel_pending_cards(...)` 条件更新 pending→cancelled |
| `src/app/api/v1/messages.py` | `DismissCard` body、`dismiss-card` 路由、`MessageSend.supersede_pending_card` |
| `tests/test_message_sse.py`（或新建 `tests/test_dismiss_card.py`） | dismiss / supersede / 42213 回归 |
| `docs/01-产品需求/API接口规范.md` | 文档同步 |
| `web/src/lib/sse.ts` | `signal?: AbortSignal`；AbortError 可识别 |
| `web/src/lib/chatSendQueue.ts` | 队列纯函数（上限、入队、出队、失败） |
| `web/src/app/chat/page.tsx` | 状态机、停止、排队 UI、焦点、supersede |
| `web/src/app/globals.css` | 排队标签 / 已跳过 / 已停止 轻量样式 |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1: 后端 cancel_pending_cards + dismiss-card + supersede

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`（`has_pending_required_card` 附近）
- Modify: `src/app/api/v1/messages.py`（`MessageSend`、`send_message`、新增路由）
- Test: `tests/test_dismiss_card.py`（新建）
- Modify: `docs/01-产品需求/API接口规范.md` §10

**Interfaces:**
- Consumes: `MessageCard`，`has_pending_required_card`，现有 `fail`/`ok`/`get_actor`
- Produces:
  - `async def cancel_pending_cards(db, *, conversation_id: str, card_id: str | None = None) -> list[str]`
  - `POST /api/v1/messages/dismiss-card` → `{ dismissed_ids: string[] }`
  - `MessageSend.supersede_pending_card: bool = False`

- [ ] **Step 1: 写失败单测**

创建 `tests/test_dismiss_card.py`（复用 `test_message_sse.py` 的 client fixture / `_parse_sse` 模式；可复制 fixture）：

```python
"""dismiss-card / supersede_pending_card。

@author 赵振明
@date <东八区实时>
"""

@pytest.mark.asyncio
async def test_send_blocked_without_supersede(client):
    # 同现有：请假触发卡后直接 send → 42213
    ...

@pytest.mark.asyncio
async def test_supersede_allows_send_and_cancels_card(client):
    conv = await client.post("/api/v1/conversations", json={"title": "请假"})
    cid = conv.json()["data"]["id"]
    await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "我要请假"})
    ok = await client.post(
        "/api/v1/messages/send",
        json={
            "conversation_id": cid,
            "content": "改问别的",
            "supersede_pending_card": True,
        },
    )
    assert ok.status_code == 200
    detail = await client.get(f"/api/v1/conversations/{cid}")
    pending = detail.json()["data"].get("pending_cards") or []
    assert pending == []

@pytest.mark.asyncio
async def test_dismiss_card_idempotent(client):
    conv = await client.post("/api/v1/conversations", json={"title": "请假"})
    cid = conv.json()["data"]["id"]
    first = await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "我要请假"})
    # 从 SSE 取 card_id，或 dismiss 省略 card_id
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

- [ ] **Step 2: 跑测确认失败**

Run: `& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_dismiss_card.py -v --tb=short`  
Expected: FAIL（路由/字段不存在）

- [ ] **Step 3: 实现 `cancel_pending_cards`**

在 `runtime.py`：

```python
async def cancel_pending_cards(
    db: AsyncSession,
    *,
    conversation_id: str,
    card_id: str | None = None,
) -> list[str]:
    """将 pending 卡标为 cancelled；返回实际作废的 id 列表。"""
    stmt = select(MessageCard).where(
        MessageCard.conversation_id == conversation_id,
        MessageCard.status == "pending",
    )
    if card_id:
        stmt = stmt.where(MessageCard.id == card_id)
    rows = list((await db.execute(stmt)).scalars().all())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ids: list[str] = []
    for row in rows:
        row.status = "cancelled"
        row.submitted_at = now
        row.result = json.dumps(
            {"dismissed": True, "reason": "user_supersede"},
            ensure_ascii=False,
        )
        ids.append(row.id)
    if ids:
        await db.commit()
    return ids
```

- [ ] **Step 4: 实现 API**

`messages.py`：

```python
class MessageSend(BaseModel):
    conversation_id: str
    content: str
    supersede_pending_card: bool = False

class DismissCardBody(BaseModel):
    conversation_id: str
    card_id: str | None = None
```

`send_message` 中替换 42213 块：

```python
if await has_pending_required_card(db, body.conversation_id):
    if body.supersede_pending_card:
        await cancel_pending_cards(db, conversation_id=body.conversation_id)
    else:
        return JSONResponse(
            status_code=422,
            content=fail(42213, "pending required card; submit card-action first"),
        )
```

新增：

```python
@router.post("/messages/dismiss-card")
async def dismiss_card(body: DismissCardBody, request: Request, db: AsyncSession = Depends(get_db)):
    actor = get_actor(request)
    conv = await db.get(Conversation, body.conversation_id)
    if conv is None:
        return JSONResponse(status_code=404, content=fail(40401, "conversation not found"))
    if conv.user_id != actor.user_id and not is_platform_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "forbidden"))
    dismissed = await cancel_pending_cards(
        db, conversation_id=body.conversation_id, card_id=body.card_id
    )
    return ok({"dismissed_ids": dismissed})
```

`retry` 路径若也检查 42213：保持原样（重试不 supersede），除非产品要求——**本期不改 retry**。

- [ ] **Step 5: 更新 API 规范**

在 §10 表格增加 `POST /messages/dismiss-card`；`MessageSend` 增加 `supersede_pending_card`；42213 说明：未 supersede 时仍返回。

- [ ] **Step 6: 跑测通过**

Run: 同上 pytest  
Expected: PASS；并跑 `tests/test_message_sse.py::test_send_blocked_when_pending_required_card` 仍 PASS。

- [ ] **Step 7: Commit（仅用户要求时）**

```bash
git add src/app/modules/conversation/runtime.py src/app/api/v1/messages.py tests/test_dismiss_card.py "docs/01-产品需求/API接口规范.md"
git commit -m "feat: dismiss pending cards and supersede on send"
```

---

### Task 2: postSse 支持 AbortSignal

**Files:**
- Modify: `web/src/lib/sse.ts`
- Test: 可选手工；若有前端单测框架则加，否则用 Chat 联调验收

**Interfaces:**
- Consumes: 现有 `postSse(path, body, onEvent)`
- Produces: `postSse(path, body, onEvent, options?: { signal?: AbortSignal })`；abort 时抛出 `DOMException`/`Error` name=`AbortError`

- [ ] **Step 1: 改签名并传入 fetch**

```typescript
export async function postSse(
  path: string,
  body: unknown,
  onEvent: SseHandler,
  options?: { signal?: AbortSignal },
): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    cache: "no-store",
    signal: options?.signal,
  });
  // ... 读流循环不变；若 signal abort，reader.read 会抛 AbortError，向上抛出
}
```

- [ ] **Step 2: 确认所有调用方兼容**（第 4 参数可选，现有 `postSse(a,b,c)` 无需改）

- [ ] **Step 3: Commit（仅用户要求时）**

---

### Task 3: chatSendQueue 纯函数

**Files:**
- Create: `web/src/lib/chatSendQueue.ts`
- Create: `web/src/lib/chatSendQueue.test.ts`（若项目无 vitest/jest，改为 `tests` 旁文档化 + 用 node 断言脚本；优先检查 `web/package.json` 测试命令；**无测试跑法则用 `node --test` 或把逻辑测放在后端无关的最小 assert 文件**）

**Interfaces:**
- Produces:

```typescript
export const CHAT_SEND_QUEUE_MAX = 5;

export type QueueItemStatus = "queued" | "sending" | "sent" | "failed";
export type QueueItem = { localId: string; text: string; status: QueueItemStatus };

export function enqueue(items: QueueItem[], text: string): { ok: true; items: QueueItem[] } | { ok: false; reason: "full" };
export function dequeueForSend(items: QueueItem[]): { head: QueueItem; rest: QueueItem[] } | null;
export function markStatus(items: QueueItem[], localId: string, status: QueueItemStatus): QueueItem[];
export function removeQueued(items: QueueItem[], localId: string): QueueItem[];
export function clearQueue(): QueueItem[]; // 返回 []
```

- [ ] **Step 1: 写测试（或 assert 脚本）**

```typescript
// enqueue 满 5 返回 full；dequeue 取最早 queued 并标 sending；removeQueued 只删 queued
```

- [ ] **Step 2: 实现使测试通过**

- [ ] **Step 3: Commit（仅用户要求时）**

---

### Task 4: ChatPage 队列状态机 + 停止 + supersede + 焦点

**Files:**
- Modify: `web/src/app/chat/page.tsx`
- Modify: `web/src/app/globals.css`（`.chat-queue-tag` / `.chat-card-skipped` / `.chat-stopped-hint`）

**Interfaces:**
- Consumes: `postSse(..., { signal })`、`enqueue/dequeue/...`、`apiJson` dismiss（可选，优先 send 带 supersede）
- Produces: 可连发 UI；停止；焦点恢复

- [ ] **Step 1: 增加 refs/state**

```typescript
const abortRef = useRef<AbortController | null>(null);
const [sendQueue, setSendQueue] = useState<QueueItem[]>([]);
const [streamPhase, setStreamPhase] = useState<"idle" | "streaming" | "stopping" | "draining">("idle");
// busy 可派生：streamPhase !== "idle" || sendQueue.some(s => s.status === "sending")
```

- [ ] **Step 2: `focusComposer` 辅助**

```typescript
function focusComposer() {
  requestAnimationFrame(() => {
    textareaRef.current?.focus();
  });
}
```

- [ ] **Step 3: 重构 `sendText`**

- 接收 `text`；`setBusy`/`streamPhase` 管理  
- body 增加 `supersede_pending_card: true`  
- 创建 `AbortController`，`abortRef.current = ac`，`postSse(..., { signal: ac.signal })`  
- catch：若 `err.name === "AbortError"` → 当前 assistant 追加「已停止」提示，**不**当发送失败 toast  
- `finally`：清 abortRef；若队列有 `queued` → `draining` + `dequeueForSend` + 递归/`void pumpQueue()`；否则 `idle` + `focusComposer()`  
- 成功出 card 时仍 `setPendingCard`；下一轮出队 send 因 supersede 会作废  

- [ ] **Step 4: 重构 `onSubmit`**

```typescript
// 伪代码
const text = input.trim();
if (!text || loading) return;
if (sendQueue.filter(i => i.status === "queued").length >= CHAT_SEND_QUEUE_MAX && streamPhase !== "idle") {
  setError("最多排队 5 条，请等待或停止后发送");
  return;
}
setInput("");
focusComposer();
// 乐观用户气泡（含排队标记）
if (streamPhase === "idle" && !sendQueue.some(i => i.status === "sending")) {
  void sendText(text);
} else {
  const r = enqueue(sendQueue, text);
  if (!r.ok) { setError("..."); return; }
  setSendQueue(r.items);
  // items 里追加 user 气泡，标记 queue
}
```

- [ ] **Step 5: 停止按钮**

流式中主按钮文案「停止」：

```typescript
function onStop() {
  abortRef.current?.abort();
  setStreamPhase("stopping");
  focusComposer();
}
```

- [ ] **Step 6: 解除 `pendingCard` 对输入的硬禁**

- 输入框 / 发送：允许在有卡时输入；发送走 supersede  
- 卡片操作区：若本地标记 `skipped` 则隐藏提交  
- 切会话 / 新对话：`abortRef.current?.abort()`；`setSendQueue([])`；`setStreamPhase("idle")`  
- `streaming` 时禁用选模与 retry；**允许**切会话（先 abort+清队列）

- [ ] **Step 7: 卡片提交成功后 `focusComposer()`**

- [ ] **Step 8: 样式**

排队标签、已跳过卡、已停止 hint 用现有 chat 变量色，轻量即可。

- [ ] **Step 9: 手动验收清单**

1. 流式中连发 3 条 → 串行回复  
2. 停止 → 队首立刻发；焦点在输入框  
3. 请假出卡后直接打字发送 → 卡「已跳过」且新回合开始  
4. 发送后不点输入框即可继续键入  
5. 队列满 5 有提示  

- [ ] **Step 10: Commit（仅用户要求时）**

---

### Task 5: CHECKPOINT

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`

- [ ] **Step 1: 覆盖「当前断点」+ 追加日志**

写明：连续发送队列已实现；测：dismiss 单测 + 手动清单；下一步：rebuild api + 硬刷新 web。

- [ ] **Step 2: 规格状态保持「已批准」；实现完成后可改为「已落地」**

---

## Spec coverage self-check

| 规格项 | Task |
|---|---|
| FIFO 排队上限 5 | Task 3–4 |
| 停止 + Abort | Task 2、4 |
| dismiss-card / supersede / 42213 | Task 1 |
| 发送后 / 流结束聚焦 | Task 4 |
| 卡已跳过 UI | Task 4 |
| 切会话 abort+清队列 | Task 4 |
| API 文档 | Task 1 |
| 不做服务端队列 / 强杀 LLM | Global Constraints |

## Placeholder scan

无 TBD；Commit 步受用户规则约束默认跳过。
