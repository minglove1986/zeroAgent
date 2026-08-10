/**
 * Prompt 模板占位页（菜单已挂，能力规划中）。
 *
 * @author 赵振明
 * @date 2026-08-10 13:52:30
 */
"use client";

import { useAdminPageTitle } from "@/components/AdminTitle";

export default function PromptsPage() {
  useAdminPageTitle("Prompt 模板");
  return (
    <div style={{ padding: 20 }}>
      <h1>Prompt 模板</h1>
      <p style={{ color: "var(--text-secondary)" }}>
        模板库、版本与绑定策略（规划中）
      </p>
    </div>
  );
}
