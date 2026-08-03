import type { NextConfig } from "next";

/**
 * 管理端 /api 同源代理到 FastAPI（固定 :8000）。
 *
 * @author 赵振明
 * @date 2026-07-29 15:10:45
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
