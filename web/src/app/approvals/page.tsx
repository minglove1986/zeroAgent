/**
 * 高风险审批待办。
 * @author 赵振明
 * @date 2026-07-22 10:28:20
 */
"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiJson } from "@/lib/api";

type Approval = {
  id: string;
  type: string;
  title: string;
  risk_level: string;
  status: string;
  requester_id: string;
  assignee_id: string;
  comment: string | null;
  ref_type: string | null;
  ref_id: string | null;
  expires_at: string | null;
  created_at: string | null;
};

export default function ApprovalsPage() {
  const [items, setItems] = useState<Approval[]>([]);
  const [status, setStatus] = useState("pending");
  const [title, setTitle] = useState("演示高风险审批");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    const res = await apiJson<{ items: Approval[] }>(`/api/v1/approvals${q}`);
    if (res.code !== 0) throw new Error(res.message);
    setItems(res.data.items || []);
  }, [status]);

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
      const res = await apiJson("/api/v1/approvals", {
        method: "POST",
        body: JSON.stringify({
          title,
          type: "tool_high_risk",
          risk_level: "high",
        }),
      });
      if (res.code !== 0) throw new Error(res.message);
      setMsg("已创建待办");
      setStatus("pending");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function onDecide(id: string, action: "approve" | "reject") {
    setBusy(true);
    setError("");
    try {
      const res = await apiJson(`/api/v1/approvals/${id}/${action}`, {
        method: "POST",
        body: JSON.stringify({
          comment: action === "approve" ? "通过" : "驳回",
        }),
      });
      if (res.code !== 0) throw new Error(res.message);
      setMsg(action === "approve" ? "已通过" : "已驳回");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh" }}>
      <AppNav />
      <main style={{ maxWidth: 780, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{ marginTop: 0 }}>审批待办</h1>
        <p style={{ color: "var(--muted)" }}>
          高风险操作与工作流人工节点。通过后可自动 resume 关联实例。
        </p>

        <div style={{ display: "flex", gap: 12, marginBottom: "1rem" }}>
          {(["pending", "approved", "rejected", "cancelled", ""] as const).map((s) => (
            <button
              key={s || "all"}
              type="button"
              className={status === s ? "btn" : "btn btn-ghost"}
              onClick={() => setStatus(s)}
            >
              {s === "" ? "全部" : s}
            </button>
          ))}
        </div>

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
          <button className="btn" type="submit" disabled={busy}>
            创建演示待办
          </button>
        </form>

        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {items.map((a) => (
            <li
              key={a.id}
              style={{
                marginBottom: 10,
                padding: "0.85rem 1rem",
                borderRadius: 10,
                border: "1px solid var(--line)",
                background: "var(--card)",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <div>
                  <strong>
                    [{a.risk_level}] {a.title}
                  </strong>
                  <div style={{ color: "var(--muted)", marginTop: 4, fontSize: "0.85rem" }}>
                    {a.type} · {a.status}
                    {a.ref_id ? ` · ${a.ref_type}:${a.ref_id}` : ""}
                    {a.expires_at ? ` · 截止 ${a.expires_at}` : ""}
                  </div>
                  {a.comment ? (
                    <div style={{ color: "var(--muted)", marginTop: 4 }}>{a.comment}</div>
                  ) : null}
                </div>
                {a.status === "pending" ? (
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      className="btn"
                      type="button"
                      disabled={busy}
                      onClick={() => onDecide(a.id, "approve")}
                    >
                      通过
                    </button>
                    <button
                      className="btn btn-ghost"
                      type="button"
                      disabled={busy}
                      onClick={() => onDecide(a.id, "reject")}
                    >
                      驳回
                    </button>
                  </div>
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
