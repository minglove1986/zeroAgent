/**
 * LLM 模型治理：同步 LiteLLM、启停、系统白名单、Agent 绑定。
 *
 * @author 赵振明
 * @date 2026-07-30 11:33:35
 */
"use client";

import { useEffect, useState } from "react";
import {
  Button,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { AdminLayout } from "@/components/AdminLayout";
import { apiJson } from "@/lib/api";

type LlmModelRow = {
  id: string;
  model_name: string;
  display_name: string;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  enabled: boolean;
  source_status: string;
  allow_system_chat: boolean;
  is_system_default: boolean;
  revision: number;
};

type AgentItem = { id: string; name: string };

export default function LlmModelsPage() {
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [rows, setRows] = useState<LlmModelRow[]>([]);
  const [cacheHint, setCacheHint] = useState("");
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [bindAgentId, setBindAgentId] = useState<string>("");
  const [bindModelIds, setBindModelIds] = useState<string[]>([]);
  const [bindDefaultId, setBindDefaultId] = useState<string>("");
  const [savingBind, setSavingBind] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const res = await apiJson<{
        items: LlmModelRow[];
        cache?: { redis_ok?: boolean; degraded?: boolean; catalog_version?: number };
      }>("/api/v1/admin/llm-models");
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "加载失败");
        return;
      }
      setRows(res.data.items || []);
      const c = res.data.cache;
      setCacheHint(
        c
          ? `缓存: ${c.redis_ok ? "正常" : "异常"} · 版本 ${c.catalog_version ?? "-"}`
          : "",
      );
    } catch {
      message.error("网络错误");
    } finally {
      setLoading(false);
    }
  }

  async function loadAgents() {
    try {
      const res = await apiJson<{ items: AgentItem[] }>("/api/v1/agents");
      if (res.code === 0 && res.data?.items) {
        setAgents(
          res.data.items.map((a) => ({
            id: a.id,
            name: a.name,
          })),
        );
      }
    } catch {
      /* Agent 列表可选 */
    }
  }

  useEffect(() => {
    void load();
    void loadAgents();
  }, []);

  async function onSync() {
    setSyncing(true);
    try {
      const res = await apiJson<{
        upserted: number;
        disabled: number;
        incomplete: number;
      }>("/api/v1/admin/llm-models/sync", { method: "POST" });
      if (res.code !== 0) {
        message.error(res.message || "同步失败");
        return;
      }
      message.success(
        `同步完成：更新 ${res.data?.upserted ?? 0} · 停用 ${res.data?.disabled ?? 0} · 不完整 ${res.data?.incomplete ?? 0}`,
      );
      await load();
    } catch {
      message.error("同步失败");
    } finally {
      setSyncing(false);
    }
  }

  async function patchRow(id: string, patch: Record<string, unknown>) {
    try {
      const res = await apiJson(`/api/v1/admin/llm-models/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      if (res.code !== 0) {
        message.error(res.message || "更新失败");
        await load();
        return;
      }
      message.success("已更新");
      await load();
    } catch {
      message.error("更新失败");
      await load();
    }
  }

  async function loadAgentBindings(agentId: string) {
    setBindAgentId(agentId);
    setBindModelIds([]);
    setBindDefaultId("");
    if (!agentId) return;
    try {
      const res = await apiJson<{
        items: { model_id: string; is_default: boolean }[];
      }>(`/api/v1/admin/agents/${agentId}/llm-models`);
      if (res.code === 0 && res.data?.items) {
        setBindModelIds(res.data.items.map((i) => i.model_id));
        const def = res.data.items.find((i) => i.is_default);
        setBindDefaultId(def?.model_id || "");
      }
    } catch {
      message.error("加载 Agent 绑定失败");
    }
  }

  async function saveBindings() {
    if (!bindAgentId) {
      message.warning("请先选择 Agent");
      return;
    }
    setSavingBind(true);
    try {
      const res = await apiJson(`/api/v1/admin/agents/${bindAgentId}/llm-models`, {
        method: "PUT",
        body: JSON.stringify({
          models: bindModelIds.map((model_id) => ({
            model_id,
            is_default: model_id === bindDefaultId,
          })),
        }),
      });
      if (res.code !== 0) {
        message.error(res.message || "保存绑定失败");
        return;
      }
      message.success("Agent 模型绑定已保存");
    } catch {
      message.error("保存绑定失败");
    } finally {
      setSavingBind(false);
    }
  }

  const statusTag = (s: string) => {
    if (s === "active") return <Tag color="green">active</Tag>;
    if (s === "incomplete") return <Tag color="orange">incomplete</Tag>;
    if (s === "missing_in_litellm") return <Tag color="red">missing</Tag>;
    return <Tag>{s}</Tag>;
  };

  const columns: ColumnsType<LlmModelRow> = [
    {
      title: "模型",
      dataIndex: "model_name",
      render: (_: unknown, r) => (
        <div>
          <div>{r.display_name}</div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {r.model_name}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "source_status",
      width: 120,
      render: (v: string) => statusTag(v),
    },
    {
      title: "启用",
      dataIndex: "enabled",
      width: 90,
      render: (v: boolean, r) => (
        <Switch
          checked={v}
          onChange={(checked) => void patchRow(r.id, { enabled: checked })}
        />
      ),
    },
    {
      title: "max_input",
      dataIndex: "max_input_tokens",
      width: 140,
      render: (v: number | null, r) => (
        <InputNumber
          min={1}
          value={v ?? undefined}
          style={{ width: 110 }}
          onBlur={(e) => {
            const n = Number(e.target.value);
            if (!Number.isFinite(n) || n <= 0) return;
            if (n === v) return;
            void patchRow(r.id, { max_input_tokens: n });
          }}
        />
      ),
    },
    {
      title: "系统对话",
      dataIndex: "allow_system_chat",
      width: 100,
      render: (v: boolean, r) => (
        <Switch
          checked={v}
          onChange={(checked) => void patchRow(r.id, { allow_system_chat: checked })}
        />
      ),
    },
    {
      title: "系统默认",
      dataIndex: "is_system_default",
      width: 100,
      render: (v: boolean, r) => (
        <Switch
          checked={v}
          onChange={(checked) => void patchRow(r.id, { is_system_default: checked })}
        />
      ),
    },
  ];

  return (
    <AdminLayout title="模型治理">
      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" loading={syncing} onClick={() => void onSync()}>
          从 LiteLLM 同步
        </Button>
        <Button onClick={() => void load()}>刷新</Button>
        <Typography.Text type="secondary">{cacheHint}</Typography.Text>
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        size="middle"
      />

      <Typography.Title level={5} style={{ marginTop: 28 }}>
        Agent 模型绑定
      </Typography.Title>
      <Space direction="vertical" style={{ width: "100%", maxWidth: 720 }} size="middle">
        <Select
          placeholder="选择 Agent"
          style={{ width: "100%" }}
          value={bindAgentId || undefined}
          onChange={(v) => void loadAgentBindings(v)}
          options={agents.map((a) => ({ value: a.id, label: `${a.name} (${a.id})` }))}
          allowClear
          showSearch
          optionFilterProp="label"
        />
        <Select
          mode="multiple"
          placeholder="可用模型"
          style={{ width: "100%" }}
          value={bindModelIds}
          onChange={(ids) => {
            setBindModelIds(ids);
            if (bindDefaultId && !ids.includes(bindDefaultId)) {
              setBindDefaultId("");
            }
          }}
          options={rows.map((r) => ({
            value: r.id,
            label: `${r.display_name} (${r.model_name})`,
            disabled: !r.enabled,
          }))}
        />
        <Select
          placeholder="默认模型（可选）"
          style={{ width: "100%" }}
          value={bindDefaultId || undefined}
          onChange={(v) => setBindDefaultId(v || "")}
          allowClear
          options={rows
            .filter((r) => bindModelIds.includes(r.id))
            .map((r) => ({
              value: r.id,
              label: r.display_name,
            }))}
        />
        <Button type="primary" loading={savingBind} onClick={() => void saveBindings()}>
          保存绑定
        </Button>
      </Space>
    </AdminLayout>
  );
}
