/**
 * 控制台顶栏导航。
 * @author 赵振明
 * @date 2026-07-29 16:29:19
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BrandMark } from "@/components/BrandMark";

const LINKS = [
  { href: "/chat", label: "系统对话" },
  { href: "/knowledge", label: "知识库上传" },
  { href: "/agents", label: "Agent/技能" },
  { href: "/prompts", label: "Prompt模板" },
  { href: "/memories", label: "我的记忆" },
  { href: "/notifications", label: "通知" },
  { href: "/approvals", label: "审批" },
];

export function AppNav() {
  const pathname = usePathname();
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "1rem 1.5rem",
        borderBottom: "1px solid var(--line)",
        background: "rgba(15,20,25,0.55)",
        backdropFilter: "blur(10px)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "1.25rem" }}>
        <Link
          href="/chat"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.55rem",
            color: "inherit",
            textDecoration: "none",
          }}
        >
          <BrandMark size={28} priority />
          <strong style={{ fontSize: "1.15rem" }}>zeroAgent</strong>
        </Link>
        <nav style={{ display: "flex", gap: "0.85rem" }}>
          {LINKS.map((l) => {
            const active = pathname === l.href || pathname.startsWith(l.href + "/");
            return (
              <Link
                key={l.href}
                href={l.href}
                style={{
                  color: active ? "var(--accent)" : "var(--muted)",
                  textDecoration: "none",
                  fontWeight: active ? 600 : 400,
                }}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <Link href="/login" style={{ color: "var(--muted)", textDecoration: "none" }}>
        退出 / 换账号
      </Link>
    </header>
  );
}
