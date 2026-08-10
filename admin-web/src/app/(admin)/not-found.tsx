/**
 * 管理端壳内 notFound()：仍走 (admin)/layout，避免整页丢失侧栏。
 *
 * @author 赵振明
 * @date 2026-08-10 13:52:30
 */
"use client";

import Link from "next/link";
import { useAdminPageTitle } from "@/components/AdminTitle";

export default function AdminNotFound() {
  useAdminPageTitle("页面未找到");
  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>页面不存在</h2>
      <p style={{ color: "var(--text-secondary)" }}>
        当前内容区无此页面，侧栏与顶栏仍可用。
      </p>
      <Link href="/overview" style={{ color: "var(--primary)" }}>
        返回概览
      </Link>
    </div>
  );
}
