/**
 * 用量成本占位页。
 *
 * @author 赵振明
 * @date 2026-08-10 13:52:30
 */
"use client";

import { useAdminPageTitle } from "@/components/AdminTitle";

export default function UsagePage() {
  useAdminPageTitle("用量成本");
  return (
    <div style={{ padding: 20 }}>
      <h1>用量成本</h1>
      <p style={{ color: "var(--text-secondary)" }}>Token / 调用量与成本看板（规划中）</p>
    </div>
  );
}
