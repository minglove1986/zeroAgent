/**
 * 聊天发送 FIFO 队列纯函数（上限 5，仅统计 queued）。
 * @author 赵振明
 * @date 2026-07-30 14:48:53
 */

export const CHAT_SEND_QUEUE_MAX = 5;

export type QueueItemStatus = "queued" | "sending" | "sent" | "failed";

export type QueueItem = {
  localId: string;
  text: string;
  status: QueueItemStatus;
};

/**
 * 生成队列项 localId。
 */
function newLocalId(): string {
  return crypto.randomUUID();
}

/**
 * 统计 queued 状态项数量（上限判定仅看 queued）。
 */
function countQueued(items: QueueItem[]): number {
  return items.filter((item) => item.status === "queued").length;
}

/**
 * 入队：queued 已达 CHAT_SEND_QUEUE_MAX 时返回 full。
 */
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
 * 取出最早 queued 项并标为 sending；无 queued 返回 null。
 */
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
 * 按 localId 更新队列项状态。
 */
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
 * 移除指定 queued 项；sending/sent/failed 不受影响。
 */
export function removeQueued(items: QueueItem[], localId: string): QueueItem[] {
  return items.filter(
    (item) => !(item.localId === localId && item.status === "queued"),
  );
}

/**
 * 清空队列，返回空数组。
 */
export function clearQueue(): QueueItem[] {
  return [];
}
