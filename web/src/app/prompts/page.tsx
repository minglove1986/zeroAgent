/**
 * Prompt 模板管理（变量 schema + 版本回滚）。
 * @author 赵振明
 * @date 2026-07-22 10:42:58
 */
"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiJson } from "@/lib/api";

type VarSchema = { name: string; required: boolean; label: string };

type Tpl = {
  id: string;
  name: string;
  description: string | null;
  content: string;
  status: string;
  version: string;
  variables_schema?: VarSchema[];
};

export default function PromptsPage() {
  const [items, setItems] = useState<Tpl[]>([]);
  const [name, setName] = useState("通用助手模板");
  const [content, setContent] = useState("你是企业助手，服务部门={{dept}}。");
  const [schemaText, setSchemaText] = useState(
    '[{"name":"dept","required":true,"label":"部门"}]',
  );
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const body = await apiJson<{ items: Tpl[] }>("/api/v1/prompt-templates");
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
      let variables_schema: VarSchema[] | undefined;
      if (schemaText.trim()) {
        variables_schema = JSON.parse(schemaText) as VarSchema[];
      }
      const body = await apiJson<{ id: string }>("/api/v1/prompt-templates", {
        method: "POST",
        body: JSON.stringify({
          name,
          content,
          description: "演示模板",
          variables_schema,
        }),
      });
      if (body.code !== 0) throw new Error(body.message);
      setMsg(`已创建：${body.data.id}`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function onPublish(id: string) {
    setBusy(true);
    try {
      const body = await apiJson(`/api/v1/prompt-templates/${id}/publish`, {
        method: "POST",
      });
      if (body.code !== 0) throw new Error(body.message);
      setMsg("已发布（已写入版本快照）");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "发布失败");
    } finally {
      setBusy(false);
    }
  }

  async function onRollback(id: string, version: string) {
    setBusy(true);
    try {
      const body = await apiJson(`/api/v1/prompt-templates/${id}/rollback`, {
        method: "POST",
        body: JSON.stringify({ version }),
      });
      if (body.code !== 0) throw new Error(body.message);
      setMsg(`已回滚到 ${version}（draft，需再发布）`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "回滚失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ minHeight: "100vh" }}>
      <AppNav />
      <main style={{ maxWidth: 720, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{ marginTop: 0 }}>Prompt 模板</h1>
        <p style={{ color: "var(--muted)" }}>
          支持 {"{{var}}"} 插值；发布写入版本快照，可回滚为草稿。
        </p>

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
            <label>名称</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label>content</label>
            <textarea
              rows={4}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label>variables_schema（JSON）</label>
            <textarea
              rows={3}
              value={schemaText}
              onChange={(e) => setSchemaText(e.target.value)}
              placeholder='[{"name":"dept","required":true,"label":"部门"}]'
            />
          </div>
          <button className="btn" type="submit" disabled={busy}>
            创建草稿
          </button>
        </form>

        <ul style={{ listStyle: "none", padding: 0 }}>
          {items.map((t) => (
            <li
              key={t.id}
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
                    {t.name} · {t.status} · {t.version}
                  </strong>
                  <div style={{ color: "var(--muted)", fontSize: "0.85rem", marginTop: 4 }}>
                    {t.id}
                    {t.variables_schema?.length
                      ? ` · vars=${t.variables_schema.map((v) => v.name).join(",")}`
                      : ""}
                  </div>
                  <div style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>{t.content}</div>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <button
                    className="btn btn-ghost"
                    type="button"
                    disabled={busy}
                    onClick={() => onPublish(t.id)}
                  >
                    发布
                  </button>
                  <button
                    className="btn btn-ghost"
                    type="button"
                    disabled={busy}
                    onClick={() => onRollback(t.id, t.version)}
                  >
                    回滚当前 version
                  </button>
                </div>
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
