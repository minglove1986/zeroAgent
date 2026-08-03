# Review package Task 3
## chatSendQueue.ts
```typescript
/**
 * 鑱婂ぉ鍙戦€?FIFO 闃熷垪绾嚱鏁帮紙涓婇檺 5锛屼粎缁熻 queued锛夈€? * @author 璧垫尟鏄? * @date 2026-07-30 14:48:53
 */

export const CHAT_SEND_QUEUE_MAX = 5;

export type QueueItemStatus = "queued" | "sending" | "sent" | "failed";

export type QueueItem = {
  localId: string;
  text: string;
  status: QueueItemStatus;
};

/**
 * 鐢熸垚闃熷垪椤?localId銆? */
function newLocalId(): string {
  return crypto.randomUUID();
}

/**
 * 缁熻 queued 鐘舵€侀」鏁伴噺锛堜笂闄愬垽瀹氫粎鐪?queued锛夈€? */
function countQueued(items: QueueItem[]): number {
  return items.filter((item) => item.status === "queued").length;
}

/**
 * 鍏ラ槦锛歲ueued 宸茶揪 CHAT_SEND_QUEUE_MAX 鏃惰繑鍥?full銆? */
export function enqueue(
  items: QueueItem[],
  text: string,
): { ok: true; items: QueueItem[] } | { ok: false; reason: "full" } {
  if (countQueued(items) >= CHAT_SEND_QUEUE_MAX) {
    return { ok: false, reason: "full" };
  }
  const item: QueueItem = {
    localId: newLocalId(),
    text: text.trim(),
    status: "queued",
  };
  return { ok: true, items: [...items, item] };
}

/**
 * 鍙栧嚭鏈€鏃?queued 椤瑰苟鏍囦负 sending锛涙棤 queued 杩斿洖 null銆? */
export function dequeueForSend(
  items: QueueItem[],
): { head: QueueItem; rest: QueueItem[] } | null {
  const idx = items.findIndex((item) => item.status === "queued");
  if (idx < 0) {
    return null;
  }
  const head: QueueItem = { ...items[idx], status: "sending" };
  const rest = items.map((item, i) => (i === idx ? head : item));
  return { head, rest };
}

/**
 * 鎸?localId 鏇存柊闃熷垪椤圭姸鎬併€? */
export function markStatus(
  items: QueueItem[],
  localId: string,
  status: QueueItemStatus,
): QueueItem[] {
  return items.map((item) =>
    item.localId === localId ? { ...item, status } : item,
  );
}

/**
 * 绉婚櫎鎸囧畾 queued 椤癸紱sending/sent/failed 涓嶅彈褰卞搷銆? */
export function removeQueued(items: QueueItem[], localId: string): QueueItem[] {
  return items.filter(
    (item) => !(item.localId === localId && item.status === "queued"),
  );
}

/**
 * 娓呯┖闃熷垪锛岃繑鍥炵┖鏁扮粍銆? */
export function clearQueue(): QueueItem[] {
  return [];
}

```
## chatSendQueue.test.ts
```typescript
/**
 * chatSendQueue 绾嚱鏁板崟娴嬶紙node --test锛夈€? * @author 璧垫尟鏄? * @date 2026-07-30 14:48:53
 */
// @ts-nocheck 鈥?Node --test 闇€ .ts 鎵╁睍鍚嶅鍏ワ紝涓?bundler tsconfig 涓嶅吋瀹?
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  CHAT_SEND_QUEUE_MAX,
  clearQueue,
  dequeueForSend,
  enqueue,
  markStatus,
  removeQueued,
  type QueueItem,
} from "./chatSendQueue.ts";

function seedQueued(count: number, prefix = "msg"): QueueItem[] {
  const items: QueueItem[] = [];
  for (let i = 0; i < count; i += 1) {
    const r = enqueue(items, `${prefix}-${i}`);
    assert.equal(r.ok, true);
    if (r.ok) {
      items.length = 0;
      items.push(...r.items);
    }
  }
  return items;
}

describe("chatSendQueue", () => {
  it("CHAT_SEND_QUEUE_MAX 鎭掍负 5", () => {
    assert.equal(CHAT_SEND_QUEUE_MAX, 5);
  });

  it("enqueue 婊?5 鏉?queued 鏃惰繑鍥?full", () => {
    const items = seedQueued(5);
    const sixth = enqueue(items, "overflow");
    assert.deepEqual(sixth, { ok: false, reason: "full" });
  });

  it("sending/sent/failed 涓嶈鍏?queued 涓婇檺", () => {
    const base = seedQueued(4);
    const sending: QueueItem = {
      localId: "in-flight",
      text: "sending",
      status: "sending",
    };
    const withSending = [...base, sending];
    const next = enqueue(withSending, "still-room");
    assert.equal(next.ok, true);
    if (next.ok) {
      assert.equal(
        next.items.filter((i) => i.status === "queued").length,
        5,
      );
    }
  });

  it("dequeueForSend 鍙栨渶鏃?queued 骞舵爣 sending", () => {
    const items = seedQueued(3);
    const firstId = items[0].localId;
    const result = dequeueForSend(items);
    assert.ok(result);
    assert.equal(result.head.localId, firstId);
    assert.equal(result.head.status, "sending");
    assert.equal(result.head.text, "msg-0");
    const inRest = result.rest.find((i) => i.localId === firstId);
    assert.ok(inRest);
    assert.equal(inRest?.status, "sending");
    assert.equal(
      result.rest.filter((i) => i.status === "queued").length,
      2,
    );
  });

  it("dequeueForSend 鏃?queued 鏃惰繑鍥?null", () => {
    assert.equal(dequeueForSend([]), null);
    assert.equal(
      dequeueForSend([
        { localId: "a", text: "x", status: "sending" },
        { localId: "b", text: "y", status: "sent" },
      ]),
      null,
    );
  });

  it("removeQueued 浠呭垹闄?queued 椤?, () => {
    const items: QueueItem[] = [
      { localId: "q1", text: "a", status: "queued" },
      { localId: "s1", text: "b", status: "sending" },
      { localId: "q2", text: "c", status: "queued" },
    ];
    const after = removeQueued(items, "q1");
    assert.deepEqual(after, [
      { localId: "s1", text: "b", status: "sending" },
      { localId: "q2", text: "c", status: "queued" },
    ]);
    assert.deepEqual(removeQueued(items, "s1"), items);
    assert.deepEqual(removeQueued(items, "missing"), items);
  });

  it("markStatus 鎸?localId 鏇存柊鐘舵€?, () => {
    const items = seedQueued(1);
    const id = items[0].localId;
    const updated = markStatus(items, id, "failed");
    assert.equal(updated[0].status, "failed");
    assert.equal(items[0].status, "queued");
  });

  it("clearQueue 杩斿洖绌烘暟缁?, () => {
    assert.deepEqual(clearQueue(), []);
  });
});

```
