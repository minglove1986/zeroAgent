/**
 * 根布局。
 * suppressHydrationWarning：忽略扩展注入的 body 属性（如 cursor），避免误报。
 * @author 赵振明
 * @date 2026-07-29 16:29:19
 */
import type { Metadata } from "next";
import { IBM_Plex_Sans, Noto_Sans_SC } from "next/font/google";
import "./globals.css";

const plex = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-plex",
});

const noto = Noto_Sans_SC({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-noto",
});

export const metadata: Metadata = {
  title: "zeroAgent",
  description: "企业级智能体平台 · 系统对话",
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
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className={`${plex.variable} ${noto.variable}`}
      suppressHydrationWarning
    >
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
