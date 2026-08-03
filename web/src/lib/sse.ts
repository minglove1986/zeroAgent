/**
 * 消费 POST SSE（messages/send · card-action）。
 * @author 赵振明
 * @date 2026-07-30 12:09:46
 */

export type SseHandler = (event: string, data: Record<string, unknown>) => void;

/**
 * 将 API 错误响应解析为可读中文提示（避免整段 JSON 甩到页面）。
 */
export function formatApiErrorText(raw: string, status: number): string {
  const text = (raw || "").trim();
  if (!text) return `请求失败（HTTP ${status}）`;
  try {
    const body = JSON.parse(text) as {
      code?: number;
      message?: string;
    };
    const msg = String(body.message || "").trim();
    const code = Number(body.code);
    if (code === 40031 || /model not allowed|model disabled|model missing|model not in/i.test(msg)) {
      // 兼容旧英文文案
      if (/not allowed for system chat/i.test(msg)) {
        const name = msg.split(":").pop()?.trim() || "当前模型";
        return `模型「${name}」未开放系统对话，请在输入区切换可用模型后再发送`;
      }
      if (/model disabled/i.test(msg)) {
        const name = msg.split(":").pop()?.trim() || "当前模型";
        return `模型「${name}」已停用，请切换其他可用模型后再发送`;
      }
      if (msg) return msg;
    }
    if (msg) return msg;
  } catch {
    /* 非 JSON */
  }
  if (text.length > 180) return `请求失败（HTTP ${status}）`;
  return text;
}

/**
 * 发起 POST SSE 请求并逐条解析 event/data；signal abort 时 fetch 或 reader.read 抛出 AbortError，向上透传。
 */
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
  if (!res.ok || !res.body) {
    const text = await res.text();
    throw new Error(formatApiErrorText(text, res.status));
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";
  let dataLines: string[] = [];

  const flush = () => {
    if (!dataLines.length) return;
    const raw = dataLines.join("\n");
    dataLines = [];
    try {
      const data = JSON.parse(raw) as Record<string, unknown>;
      onEvent(eventName, data);
    } catch {
      onEvent(eventName, { raw });
    }
    eventName = "message";
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      } else if (line === "") {
        flush();
      }
    }
  }
  flush();
}
