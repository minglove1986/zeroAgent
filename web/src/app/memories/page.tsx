/**
 * 我的记忆（PRD 第十五章：查看/编辑/删除/清空）。
 * @author 赵振明
 * @date 2026-07-22 09:09:54
 */
"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiJson } from "@/lib/api";

type MemoryItem = {
  id: string;
  memory_type: string;
  memory_key: string;
  memory_value: string;
  source: string;
  confidence: number;
};

export default function MemoriesPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [memoryType, setMemoryType] = useState("fact");
  const [memoryKey, setMemoryKey] = useState("name");
  const [memoryValue, setMemoryValue] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const body = await apiJson<{ items: MemoryItem[] }>("/api/v1/users/me/memories");
    if (body.code !== 0) throw new Error(body.message);
    setItems(body.data.items || []);
  }, []);

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
      const body = await apiJson("/api/v1/users/me/memories", {
        method: "POST",
        body: JSON.stringify({
          memory_type: memoryType,
          memory_key: memoryKey,
          memory_value: memoryValue,
          source: "manual",
        }),
      });
      if (body.code !== 0) throw new Error(body.message);
      setMemoryValue("");
      setMsg("已保存记忆");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(id: string) {
    setBusy(true);
    try {
      const body = await apiJson(`/api/v1/users/me/memories/${id}`, { method: "DELETE" });
      if (body.code !== 0) throw new Error(body.message);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function onClear() {
    if (!window.confirm("确认清空全部记忆？此操作不可恢复。")) return;
    setBusy(true);
    try {
      const body = await apiJson("/api/v1/users/me/memories/clear", { method: "POST" });
      if (body.code !== 0) throw new Error(body.message);
      setMsg("已清空");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "清空失败");
    } finally {
      setBusy(false);
    }
  }

  async function onExport() {
    setBusy(true);
    setError("");
    try {
      const body = await apiJson<{ count: number }>("/api/v1/users/me/memories/export");
      if (body.code !== 0) throw new Error(body.message);
      const blob = new Blob([JSON.stringify(body.data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `zeroagent-memories-${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setMsg(`已导出 ${body.data.count} 条`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh" }}>
      <AppNav />
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{ marginTop: 0 }}>我的记忆</h1>
        <p style={{ color: "var(--muted)", lineHeight: 1.55 }}>
          跨会话偏好 / 事实 / 摘要。对话时自动注入 System Prompt；也可手动维护。
          试在对话中说「我叫张三」触发自动抽取。
        </p>

        <form
          onSubmit={onCreate}
          style={{
            marginTop: "1.25rem",
            padding: "1.25rem",
            borderRadius: "var(--radius)",
            border: "1px solid var(--line)",
            background: "var(--card)",
          }}
        >
          <div className="field">
            <label>类型</label>
            <select
              value={memoryType}
              onChange={(e) => setMemoryType(e.target.value)}
              style={{
                border: "1px solid var(--line)",
                borderRadius: 8,
                padding: "0.7rem",
                background: "rgba(15,20,25,0.55)",
                color: "var(--ink)",
              }}
            >
              <option value="fact">事实 fact</option>
              <option value="preference">偏好 preference</option>
              <option value="summary">摘要 summary</option>
            </select>
          </div>
          <div className="field">
            <label>键</label>
            <input value={memoryKey} onChange={(e) => setMemoryKey(e.target.value)} required />
          </div>
          <div className="field">
            <label>值</label>
            <input
              value={memoryValue}
              onChange={(e) => setMemoryValue(e.target.value)}
              required
            />
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="btn" type="submit" disabled={busy}>
              保存
            </button>
            <button className="btn btn-ghost" type="button" disabled={busy} onClick={onExport}>
              导出 JSON
            </button>
            <button className="btn btn-ghost" type="button" disabled={busy} onClick={onClear}>
              一键清空
            </button>
          </div>
        </form>

        <ul style={{ marginTop: "1.5rem", padding: 0, listStyle: "none" }}>
          {items.map((m) => (
            <li
              key={m.id}
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
                    [{m.memory_type}] {m.memory_key}
                  </strong>
                  <div style={{ color: "var(--muted)", marginTop: 4 }}>{m.memory_value}</div>
                  <div style={{ color: "var(--muted)", fontSize: "0.8rem", marginTop: 4 }}>
                    source={m.source}
                  </div>
                </div>
                <button
                  className="btn btn-ghost"
                  type="button"
                  disabled={busy}
                  onClick={() => onDelete(m.id)}
                >
                  删除
                </button>
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
