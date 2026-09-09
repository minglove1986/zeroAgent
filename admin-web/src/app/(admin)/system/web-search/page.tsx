/**
 * 联网搜索配置：总开关、Provider、引擎目录同步与启停。
 *
 * @author 赵振明
 * @date 2026-09-08 10:58:43
 */
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Table,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

const BAIDU_DEFAULT_BASE_URL = "https://qianfan.baidubce.com";

type ProviderItem = {
  id: string;
  label: string;
  implemented: boolean;
};

type SettingsData = {
  enabled: boolean;
  provider: string;
  base_url: string;
  api_key_set: boolean;
  api_key_masked: string | null;
  timeout_seconds: number;
  result_count: number;
  providers: ProviderItem[];
};

type EngineRow = {
  id: string;
  provider: string;
  engine_key: string;
  display_name: string;
  enabled: boolean;
  source_status: string;
  categories: string[];
  revision: number;
};

export default function WebSearchSettingsPage() {
  useAdminPageTitle("联网搜索");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [enginesLoading, setEnginesLoading] = useState(false);
  const [form] = Form.useForm();
  const watchedProvider = Form.useWatch("provider", form) as string | undefined;
  const isBaidu = (watchedProvider || "").toLowerCase() === "baidu";
  const showEngineCatalog = !isBaidu && (watchedProvider || "searxng") === "searxng";
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [apiKeySet, setApiKeySet] = useState(false);
  const [apiKeyMasked, setApiKeyMasked] = useState<string | null>(null);
  const [testHint, setTestHint] = useState("");
  const [engines, setEngines] = useState<EngineRow[]>([]);
  const [engineProvider, setEngineProvider] = useState("searxng");
  const [keyword, setKeyword] = useState("");
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);
  const [bulking, setBulking] = useState(false);

  const loadEngines = useCallback(async (provider?: string) => {
    setEnginesLoading(true);
    try {
      const q = provider ? `?provider=${encodeURIComponent(provider)}` : "";
      const res = await apiJson<{ provider: string; items: EngineRow[] }>(
        `/api/v1/admin/web-search-engines${q}`,
      );
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "加载引擎失败");
        return;
      }
      setEngineProvider(res.data.provider || provider || "searxng");
      setEngines(res.data.items || []);
    } catch {
      message.error("加载引擎失败");
    } finally {
      setEnginesLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiJson<SettingsData>("/api/v1/admin/web-search-settings");
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "加载失败");
        return;
      }
      const d = res.data;
      setProviders(d.providers || []);
      setApiKeySet(Boolean(d.api_key_set));
      setApiKeyMasked(d.api_key_masked || null);
      const provider = d.provider || "searxng";
      form.setFieldsValue({
        enabled: d.enabled,
        provider,
        base_url: provider === "baidu" ? BAIDU_DEFAULT_BASE_URL : d.base_url || "",
        api_key: "",
        timeout_seconds: d.timeout_seconds ?? 10,
        result_count: d.result_count ?? 5,
        clear_api_key: false,
      });
      if (provider === "searxng") {
        await loadEngines(provider);
      }
    } catch {
      message.error("网络错误");
    } finally {
      setLoading(false);
    }
  }, [form, loadEngines]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!watchedProvider) return;
    if (watchedProvider === "baidu") {
      form.setFieldsValue({ base_url: BAIDU_DEFAULT_BASE_URL });
    }
  }, [watchedProvider, form]);

  async function onSave(values: {
    enabled: boolean;
    provider: string;
    base_url: string;
    api_key?: string;
    timeout_seconds: number;
    result_count: number;
    clear_api_key?: boolean;
  }) {
    setSaving(true);
    try {
      const provider = values.provider;
      const body: Record<string, unknown> = {
        enabled: values.enabled,
        provider,
        base_url: provider === "baidu" ? BAIDU_DEFAULT_BASE_URL : values.base_url || "",
        timeout_seconds: values.timeout_seconds,
        result_count: values.result_count,
        clear_api_key: Boolean(values.clear_api_key),
      };
      if (values.api_key && values.api_key.trim()) {
        body.api_key = values.api_key.trim();
      }
      const res = await apiJson<SettingsData>("/api/v1/admin/web-search-settings", {
        method: "PUT",
        body: JSON.stringify(body),
      });
      if (res.code !== 0) {
        message.error(res.message || "保存失败");
        return;
      }
      message.success("已保存");
      await load();
    } catch {
      message.error("保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function onTest() {
    setTesting(true);
    setTestHint("");
    try {
      const values = form.getFieldsValue();
      const provider = values.provider;
      const body: Record<string, unknown> = {
        query: "zeroAgent",
        provider,
        base_url: provider === "baidu" ? BAIDU_DEFAULT_BASE_URL : values.base_url || "",
        timeout_seconds: values.timeout_seconds,
        result_count: Math.min(Number(values.result_count) || 3, 3),
      };
      if (values.api_key && String(values.api_key).trim()) {
        body.api_key = String(values.api_key).trim();
      }
      const res = await apiJson<{
        ok?: boolean;
        error?: string;
        hint?: string;
        items?: { title: string; url: string }[];
      }>("/api/v1/admin/web-search-settings/test", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "测试失败");
        return;
      }
      if (res.data.ok) {
        const titles = (res.data.items || [])
          .slice(0, 2)
          .map((i) => i.title)
          .join("；");
        message.success("连接成功");
        setTestHint(titles ? `样例：${titles}` : "连接成功（无结果条目）");
      } else {
        message.error(res.data.error || "测试失败");
        setTestHint(res.data.hint || res.data.error || "");
      }
    } catch {
      message.error("测试失败");
    } finally {
      setTesting(false);
    }
  }

  async function onSyncEngines() {
    setSyncing(true);
    try {
      const res = await apiJson<{
        provider: string;
        supports_engine_catalog: boolean;
        upserted: number;
        disabled_missing: number;
        message?: string;
      }>("/api/v1/admin/web-search-engines/sync", { method: "POST", body: "{}" });
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "同步失败");
        return;
      }
      if (!res.data.supports_engine_catalog) {
        message.info(res.data.message || "本实现方式无需引擎目录");
      } else {
        message.success(
          `已同步：更新 ${res.data.upserted}，标记缺失 ${res.data.disabled_missing}`,
        );
      }
      await loadEngines(res.data.provider);
    } catch {
      message.error("同步失败");
    } finally {
      setSyncing(false);
    }
  }

  async function onToggleEngine(row: EngineRow, enabled: boolean) {
    try {
      const res = await apiJson<EngineRow>(`/api/v1/admin/web-search-engines/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled, expected_revision: row.revision }),
      });
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "更新失败");
        await loadEngines(engineProvider);
        return;
      }
      setEngines((prev) => prev.map((e) => (e.id === row.id ? { ...e, ...res.data! } : e)));
    } catch {
      message.error("更新失败");
    }
  }

  async function onBulkEnabled(enabled: boolean) {
    setBulking(true);
    try {
      const res = await apiJson<{
        provider: string;
        updated: number;
        skipped_missing: number;
      }>("/api/v1/admin/web-search-engines/bulk-enabled", {
        method: "POST",
        body: JSON.stringify({ enabled, provider: engineProvider }),
      });
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "批量操作失败");
        return;
      }
      const skip = res.data.skipped_missing || 0;
      message.success(
        enabled
          ? `已开启 ${res.data.updated} 个${skip ? `（跳过缺失 ${skip}）` : ""}`
          : `已关闭 ${res.data.updated} 个`,
      );
      await loadEngines(engineProvider);
    } catch {
      message.error("批量操作失败");
    } finally {
      setBulking(false);
    }
  }

  const filteredEngines = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return engines;
    return engines.filter(
      (e) =>
        e.engine_key.toLowerCase().includes(kw) ||
        e.display_name.toLowerCase().includes(kw) ||
        (e.categories || []).some((c) => c.toLowerCase().includes(kw)),
    );
  }, [engines, keyword]);

  useEffect(() => {
    setPage(1);
  }, [keyword, pageSize, engineProvider]);

  const columns: ColumnsType<EngineRow> = [
    { title: "引擎", dataIndex: "engine_key", key: "engine_key", width: 160 },
    { title: "名称", dataIndex: "display_name", key: "display_name", width: 160 },
    {
      title: "分类",
      dataIndex: "categories",
      key: "categories",
      render: (cats: string[]) => (cats || []).join(", ") || "-",
    },
    {
      title: "状态",
      dataIndex: "source_status",
      key: "source_status",
      width: 100,
    },
    {
      title: "启用",
      dataIndex: "enabled",
      key: "enabled",
      width: 90,
      render: (_: boolean, row) => (
        <Switch
          checked={row.enabled}
          disabled={row.source_status === "missing"}
          onChange={(v) => void onToggleEngine(row, v)}
        />
      ),
    },
  ];

  return (
    <div style={{ padding: 20, maxWidth: 960 }}>
      <Typography.Paragraph type="secondary">
        总开关关闭时对话不可联网搜索。实现方式二选一：SearXNG（需 Base URL + 同步引擎）或百度搜索（需
        API Key，官方固定地址）。
      </Typography.Paragraph>
      {apiKeySet ? (
        <Typography.Paragraph type="secondary">
          当前密钥：{apiKeyMasked || "已配置"}（留空保存不修改）
        </Typography.Paragraph>
      ) : null}
      <Form
        form={form}
        layout="vertical"
        onFinish={(v) => void onSave(v)}
        disabled={loading}
      >
        <Form.Item name="enabled" label="启用联网搜索" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="provider" label="实现方式" rules={[{ required: true }]}>
          <Select
            options={providers.map((p) => ({
              value: p.id,
              label: p.label,
              disabled: !p.implemented,
            }))}
          />
        </Form.Item>
        <Form.Item
          name="base_url"
          label="Base URL"
          rules={isBaidu ? [] : [{ required: true, message: "请填写 Base URL" }]}
        >
          <Input
            placeholder="http://host.docker.internal:8881"
            readOnly={isBaidu}
            disabled={isBaidu}
          />
        </Form.Item>
        <Form.Item
          name="api_key"
          label={isBaidu ? "API Key（必填）" : "API Key（可选）"}
          rules={
            isBaidu && !apiKeySet
              ? [{ required: true, message: "请填写百度 API Key" }]
              : []
          }
        >
          <Input.Password
            placeholder={isBaidu ? "千帆 API Key" : "SearXNG 通常可不填"}
          />
        </Form.Item>
        <Form.Item name="clear_api_key" label="清除已保存密钥" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="timeout_seconds" label="超时（秒）">
          <InputNumber min={1} max={60} style={{ width: "100%" }} />
        </Form.Item>
        <Form.Item name="result_count" label="结果条数">
          <InputNumber min={1} max={10} style={{ width: "100%" }} />
        </Form.Item>
        <Space wrap>
          <Button type="primary" htmlType="submit" loading={saving}>
            保存
          </Button>
          <Button onClick={() => void onTest()} loading={testing}>
            测试连接
          </Button>
          <Button onClick={() => void load()}>刷新</Button>
        </Space>
      </Form>
      {testHint ? (
        <Typography.Paragraph style={{ marginTop: 16 }} type="secondary">
          {testHint}
        </Typography.Paragraph>
      ) : null}

      {showEngineCatalog ? (
        <>
          <Typography.Title level={5} style={{ marginTop: 32 }}>
            引擎目录（{engineProvider}）
          </Typography.Title>
          <Space wrap style={{ marginBottom: 12 }}>
            <Button type="primary" onClick={() => void onSyncEngines()} loading={syncing}>
              同步引擎
            </Button>
            <Button
              onClick={() => void onBulkEnabled(true)}
              loading={bulking}
              disabled={!engines.length}
            >
              一键开启全部
            </Button>
            <Button
              onClick={() => void onBulkEnabled(false)}
              loading={bulking}
              disabled={!engines.length}
            >
              一键关闭全部
            </Button>
            <Input
              allowClear
              placeholder="按名称/分类过滤"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              style={{ width: 240 }}
            />
            <span>每页</span>
            <Select
              value={pageSize}
              style={{ width: 120 }}
              options={[
                { value: 20, label: "20 条" },
                { value: 50, label: "50 条" },
                { value: 100, label: "100 条" },
                { value: 200, label: "200 条" },
                { value: 500, label: "500 条" },
              ]}
              onChange={(v) => setPageSize(Number(v))}
            />
            <Button onClick={() => void loadEngines(engineProvider)} loading={enginesLoading}>
              刷新列表
            </Button>
          </Space>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
            共 {filteredEngines.length} 条
            {keyword.trim() ? `（已过滤，全量 ${engines.length}）` : ""}
            ；一键开启会跳过状态为 missing 的引擎。
          </Typography.Paragraph>
          <Table
            rowKey="id"
            size="small"
            loading={enginesLoading}
            columns={columns}
            dataSource={filteredEngines}
            pagination={{
              current: page,
              pageSize,
              total: filteredEngines.length,
              showSizeChanger: false,
              showQuickJumper: true,
              onChange: (p) => setPage(p),
              showTotal: (total) => `共 ${total} 条`,
            }}
          />
        </>
      ) : isBaidu ? (
        <Typography.Paragraph type="secondary" style={{ marginTop: 24 }}>
          百度搜索无需引擎目录同步。
        </Typography.Paragraph>
      ) : null}
    </div>
  );
}
