/**
 * 无管理权限提示页。
 *
 * @author 赵振明
 * @date 2026-07-29 15:10:45
 */
"use client";

import { useRouter } from "next/navigation";

export default function FourZeroThreePage() {
  const router = useRouter();
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
    >
      <div style={{ textAlign: "center" }}>
        <h1 style={{ color: "var(--danger)" }}>403</h1>
        <p>您无权访问管理后台。请使用 platform_admin / super_admin 账号。</p>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => router.push("/login")}
        >
          返回登录
        </button>
      </div>
    </div>
  );
}
