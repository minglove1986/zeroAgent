/**
 * 文档分类树形 CRUD（最多 3 级；删除保护）。
 * @author 赵振明
 * @date 2026-11-20 14:55:51
 */
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Tree,
  Typography,
} from "antd";
import type { DataNode } from "antd/es/tree";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

const { Title, Paragraph, Text } = Typography;

const SCHEMA_OPTIONS = [
  { value: "schema_resume", label: "简历 schema_resume" },
  { value: "schema_policy", label: "制度 schema_policy" },
  { value: "schema_runbook", label: "运维手册 schema_runbook" },
  { value: "schema_generic", label: "通用 schema_generic" },
  { value: "schema_notice", label: "公告 schema_notice" },
];

type CatItem = {
  id: string;
  code: string;
  name: string;
  parent_id?: string | null;
  schema_code?: string | null;
  sort: number;
  enabled: boolean;
};

type FormValues = {
  code?: string;
  name: string;
  parent_id?: string | null;
  schema_code?: string | null;
  sort: number;
  enabled: boolean;
};

/**
 * 将扁平分类列表转为 Tree 数据。
 */
function buildTree(items: CatItem[]): DataNode[] {
  const byParent = new Map<string | null, CatItem[]>();
  for (const it of items) {
    const key = it.parent_id || null;
    const list = byParent.get(key) || [];
    list.push(it);
    byParent.set(key, list);
  }
  const walk = (parentId: string | null): DataNode[] => {
    const children = byParent.get(parentId) || [];
    return children.map((c) => ({
      key: c.id,
      title: `${c.name}${c.enabled ? "" : "（停用）"}`,
      children: walk(c.id),
    }));
  };
  return walk(null);
}

