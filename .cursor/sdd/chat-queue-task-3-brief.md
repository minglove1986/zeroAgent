### Task 3: chatSendQueue 绾嚱鏁?
**Files:**
- Create: `web/src/lib/chatSendQueue.ts`
- Create: `web/src/lib/chatSendQueue.test.ts`锛堣嫢椤圭洰鏃?vitest/jest锛屾敼涓?`tests` 鏃佹枃妗ｅ寲 + 鐢?node 鏂█鑴氭湰锛涗紭鍏堟鏌?`web/package.json` 娴嬭瘯鍛戒护锛?*鏃犳祴璇曡窇娉曞垯鐢?`node --test` 鎴栨妸閫昏緫娴嬫斁鍦ㄥ悗绔棤鍏崇殑鏈€灏?assert 鏂囦欢**锛?
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
export function clearQueue(): QueueItem[]; // 杩斿洖 []
```

- [ ] **Step 1: 鍐欐祴璇曪紙鎴?assert 鑴氭湰锛?*

```typescript
// enqueue 婊?5 杩斿洖 full锛沝equeue 鍙栨渶鏃?queued 骞舵爣 sending锛況emoveQueued 鍙垹 queued
```

- [ ] **Step 2: 瀹炵幇浣挎祴璇曢€氳繃**

- [ ] **Step 3: Commit锛堜粎鐢ㄦ埛瑕佹眰鏃讹級**

---
