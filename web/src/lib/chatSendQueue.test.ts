/**
 * chatSendQueue 纯函数单测（node --test）。
 * @author 赵振明
 * @date 2026-07-30 14:48:53
 */
// @ts-nocheck — Node --test 需 .ts 扩展名导入，与 bundler tsconfig 不兼容

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
  it("CHAT_SEND_QUEUE_MAX 恒为 5", () => {
    assert.equal(CHAT_SEND_QUEUE_MAX, 5);
  });

  it("enqueue 满 5 条 queued 时返回 full", () => {
    const items = seedQueued(5);
    const sixth = enqueue(items, "overflow");
    assert.deepEqual(sixth, { ok: false, reason: "full" });
  });

  it("sending/sent/failed 不计入 queued 上限", () => {
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

  it("dequeueForSend 取最早 queued 并标 sending", () => {
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

  it("dequeueForSend 无 queued 时返回 null", () => {
    assert.equal(dequeueForSend([]), null);
    assert.equal(
      dequeueForSend([
        { localId: "a", text: "x", status: "sending" },
        { localId: "b", text: "y", status: "sent" },
      ]),
      null,
    );
  });

  it("removeQueued 仅删除 queued 项", () => {
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

  it("markStatus 按 localId 更新状态", () => {
    const items = seedQueued(1);
    const id = items[0].localId;
    const updated = markStatus(items, id, "failed");
    assert.equal(updated[0].status, "failed");
    assert.equal(items[0].status, "queued");
  });

  it("clearQueue 返回空数组", () => {
    assert.deepEqual(clearQueue(), []);
  });
});
