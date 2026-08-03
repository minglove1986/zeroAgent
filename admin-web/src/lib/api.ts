/**
 * 管理端同源 API 封装（经 Next rewrite 代理到 FastAPI，携带 Session Cookie）。
 *
 * @author 赵振明
 * @date 2026-07-29 15:10:45
 */

export type ApiBody<T = unknown> = {
  code: number;
  message: string;
  data?: T;
  request_id?: string;
};

/**
 * 发起 JSON 请求并解析统一响应体；始终携带 credentials。
 */
export async function apiJson<T>(
  path: string,
  init?: RequestInit,
): Promise<ApiBody<T>> {
  const res = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  let body: ApiBody<T>;
  try {
    body = (await res.json()) as ApiBody<T>;
  } catch {
    throw new Error(`HTTP ${res.status}`);
  }
  if (!res.ok && body.code === undefined) {
    throw new Error(`HTTP ${res.status}`);
  }
  return body;
}
