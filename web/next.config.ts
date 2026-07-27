import type { NextConfig } from "next";

/**
 * 其余 /api 走 rewrite；messages/send 与 card-action 由 App Router route 流式代理
 *（Route Handler 优先于 rewrite，避免 SSE 被整包缓冲）。
 */
const nextConfig: NextConfig = {
  async rewrites() {
    const api = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${api}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
