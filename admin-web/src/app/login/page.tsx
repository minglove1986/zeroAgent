/**
 * 管理端登录页（Suspense 包裹以支持 useSearchParams）。
 *
 * @author 赵振明
 * @date 2026-07-29 16:29:19
 */
"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiJson } from "@/lib/api";
import { isAdminRole, useAuth, type AdminUser } from "@/lib/auth";
import { BrandMark } from "@/components/BrandMark";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading: authLoading, refresh } = useAuth();
  const [username, setUsername] = useState("demo");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const nextPath = searchParams.get("next") || "/overview";

  useEffect(() => {
    if (authLoading) return;
    if (user && isAdminRole(user.role)) {
      router.replace(nextPath.startsWith("/") ? nextPath : "/overview");
    }
  }, [authLoading, user, router, nextPath]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await apiJson<AdminUser>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      if (res.code !== 0 || !res.data) {
        throw new Error(res.message || "登录失败");
      }
      if (!isAdminRole(res.data.role)) {
        await apiJson("/api/v1/auth/logout", { method: "POST" });
        throw new Error("当前账号无管理后台权限");
      }
      await refresh();
      router.push(nextPath.startsWith("/") ? nextPath : "/overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  if (authLoading) {
    return <div style={{ padding: 24 }}>检测会话状态...</div>;
  }

  return (
    <div
      style={{
        display: "flex",
        minHeight: "100vh",
        alignItems: "center",
        justifyContent: "center",
        padding: 40,
        background: "var(--bg-surface)",
      }}
    >
      <form
        onSubmit={onSubmit}
        style={{
          width: 400,
          padding: 30,
          borderRadius: 8,
          border: "1px solid var(--border-color)",
          background: "var(--bg-surface)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            marginBottom: 20,
          }}
        >
          <BrandMark size={40} priority />
          <div>
            <h2 style={{ margin: 0, textAlign: "left" }}>zeroAgent</h2>
            <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>管理员控制台</div>
          </div>
        </div>
        <div className="field">
          <label htmlFor="admin-username">用户名</label>
          <input
            id="admin-username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoComplete="username"
          />
        </div>
        <div className="field">
          <label htmlFor="admin-password">密码</label>
          <input
            id="admin-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
          />
        </div>
        {error ? <div className="err">{error}</div> : null}
        <button
          type="submit"
          className="btn btn-primary"
          style={{ width: "100%", marginTop: 15 }}
          disabled={busy}
        >
          {busy ? "登录中..." : "登录"}
        </button>
        <p style={{ marginTop: 12, fontSize: 12, color: "var(--text-secondary)" }}>
          需 platform_admin / super_admin；默认可试用员工端演示管理员账号。
        </p>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div style={{ padding: 24 }}>加载登录页...</div>}>
      <LoginForm />
    </Suspense>
  );
}
