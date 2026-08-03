"use client";
import { AdminLayout } from "@/components/AdminLayout";

export default function AgentsPage() {
  return (
    <AdminLayout title="Agent 管理">
      <div style={{ padding: 20 }}>
        <h1>Agent 管理</h1>
        <p style={{ color: "var(--text-secondary)" }}>Agent 创建、配置、状态机与版本控制（规划中）</p>
      </div>
    </AdminLayout>
  );
}