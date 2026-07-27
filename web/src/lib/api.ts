/**
 * API 封装（经 Next rewrite 代理到 :8000）。
 * @author 赵振明
 * @date 2026-07-21 16:50:00
 */

export type ApiBody<T = unknown> = {
  code: number;
  message: string;
  data: T;
  request_id?: string;
};

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
  const body = (await res.json()) as ApiBody<T>;
  if (!res.ok && body.code === undefined) {
    throw new Error(`HTTP ${res.status}`);
  }
  return body;
}
