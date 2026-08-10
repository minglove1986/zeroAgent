"use client";
import { useAdminPageTitle } from "@/components/AdminTitle";

export default function KGPage() {
  useAdminPageTitle("知识图谱");
  return (
    <>
      <div style={{ padding: 20 }}>
        <h1>知识图谱</h1>
        <p style={{ color: "var(--text-secondary)" }}>本体设计、实体与关系录入（规划中）</p>
      </div>
    </>
  );
}