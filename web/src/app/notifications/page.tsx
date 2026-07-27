/**
 * 站内通知列表。
 * @author 赵振明
 * @date 2026-07-22 10:10:11
 */
"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiJson } from "@/lib/api";

type Ntf = {
  id: string;
  title: string;
  body: string | null;
  category: string;
  is_read: boolean;
  created_at: string | null;
};

export default function NotificationsPage() {
  const [items, setItems] = useState<Ntf[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [title, setTitle] = useState("系统提醒");
  const [body, setBody] = useState("这是一条演示通知");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const q = unreadOnly ? "?unread_only=true" : "";
    const res = await apiJson<{ items: Ntf[] }>(`/api/v1/notifications${q}`);
    if (res.code !== 0) throw new Error(res.message);
    setItems(res.data.items || []);
  }, [unreadOnly]);

  useEffect(() => {
    void refresh().catch((err) =>
      setError(err instanceof Error ? err.message : "加载失败"),
    );
  }, [refresh]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await apiJson("/api/v1/notifications", {
        method: "POST",
        body: JSON.stringify({ title, body, category: "system" }),
      });
      if (res.code !== 0) throw new Error(res.message);
      setMsg("已创建通知");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function onRead(id: string) {
    setBusy(true);
    try {
      const res = await apiJson(`/api/v1/notifications/${id}/read`, { method: "POST" });
      if (res.code !== 0) throw new Error(res.message);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "标记失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh" }}>
      <AppNav />
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{ marginTop: 0 }}>站内通知</h1>
        <p style={{ color: "var(--muted)" }}>替代 IM 通道的 Web 通知（告警 / 工作流 / 系统）。</p>

        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            color: "var(--muted)",
            marginBottom: "1rem",
          }}
        >
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => setUnreadOnly(e.target.checked)}
          />
          仅未读
        </label>

        <form
          onSubmit={onCreate}
          style={{
            padding: "1.25rem",
            borderRadius: "var(--radius)",
            border: "1px solid var(--line)",
            background: "var(--card)",
            marginBottom: "1.5rem",
          }}
        >
          <div className="field">
            <label>标题</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>
          <div className="field">
            <label>内容</label>
            <input value={body} onChange={(e) => setBody(e.target.value)} />
          </div>
          <button className="btn" type="submit" disabled={busy}>
            发送演示通知
          </button>
        </form>

        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {items.map((n) => (
            <li
              key={n.id}
              style={{
                marginBottom: 10,
                padding: "0.85rem 1rem",
                borderRadius: 10,
                border: "1px solid var(--line)",
                background: n.is_read ? "var(--card)" : "rgba(45,212,191,0.1)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <div>
                  <strong>
                    [{n.category}] {n.title}
                  </strong>
                  {n.body ? (
                    <div style={{ color: "var(--muted)", marginTop: 4 }}>{n.body}</div>
                  ) : null}
                  <div style={{ color: "var(--muted)", fontSize: "0.8rem", marginTop: 4 }}>
                    {n.created_at || ""} {n.is_read ? "· 已读" : "· 未读"}
                  </div>
                </div>
                {!n.is_read ? (
                  <button
                    className="btn btn-ghost"
                    type="button"
                    disabled={busy}
                    onClick={() => onRead(n.id)}
                  >
                    标为已读
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
        {msg ? <p style={{ color: "var(--accent)" }}>{msg}</p> : null}
        {error ? <p className="err">{error}</p> : null}
      </main>
    </div>
  );
}
