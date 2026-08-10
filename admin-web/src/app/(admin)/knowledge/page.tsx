"use client";
import { useAdminPageTitle } from "@/components/AdminTitle";

export default function KnowledgePage() {
  useAdminPageTitle("知识库管理");
  return (
    <>
      <div style={{ padding: 20 }}>
        <h1>知识库管理</h1>
        <p style={{ color: "var(--text-secondary)" }}>文档上传、分类、权限与发布流程（规划中）</p>
      </div>
    </>
  );
}