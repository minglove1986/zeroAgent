/**
 * SSE 上游代理：避免 Next rewrite 整包缓冲导致非流式。
 * @author 赵振明
 * @date 2026-07-22 08:47:00
 */

const API = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request): Promise<Response> {
  const upstream = await fetch(`${API}/api/v1/messages/send`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      Cookie: req.headers.get("cookie") ?? "",
    },
    body: await req.text(),
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
