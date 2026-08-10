"use client";
import { useAdminPageTitle } from "@/components/AdminTitle";

export default function WorkflowsPage() {
  useAdminPageTitle("工作流编排");
  return (
    <>
      <div style={{ padding: 20 }}>
        <h1>工作流编排</h1>
        <p style={{ color: "var(--text-secondary)" }}>可视化 DAG 编辑器与节点库（规划中）</p>
      </div>
    </>
  );
}