/**
 * 员工端知识库已下线：维护请到管理端。
 * @author 赵振明
 * @date 2026-11-20 14:22:56
 */
"use client";

import Link from "next/link";

const ADMIN_KB =
  process.env.NEXT_PUBLIC_ADMIN_ORIGIN?.replace(/\/$/, "") ||
  "http://127.0.0.1:3001";

export default function KnowledgeOfflinePage() {
  return (
    <main style={{ padding: "2.5rem 1.5rem", maxWidth: 640, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "0.75rem" }}>知识库已迁至管理端</h1>
      <p style={{ color: "var(--text-secondary, #8b949e)", lineHeight: 1.6 }}>
        员工端不再提供知识库上传与维护。请使用管理端完成建库、文档、切块、权限与分类等操作。
      </p>
      <p style={{ marginTop: "1.25rem" }}>
        <a
          href={`${ADMIN_KB}/knowledge`}
          style={{ color: "var(--accent, #58a6ff)" }}
          rel="noopener noreferrer"
        >
          打开管理端 · 知识库
        </a>
        {" · "}
        <Link href="/chat" style={{ color: "var(--accent, #58a6ff)" }}>
          返回对话
        </Link>
      </p>
    </main>
  );
}
