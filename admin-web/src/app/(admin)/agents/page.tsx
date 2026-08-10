"use client";
import { useAdminPageTitle } from "@/components/AdminTitle";

export default function AgentsPage() {
  useAdminPageTitle("Agent 管理");
  return (
    <>
      <div style={{ padding: 20 }}>
        <h1>Agent 管理</h1>
        <p style={{ color: "var(--text-secondary)" }}>Agent 创建、配置、状态机与版本控制（规划中）</p>
      </div>
    </>
  );
}