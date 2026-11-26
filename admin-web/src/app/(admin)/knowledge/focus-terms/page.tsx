/**
 * 检索专名词典：命中后硬过滤 KB 文档范围。
 *
 * @author 赵振明
 * @date 2026-11-23 15:22:03
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from "antd";
import {
  PlusOutlined,
  ReloadOutlined,
  ExperimentOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

type FocusTerm = {
  id: string;
  term: string;
  aliases: string[];
  kind: "person" | "project" | "other" | string;
  enabled: boolean;
  priority: number;
  remark?: string | null;
  origin?: string;
};

type TestHit = {
  term: string;
  aliases?: string[];
  kind?: string;
};

const KIND_OPTIONS = [
  { value: "person", label: "人名" },
  { value: "project", label: "项目/产品" },
  { value: "other", label: "其他" },
];

/**
 * 检索专名维护页。
 *
 * @author 赵振明
 * @date 2026-11-23 15:22:03
 */
export default function FocusTermsPage() {
  const { message, modal } = App.useApp();
  useAdminPageTitle("检索专名");

  const [items, setItems] = useState<FocusTerm[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [kind, setKind] = useState<string | undefined>();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<FocusTerm | null>(null);
  const [testOpen, setTestOpen] = useState(false);
  const [testText, setTestText] = useState("");
  const [testHits, setTestHits] = useState<TestHit[]>([]);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: "50",
      });
      if (kind) params.set("kind", kind);
      if (q.trim()) params.set("q", q.trim());
      const res = await apiJson<{ items: FocusTerm[]; total: number }>(
        `/api/v1/knowledge/focus-terms?${params.toString()}`,
      );
      if (res.code !== 0) {
        message.error(res.message || "加载失败");
        return;
      }
      setItems(res.data?.items || []);
      setTotal(res.data?.total || 0);
    } catch {
      message.error("网络错误");
    } finally {
      setLoading(false);
    }
  }, [kind, message, page, q]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 打开新建/编辑弹窗。 */
  function openEdit(row?: FocusTerm) {
    setEditing(row || null);
    form.setFieldsValue(
      row
        ? {
            term: row.term,
            kind: row.kind,
            aliases: (row.aliases || []).join(", "),
            enabled: row.enabled,
            priority: row.priority,
            remark: row.remark,
          }
        : {
            term: "",
            kind: "project",
            aliases: "",
            enabled: true,
            priority: 100,
            remark: "",
          },
    );
    setModalOpen(true);
  }

  /** 解析别名输入（逗号/空格分隔）。 */
  function parseAliasesInput(raw: unknown): string[] {
    const s = String(raw || "");
    return s
      .split(/[,，\s]+/)
      .map((x) => x.trim())
      .filter(Boolean);
  }

  /** 提交新建或更新。 */
  async function onSubmit(values: Record<string, unknown>) {
    const body = {
      term: String(values.term || "").trim(),
      kind: values.kind,
      aliases: parseAliasesInput(values.aliases),
      enabled: Boolean(values.enabled),
      priority: Number(values.priority ?? 100),
      remark: values.remark ? String(values.remark) : null,
    };
    try {
      const res = editing
        ? await apiJson(`/api/v1/knowledge/focus-terms/${editing.id}`, {
            method: "PATCH",
            body: JSON.stringify(body),
          })
        : await apiJson("/api/v1/knowledge/focus-terms", {
            method: "POST",
            body: JSON.stringify(body),
          });
      if (res.code !== 0) {
        message.error(res.message || "保存失败");
        return;
      }
      message.success(editing ? "已更新" : "已创建");
      setModalOpen(false);
      await load();
    } catch {
      message.error("保存失败");
    }
  }

  /** 软删。 */
  function onDelete(row: FocusTerm) {
    modal.confirm({
      title: `删除专名「${row.term}」？`,
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        const res = await apiJson(`/api/v1/knowledge/focus-terms/${row.id}`, {
          method: "DELETE",
        });
        if (res.code !== 0) {
          message.error(res.message || "删除失败");
          return;
        }
        message.success("已删除");
        await load();
      },
    });
  }

  /** 重载缓存。 */
  async function onReload() {
    const res = await apiJson<{ term_count: number }>(
      "/api/v1/knowledge/focus-terms/reload-cache",
      { method: "POST" },
    );
    if (res.code === 0) {
      message.success(`缓存已重载（${res.data?.term_count ?? 0}）`);
      await load();
    } else {
      message.error(res.message || "重载失败");
    }
  }

  /** 从标题同步人名。 */
  async function onSyncTitles() {
    const res = await apiJson<{ inserted: number; skipped: number }>(
      "/api/v1/knowledge/focus-terms/sync-from-titles",
      { method: "POST" },
    );
    if (res.code === 0) {
      message.success(
        `同步完成：新增 ${res.data?.inserted ?? 0}，跳过 ${res.data?.skipped ?? 0}`,
      );
      await load();
    } else {
      message.error(res.message || "同步失败");
    }
  }

  /** 试匹配。 */
  async function onTest() {
    const res = await apiJson<{ matched: TestHit[]; count: number }>(
      "/api/v1/knowledge/focus-terms/test",
      { method: "POST", body: JSON.stringify({ text: testText }) },
    );
    if (res.code !== 0) {
      message.error(res.message || "试匹配失败");
      return;
    }
    setTestHits(res.data?.matched || []);
    message.success(`命中 ${res.data?.count ?? 0} 个专名`);
  }

  /** 行内启停。 */
  async function onToggleEnabled(row: FocusTerm, enabled: boolean) {
    const res = await apiJson(`/api/v1/knowledge/focus-terms/${row.id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
    if (res.code !== 0) {
      message.error(res.message || "更新失败");
      return;
    }
    await load();
  }

  const columns = [
    {
      title: "专名",
      dataIndex: "term",
      render: (t: string, row: FocusTerm) => (
        <Space>
          <strong>{t}</strong>
          {row.origin === "auto_title" ? <Tag>标题同步</Tag> : null}
        </Space>
      ),
    },
    {
      title: "类型",
      dataIndex: "kind",
      width: 110,
      render: (k: string) =>
        KIND_OPTIONS.find((x) => x.value === k)?.label || k,
    },
    {
      title: "别名",
      dataIndex: "aliases",
      render: (als: string[]) =>
        (als || []).length ? (
          <Space size={[4, 4]} wrap>
            {als.map((a) => (
              <Tag key={a}>{a}</Tag>
            ))}
          </Space>
        ) : (
          <span style={{ color: "#999" }}>—</span>
        ),
    },
    {
      title: "优先级",
      dataIndex: "priority",
      width: 90,
    },
    {
      title: "启用",
      dataIndex: "enabled",
      width: 80,
      render: (v: boolean, row: FocusTerm) => (
        <Switch
          checked={v}
          onChange={(checked) => void onToggleEnabled(row, checked)}
        />
      ),
    },
    {
      title: "备注",
      dataIndex: "remark",
      ellipsis: true,
    },
    {
      title: "操作",
      width: 140,
      render: (_: unknown, row: FocusTerm) => (
        <Space>
          <Button type="link" size="small" onClick={() => openEdit(row)}>
            编辑
          </Button>
          <Button type="link" size="small" danger onClick={() => onDelete(row)}>
            删除
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space wrap style={{ marginBottom: 16 }}>
        <Select
          allowClear
          placeholder="类型"
          style={{ width: 140 }}
          options={KIND_OPTIONS}
          value={kind}
          onChange={(v) => {
            setPage(1);
            setKind(v);
          }}
        />
        <Input.Search
          placeholder="搜索专名/别名"
          allowClear
          style={{ width: 220 }}
          onSearch={(v) => {
            setPage(1);
            setQ(v);
          }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={() => openEdit()}>
          新建
        </Button>
        <Button icon={<ReloadOutlined />} onClick={() => void onReload()}>
          重载缓存
        </Button>
        <Button icon={<SyncOutlined />} onClick={() => void onSyncTitles()}>
          从标题同步人名
        </Button>
        <Button
          icon={<ExperimentOutlined />}
          onClick={() => {
            setTestHits([]);
            setTestOpen(true);
          }}
        >
          试匹配
        </Button>
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{
          current: page,
          total,
          pageSize: 50,
          onChange: (p) => setPage(p),
        }}
      />

      <Modal
        title={editing ? "编辑专名" : "新建专名"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={(v) => void onSubmit(v)}>
          <Form.Item
            name="term"
            label="规范名"
            rules={[{ required: true, message: "请输入专名" }]}
          >
            <Input placeholder="如：好友买" />
          </Form.Item>
          <Form.Item name="kind" label="类型" rules={[{ required: true }]}>
            <Select options={KIND_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="aliases"
            label="别名"
            extra="逗号或空格分隔，如 hoolebuy goalgo-engine"
          >
            <Input.TextArea rows={2} placeholder="别名列表" />
          </Form.Item>
          <Form.Item name="priority" label="优先级" initialValue={100}>
            <InputNumber min={1} max={9999} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="试匹配"
        open={testOpen}
        onCancel={() => setTestOpen(false)}
        onOk={() => void onTest()}
        okText="匹配"
        destroyOnHidden
      >
        <Input.TextArea
          rows={3}
          value={testText}
          onChange={(e) => setTestText(e.target.value)}
          placeholder="输入问句，如：关于好友买项目你知道多少"
        />
        {testHits.length > 0 ? (
          <div style={{ marginTop: 12 }}>
            {testHits.map((h) => (
              <Tag key={h.term} color="blue">
                {h.term}
                {h.kind ? ` · ${h.kind}` : ""}
              </Tag>
            ))}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