export default function KnowledgeCategoriesPage() {
  useAdminPageTitle("文档分类");
  const { message } = App.useApp();
  const [items, setItems] = useState<CatItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<"create" | "edit">("create");
  const [form] = Form.useForm<FormValues>();

  const selected = useMemo(
    () => items.find((x) => x.id === selectedId) || null,
    [items, selectedId],
  );

  const treeData = useMemo(() => buildTree(items), [items]);

  const parentOptions = useMemo(() => {
    const depthOf = (id: string | null | undefined, guard = 0): number => {
      if (!id || guard > 8) return 0;
      const row = items.find((x) => x.id === id);
      if (!row) return 0;
      return 1 + depthOf(row.parent_id, guard + 1);
    };
    return items
      .filter((x) => depthOf(x.id) < 3)
      .map((x) => ({
        value: x.id,
        label: `${x.name} (${x.code})`,
      }));
  }, [items]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiJson<{ items: CatItem[] }>(
        "/api/v1/doc-categories?include_disabled=true",
      );
      if (res.code !== 0) {
        message.error(res.message || "加载失败");
        return;
      }
      setItems(res.data?.items || []);
    } catch (err) {
      message.error(`加载失败：${(err as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void load();
  }, [load]);

  function openCreate(parentId?: string | null) {
    setModalMode("create");
    form.resetFields();
    form.setFieldsValue({
      code: "",
      name: "",
      parent_id: parentId || undefined,
      schema_code: undefined,
      sort: 0,
      enabled: true,
    });
    setModalOpen(true);
  }

  function openEdit(row: CatItem) {
    setModalMode("edit");
    form.setFieldsValue({
      code: row.code,
      name: row.name,
      parent_id: row.parent_id || undefined,
      schema_code: row.schema_code || undefined,
      sort: row.sort,
      enabled: row.enabled,
    });
    setModalOpen(true);
  }

  async function submitModal() {
    const values = await form.validateFields();
    try {
      if (modalMode === "create") {
        const res = await apiJson<CatItem>("/api/v1/doc-categories", {
          method: "POST",
          body: JSON.stringify({
            code: values.code,
            name: values.name,
            parent_id: values.parent_id || null,
            schema_code: values.schema_code || null,
            sort: values.sort ?? 0,
            enabled: values.enabled ?? true,
          }),
        });
        if (res.code !== 0) {
          message.error(res.message || "创建失败");
          return;
        }
        message.success("已创建");
        setSelectedId(res.data?.id || null);
      } else if (selected) {
        const clearParent =
          !values.parent_id && Boolean(selected.parent_id);
        const clearSchema =
          !values.schema_code && Boolean(selected.schema_code);
        const res = await apiJson<CatItem>(
          `/api/v1/doc-categories/${encodeURIComponent(selected.id)}`,
          {
            method: "PATCH",
            body: JSON.stringify({
              name: values.name,
              parent_id: values.parent_id || null,
              schema_code: values.schema_code || null,
              sort: values.sort ?? 0,
              enabled: values.enabled ?? true,
              clear_parent: clearParent,
              clear_schema: clearSchema,
            }),
          },
        );
        if (res.code !== 0) {
          message.error(res.message || "更新失败");
          return;
        }
        message.success("已更新");
      }
      setModalOpen(false);
      await load();
    } catch (err) {
      message.error(`保存失败：${(err as Error).message}`);
    }
  }

  async function onToggleEnabled(row: CatItem, enabled: boolean) {
    try {
      const res = await apiJson(
        `/api/v1/doc-categories/${encodeURIComponent(row.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify({ enabled }),
        },
      );
      if (res.code !== 0) {
        message.error(res.message || "启停失败");
        return;
      }
      message.success(enabled ? "已启用" : "已停用");
      await load();
    } catch (err) {
      message.error(`启停失败：${(err as Error).message}`);
    }
  }

  async function onDelete(row: CatItem) {
    try {
      const res = await apiJson(
        `/api/v1/doc-categories/${encodeURIComponent(row.id)}`,
        { method: "DELETE" },
      );
      if (res.code !== 0) {
        message.error(res.message || "删除失败");
        return;
      }
      message.success("已删除");
      if (selectedId === row.id) setSelectedId(null);
      await load();
    } catch (err) {
      message.error(`删除失败：${(err as Error).message}`);
    }
  }

  const hasChildren = selected
    ? items.some((x) => x.parent_id === selected.id)
    : false;

  return (
    <div style={{ padding: 20 }}>
      <Title level={3}>文档分类</Title>
      <Paragraph type="secondary">
        最多 3 级、根节点 ≤10；schema 白名单；被文档引用或有子节点时不可删。种子分类仅补缺，不覆盖人工修改。
      </Paragraph>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(260px, 340px) 1fr",
          gap: 24,
          alignItems: "start",
        }}
      >
        <div>
          <Space style={{ marginBottom: 12 }}>
            <Button type="primary" onClick={() => openCreate(null)}>
              新建根分类
            </Button>
            <Button onClick={() => void load()} loading={loading}>
              刷新
            </Button>
          </Space>
          <Tree
            treeData={treeData}
            selectedKeys={selectedId ? [selectedId] : []}
            onSelect={(keys) => {
              const k = keys[0];
              setSelectedId(typeof k === "string" ? k : null);
            }}
            defaultExpandAll
            style={{
              background: "var(--ant-color-bg-container, #fff)",
              padding: 12,
              border: "1px solid var(--ant-color-border, #f0f0f0)",
              borderRadius: 8,
              minHeight: 320,
            }}
          />
        </div>
        <div
          style={{
            padding: 16,
            border: "1px solid var(--ant-color-border, #f0f0f0)",
            borderRadius: 8,
            minHeight: 320,
          }}
        >
          {!selected ? (
            <Text type="secondary">请选择左侧分类查看详情</Text>
          ) : (
            <>
              <Title level={4} style={{ marginTop: 0 }}>
                {selected.name}
              </Title>
              <Paragraph>
                <Text type="secondary">编码：</Text>
                {selected.code}
              </Paragraph>
              <Paragraph>
                <Text type="secondary">父级：</Text>
                {selected.parent_id || "（根）"}
              </Paragraph>
              <Paragraph>
                <Text type="secondary">Schema：</Text>
                {selected.schema_code || "（分组节点）"}
              </Paragraph>
              <Paragraph>
                <Text type="secondary">排序：</Text>
                {selected.sort}
              </Paragraph>
              <Paragraph>
                <Text type="secondary">启用：</Text>
                <Switch
                  checked={selected.enabled}
                  onChange={(v) => void onToggleEnabled(selected, v)}
                />
              </Paragraph>
              <Space wrap>
                <Button onClick={() => openEdit(selected)}>编辑</Button>
                <Button onClick={() => openCreate(selected.id)}>
                  新增子分类
                </Button>
                <Popconfirm
                  title="确认删除该分类？"
                  disabled={hasChildren}
                  onConfirm={() => void onDelete(selected)}
                >
                  <Button danger disabled={hasChildren}>
                    {hasChildren ? "有子节点不可删" : "删除"}
                  </Button>
                </Popconfirm>
              </Space>
              {hasChildren ? (
                <Paragraph type="secondary" style={{ marginTop: 12 }}>
                  存在子分类时须先删子节点；若已被文档引用，接口将返回 409。
                </Paragraph>
              ) : null}
            </>
          )}
        </div>
      </div>

      <Modal
        title={modalMode === "create" ? "新建分类" : "编辑分类"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitModal()}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="code"
            label="编码"
            rules={[
              { required: true, message: "必填" },
              {
                pattern: /^[a-z][a-z0-9_.-]{0,62}$/,
                message: "小写字母开头，仅 a-z0-9_.-",
              },
            ]}
          >
            <Input disabled={modalMode === "edit"} placeholder="如 hr.custom" />
          </Form.Item>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "必填" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="parent_id" label="父级">
            <Select
              allowClear
              options={parentOptions.filter(
                (o) => modalMode !== "edit" || o.value !== selected?.id,
              )}
              placeholder="空=根分类"
            />
          </Form.Item>
          <Form.Item name="schema_code" label="Schema">
            <Select
              allowClear
              options={SCHEMA_OPTIONS}
              placeholder="分组节点可不选"
            />
          </Form.Item>
          <Form.Item name="sort" label="排序" initialValue={0}>
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
