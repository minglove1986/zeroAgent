/**
 * 登录页（品牌主视觉 + 自建账号）。
 * @author 赵振明
 * @date 2026-07-23 15:30:58
 */
"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiJson } from "@/lib/api";

const DEMO_USER = {
  username: "demo",
  password: "demo1234",
  name: "演示用户",
  employee_no: "E-DEMO",
  email: "demo@zeroagent.local",
  phone: "13900000000",
  position: "平台管理员",
  hire_date: "2026-01-01",
  main_department_id: "dept_it",
  department_ids: ["dept_it", "dept_root"],
  role: "platform_admin",
};

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("demo");
  const [password, setPassword] = useState("demo1234");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function doLogin(u: string, p: string) {
    const body = await apiJson<{ username: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: u, password: p }),
    });
    if (body.code !== 0) {
      throw new Error(body.message || `登录失败 ${body.code}`);
    }
    router.push("/chat");
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await doLogin(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  async function onBootstrap() {
    setError("");
    setBusy(true);
    try {
      await apiJson("/api/v1/users", {
        method: "POST",
        body: JSON.stringify(DEMO_USER),
      });
      await doLogin(DEMO_USER.username, DEMO_USER.password);
    } catch (err) {
      try {
        await doLogin(DEMO_USER.username, DEMO_USER.password);
      } catch {
        setError(err instanceof Error ? err.message : "创建演示账号失败");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "2rem",
      }}
    >
      <section
        style={{
          width: "min(420px, 100%)",
          padding: "2.5rem 2rem",
          borderRadius: "var(--radius)",
          background: "var(--card)",
          border: "1px solid var(--line)",
          backdropFilter: "blur(12px)",
        }}
      >
        <p style={{ margin: 0, color: "var(--accent)", letterSpacing: "0.08em", fontSize: "0.8rem" }}>
          ENTERPRISE AGENT
        </p>
        <h1 style={{ margin: "0.4rem 0 0.6rem", fontSize: "2.4rem", fontWeight: 700 }}>
          zeroAgent
        </h1>
        <p style={{ margin: "0 0 1.75rem", color: "var(--muted)", lineHeight: 1.5 }}>
          企业内网智能体控制台。登录后进入系统对话（SSE + 交互卡片）。
        </p>

        <form onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">密码</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error ? <p className="err">{error}</p> : null}
          <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            <button className="btn" type="submit" disabled={busy}>
              {busy ? "登录中…" : "登录"}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              disabled={busy}
              onClick={onBootstrap}
            >
              创建演示账号并登录
            </button>
          </div>
        </form>
      </section>
    </main>
  );
}
