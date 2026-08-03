/**
 * 管理端三段式导航：侧栏菜单 + 顶栏标题/主题/退出。
 *
 * @author 赵振明
 * @date 2026-07-30 11:33:35
 */
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { BrandMark } from "./BrandMark";
import { ThemeSwitcher } from "./ThemeSwitcher";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/overview", label: "概览" },
  { href: "/system/persona", label: "系统人格" },
  { href: "/system/llm-models", label: "模型治理" },
  { href: "/system/memory-fields", label: "记忆白名单" },
  { href: "/system/l2-keywords", label: "L2关键词" },
  { href: "/operations/audit", label: "审计日志" },
  { href: "/operations/feedbacks", label: "消息反馈" },
];

export default function AppNav({
  children,
  title,
}: {
  children: ReactNode;
  title?: string;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();

  async function onLogout() {
    await logout();
    router.replace("/login");
  }

  const displayName = user?.name || user?.username || "管理员";

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <aside
        style={{
          width: 250,
          background: "var(--sidebar-bg)",
          borderRight: "1px solid var(--border-color)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--border-color)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <BrandMark size={32} priority />
          <div style={{ lineHeight: 1.25 }}>
            <strong style={{ display: "block" }}>zeroAgent</strong>
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>Admin</span>
          </div>
        </div>
        <nav style={{ flex: 1, overflowY: "auto" }}>
          {LINKS.map((l) => {
            const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <Link
                key={l.href}
                href={l.href}
                style={{
                  display: "block",
                  padding: "12px 20px",
                  color: active ? "var(--primary)" : "var(--text-primary)",
                  textDecoration: "none",
                  borderBottom: `1px solid ${active ? "var(--border-color)" : "transparent"}`,
                }}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <header
          style={{
            height: 60,
            background: "var(--header-bg)",
            borderBottom: "1px solid var(--border-color)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 20px",
          }}
        >
          <h1 style={{ margin: 0, fontSize: 18 }}>{title || "控制台"}</h1>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <ThemeSwitcher />
            <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>
              {displayName}
              {user?.role ? ` · ${user.role}` : ""}
            </span>
            <button type="button" className="btn btn-danger" onClick={() => void onLogout()}>
              退出
            </button>
          </div>
        </header>
        <main
          style={{
            flex: 1,
            overflowY: "auto",
            padding: 20,
            background: "var(--bg-surface)",
          }}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
