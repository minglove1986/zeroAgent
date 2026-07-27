/**
 * 消息重试 SSE 代理（避免 rewrite 缓冲）。
 * @author 赵振明
 * @date 2026-07-22 09:32:36
 */

const API = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  ctx: { params: Promise<{ messageId: string }> },
): Promise<Response> {
  const { messageId } = await ctx.params;
  const upstream = await fetch(`${API}/api/v1/messages/${messageId}/retry`, {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      Cookie: req.headers.get("cookie") ?? "",
    },
    cache: "no-store",
  });

  if (!upstream.body) {
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type":
        upstream.headers.get("Content-Type") || "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
