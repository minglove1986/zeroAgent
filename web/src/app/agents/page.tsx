/**
 * Agent / 技能管理（禁止 Agent 挂 tool_ids）。
 * @author 赵振明
 * @date 2026-07-21 16:58:11
 */
"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiJson } from "@/lib/api";

type SkillItem = {
  id: string;
  name: string;
  description: string | null;
  status: string;
  current_version: string | null;
};

type AgentItem = {
  id: string;
  name: string;
  description: string | null;
  main_model_id: string;
  status: string;
  memory_access?: string;
  can_modify_memory?: boolean;
};

export default function AgentsPage() {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [model, setModel] = useState("MiniMax-M3");
  const [skillName, setSkillName] = useState("请假助手技能");
  const [skillPrompt, setSkillPrompt] = useState("你是请假办理技能，可调用 ask_user。");
  const [agentName, setAgentName] = useState("HR助手");
  const [memoryAccess, setMemoryAccess] = useState("all");
  const [canModifyMemory, setCanModifyMemory] = useState(false);
  const [inheritSystemPersona, setInheritSystemPersona] = useState(true);
  const [fallbackModels, setFallbackModels] = useState("");
  const [templates, setTemplates] = useState<
    { id: string; name: string; status: string; variables_schema?: { name: string; required: boolean; label: string }[] }[]
  >([]);
  const [promptTemplateId, setPromptTemplateId] = useState("");
  const [agentVars, setAgentVars] = useState<Record<string, string>>({});
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    const [s, a, rt, t] = await Promise.all([
      apiJson<{ items: SkillItem[] }>("/api/v1/skills"),
      apiJson<{ items: AgentItem[] }>("/api/v1/agents"),
      apiJson<{ litellm_model: string }>("/api/v1/runtime"),
      apiJson<{
        items: {
          id: string;
          name: string;
          status: string;
          variables_schema?: { name: string; required: boolean; label: string }[];
        }[];
      }>("/api/v1/prompt-templates"),
    ]);
    if (s.code === 0) setSkills(s.data.items);
    if (a.code === 0) setAgents(a.data.items);
    if (rt.code === 0 && rt.data.litellm_model) setModel(rt.data.litellm_model);
    if (t.code === 0) setTemplates(t.data.items || []);
  }, []);

  const selectedTpl = templates.find((t) => t.id === promptTemplateId);
  const schemaFields = selectedTpl?.variables_schema || [];

  useEffect(() => {
    void refresh().catch((err) =>
      setError(err instanceof Error ? err.message : "加载失败"),
    );
  }, [refresh]);

  async function createSkill(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = await apiJson<{ skill_id: string }>("/api/v1/skills", {
        method: "POST",
        body: JSON.stringify({
          name: skillName,
          description: "演示技能",
          system_prompt: skillPrompt,
          tool_ids: ["ask_user"],
        }),
      });
      if (body.code !== 0) throw new Error(body.message);
      const pub = await apiJson(`/api/v1/skills/${body.data.skill_id}/publish`, {
        method: "POST",
      });
      if (pub.code !== 0) throw new Error(pub.message);
      setMsg(`技能已创建并发布：${body.data.skill_id}`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建技能失败");
    } finally {
      setBusy(false);
    }
  }

  async function createAgent(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = await apiJson<{ agent_id: string }>("/api/v1/agents", {
        method: "POST",
        body: JSON.stringify({
          name: agentName,
          description: "演示 Agent",
          main_model_id: model,
          skill_ids: selectedSkillIds,
          memory_access: memoryAccess,
          can_modify_memory: canModifyMemory,
          inherit_system_persona: inheritSystemPersona,
          fallback_model_ids: fallbackModels
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          prompt_template_id: promptTemplateId || null,
          variables: agentVars,
        }),
      });
      if (body.code !== 0) throw new Error(body.message);
      setMsg(`Agent 已创建：${body.data.agent_id}`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建 Agent 失败");
    } finally {
      setBusy(false);
    }
  }

  function toggleSkill(id: string) {
    setSelectedSkillIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  return (
    <div style={{ minHeight: "100vh" }}>
      <AppNav />
      <main style={{ maxWidth: 880, margin: "0 auto", padding: "2rem 1.5rem" }}>
        <h1 style={{ marginTop: 0 }}>Agent / 技能</h1>
        <p style={{ color: "var(--muted)", lineHeight: 1.55 }}>
          工具（含 ask_user）只能挂在技能上；Agent 只绑 skill_ids / callable_agent_ids。
          默认模型：{model}
        </p>

        <section
          style={{
            marginTop: "1.25rem",
            padding: "1.25rem",
            borderRadius: "var(--radius)",
            border: "1px solid var(--line)",
            background: "var(--card)",
          }}
        >
          <h2 style={{ fontSize: "1.05rem", marginTop: 0 }}>创建技能</h2>
          <form onSubmit={createSkill}>
            <div className="field">
              <label>名称</label>
              <input value={skillName} onChange={(e) => setSkillName(e.target.value)} required />
            </div>
            <div className="field">
              <label>system_prompt</label>
              <textarea
                rows={3}
                value={skillPrompt}
                onChange={(e) => setSkillPrompt(e.target.value)}
                required
              />
            </div>
            <button className="btn" type="submit" disabled={busy}>
              创建并发布（含 ask_user）
            </button>
          </form>
        </section>

        <section
          style={{
            marginTop: "1.25rem",
            padding: "1.25rem",
            borderRadius: "var(--radius)",
            border: "1px solid var(--line)",
            background: "var(--card)",
          }}
        >
          <h2 style={{ fontSize: "1.05rem", marginTop: 0 }}>创建 Agent</h2>
          <form onSubmit={createAgent}>
            <div className="field">
              <label>名称</label>
              <input value={agentName} onChange={(e) => setAgentName(e.target.value)} required />
            </div>
            <div className="field">
              <label>main_model_id</label>
              <input value={model} onChange={(e) => setModel(e.target.value)} required />
            </div>
            <div className="field">
              <label>fallback_model_ids（逗号分隔）</label>
              <input
                value={fallbackModels}
                onChange={(e) => setFallbackModels(e.target.value)}
                placeholder="例如 backup-model-a, backup-model-b"
              />
            </div>
            <div className="field">
              <label>prompt_template_id</label>
              <select
                value={promptTemplateId}
                onChange={(e) => {
                  setPromptTemplateId(e.target.value);
                  setAgentVars({});
                }}
                style={{
                  border: "1px solid var(--line)",
                  borderRadius: 8,
                  padding: "0.7rem",
                  background: "rgba(15,20,25,0.55)",
                  color: "var(--ink)",
                }}
              >
                <option value="">不引用模板</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} · {t.status} · {t.id}
                  </option>
                ))}
              </select>
            </div>
            {schemaFields.length > 0 ? (
              <div style={{ marginBottom: "1rem" }}>
                <div style={{ color: "var(--muted)", fontSize: "0.85rem", marginBottom: 8 }}>
                  模板变量
                </div>
                {schemaFields.map((f) => (
                  <div className="field" key={f.name}>
                    <label>
                      {f.label || f.name}
                      {f.required ? " *" : ""}
                    </label>
                    <input
                      value={agentVars[f.name] || ""}
                      onChange={(e) =>
                        setAgentVars((prev) => ({ ...prev, [f.name]: e.target.value }))
                      }
                      required={f.required}
                    />
                  </div>
                ))}
              </div>
            ) : null}
            <div className="field">
              <label>memory_access</label>
              <select
                value={memoryAccess}
                onChange={(e) => setMemoryAccess(e.target.value)}
                style={{
                  border: "1px solid var(--line)",
                  borderRadius: 8,
                  padding: "0.7rem",
                  background: "rgba(15,20,25,0.55)",
                  color: "var(--ink)",
                }}
              >
                <option value="all">all 全部</option>
                <option value="preference">preference 仅偏好</option>
                <option value="fact">fact 仅事实</option>
                <option value="none">none 不注入</option>
              </select>
            </div>
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: "1rem",
                color: "var(--muted)",
                fontSize: "0.9rem",
              }}
            >
              <input
                type="checkbox"
                checked={canModifyMemory}
                onChange={(e) => setCanModifyMemory(e.target.checked)}
              />
              can_modify_memory（允许对话后自动写入用户记忆，默认关）
            </label>
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: "1rem",
                color: "var(--muted)",
                fontSize: "0.9rem",
              }}
            >
              <input
                type="checkbox"
                checked={inheritSystemPersona}
                onChange={(e) => setInheritSystemPersona(e.target.checked)}
              />
              继承系统人格（管理后台「系统人格」提示词，默认开）
            </label>
            <div style={{ marginBottom: "1rem" }}>
              <div style={{ color: "var(--muted)", fontSize: "0.85rem", marginBottom: 8 }}>
                绑定技能
              </div>
              {skills.length === 0 ? (
                <p style={{ color: "var(--muted)", margin: 0 }}>暂无技能，请先创建</p>
              ) : (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {skills.map((s) => {
                    const on = selectedSkillIds.includes(s.id);
                    return (
                      <button
                        key={s.id}
                        type="button"
                        className={on ? "btn" : "btn btn-ghost"}
                        onClick={() => toggleSkill(s.id)}
                      >
                        {s.name}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <button className="btn" type="submit" disabled={busy}>
              创建 Agent
            </button>
          </form>
        </section>

        <section style={{ marginTop: "1.5rem" }}>
          <h2 style={{ fontSize: "1.05rem" }}>已有技能</h2>
          <ul style={{ color: "var(--muted)" }}>
            {skills.map((s) => (
              <li key={s.id}>
                {s.name} · {s.id} · {s.status}
                {s.current_version ? ` · ${s.current_version}` : ""}
              </li>
            ))}
          </ul>
          <h2 style={{ fontSize: "1.05rem" }}>已有 Agent</h2>
          <ul style={{ color: "var(--muted)" }}>
            {agents.map((a) => (
              <li key={a.id}>
                {a.name} · {a.id} · {a.main_model_id} · {a.status}
                {a.memory_access ? ` · mem=${a.memory_access}` : ""}
                {a.can_modify_memory ? " · writable" : ""}
              </li>
            ))}
          </ul>
        </section>

        {msg ? <p style={{ color: "var(--accent)" }}>{msg}</p> : null}
        {error ? <p className="err">{error}</p> : null}
      </main>
    </div>
  );
}
