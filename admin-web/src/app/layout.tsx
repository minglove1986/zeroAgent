/**
 * 管理端根布局：注入全局样式与会话上下文（不含侧栏，登录页可独立渲染）。
 *
 * @author 赵振明
 * @date 2026-07-29 16:29:19
 */
import type { Metadata } from "next";
import { AuthProvider } from "@/lib/auth";
import "./globals.css";

export const metadata: Metadata = {
  title: "zeroAgent Admin",
  description: "zeroAgent 管理控制台",
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/zeroagent-icon-16.png", type: "image/png", sizes: "16x16" },
      { url: "/zeroagent-icon-32.png", type: "image/png", sizes: "32x32" },
      { url: "/zeroagent-icon-48.png", type: "image/png", sizes: "48x48" },
      { url: "/zeroagent-icon-192.png", type: "image/png", sizes: "192x192" },
      { url: "/zeroagent-icon-512.png", type: "image/png", sizes: "512x512" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  manifest: "/site.webmanifest",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
