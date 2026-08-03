# Final whole-feature review package: chat send queue
## Spec
docs/superpowers/specs/2026-07-30-chat-send-queue-design.md
## Plan
docs/superpowers/plans/2026-07-30-chat-send-queue.md
## Prior Minor ledger
- Task1: dirty tree pollution; cancel-before-send intermediate state (plan-mandated)
- Task2: sse.ts had parallel formatApiErrorText changes
- Task3: empty string enqueue (page must guard)
- Task4: no browser E2E yet; drain gap focus optional
## Feature files
src/app/modules/conversation/runtime.py
src/app/api/v1/messages.py
tests/test_dismiss_card.py
web/src/lib/sse.ts
web/src/lib/chatSendQueue.ts
web/src/lib/chatSendQueue.test.ts
web/src/app/chat/page.tsx
web/src/app/globals.css
docs/superpowers/specs/2026-07-30-chat-send-queue-design.md
## Grep evidence

### cancel_pending_cards

src/app\api\v1\messages.py:24:    cancel_pending_cards,
src/app\api\v1\messages.py:307:            await cancel_pending_cards(db, conversation_id=body.conversation_id)
src/app\api\v1\messages.py:378:    dismissed = await cancel_pending_cards(
src/app\modules\conversation\runtime.py:294:async def cancel_pending_cards(

### supersede_pending_card

web/src\app\chat\page.tsx:786:   * 鍙戣捣 messages/send锛堝缁?supersede_pending_card锛夛紱鏀寔 Abort 涓庡嚭闃熺画鍙戙€?web/src\app\chat\page.tsx:827:          supersede_pending_card: true,
tests\test_dismiss_card.py:1:"""dismiss-card / supersede_pending_card銆?tests\test_dismiss_card.py:84:            "supersede_pending_card": True,
src/app\api\v1\messages.py:68:    supersede_pending_card: bool = False
src/app\api\v1\messages.py:306:        if body.supersede_pending_card:

### dismiss-card

tests\test_dismiss_card.py:1:"""dismiss-card / supersede_pending_card銆?tests\test_dismiss_card.py:101:        "/api/v1/messages/dismiss-card",
tests\test_dismiss_card.py:107:        "/api/v1/messages/dismiss-card",
src/app\api\v1\messages.py:361:@router.post("/messages/dismiss-card")

### CHAT_SEND_QUEUE_MAX

web/src\lib\chatSendQueue.ts:7:export const CHAT_SEND_QUEUE_MAX = 5;
web/src\lib\chatSendQueue.ts:32: * 鍏ラ槦锛歲ueued 宸茶揪 CHAT_SEND_QUEUE_MAX 鏃惰繑鍥?full銆?web/src\lib\chatSendQueue.ts:38:  if (countQueued(items) >= CHAT_SEND_QUEUE_MAX) {
web/src\lib\chatSendQueue.test.ts:12:  CHAT_SEND_QUEUE_MAX,
web/src\lib\chatSendQueue.test.ts:35:  it("CHAT_SEND_QUEUE_MAX 鎭掍负 5", () => {
web/src\lib\chatSendQueue.test.ts:36:    assert.equal(CHAT_SEND_QUEUE_MAX, 5);
web/src\app\chat\page.tsx:34:  CHAT_SEND_QUEUE_MAX,
web/src\app\chat\page.tsx:947:    if (queuedCount >= CHAT_SEND_QUEUE_MAX && phase !== "idle") {

### focusComposer

web/src\app\chat\page.tsx:288:  function focusComposer() {
web/src\app\chat\page.tsx:580:    focusComposer();
web/src\app\chat\page.tsx:652:      focusComposer();
web/src\app\chat\page.tsx:682:    focusComposer();
web/src\app\chat\page.tsx:782:    focusComposer();
web/src\app\chat\page.tsx:935:    focusComposer();
web/src\app\chat\page.tsx:953:    focusComposer();

### onStop

web/src\app\chat\page.tsx:930:  function onStop() {
web/src\app\chat\page.tsx:1675:                    onClick={onStop}

### onRemoveQueued

web/src\app\chat\page.tsx:665:  function onRemoveQueued(localId: string) {
web/src\app\chat\page.tsx:1390:                              onClick={() => onRemoveQueued(item.queueLocalId!)}

### onRetryFailedQueue

web/src\app\chat\page.tsx:690:  function onRetryFailedQueue(localId: string) {
web/src\app\chat\page.tsx:1405:                              onClick={() => onRetryFailedQueue(item.queueLocalId!)}

### signal: options

web/src\lib\sse.ts:60:    signal: options?.signal,
