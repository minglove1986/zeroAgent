"use client";
import { useState, useEffect } from "react";
import { AdminLayout } from "@/components/AdminLayout";
import { message, Button, Table, Input, Space, Tag, Modal, Row, Col, Form, Select, Checkbox, InputNumber } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";
import { apiJson } from "@/lib/api";

type FieldItem = Record<string, any>;

const CATEGORIES = [
  { value: "fact", label: "事实" },
  { value: "preference", label: "偏好" },
  { value: "summary", label: "摘要" },
];

export default function MemoryFieldsPage() {
  const [fields, setFields] = useState<FieldItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form] = Form.useForm();
  const router = useRouter();

  useEffect(() => {
    loadFields();
  }, []);

  async function loadFields() {
    try {
      const res = await apiJson("/api/v1/memory/extract-fields");
      if (res.code === 0) setFields(res.data.items || []);
      else message.error(res.message || "加载失败");
    } catch (e) {
      console.error(e);
      message.error("网络错误");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(values) {
    try {
      const res = await apiJson("/api/v1/memory/extract-fields", {
        method: "POST",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("创建成功");
        loadFields();
        setModalVisible(false);
      } else {
        message.error(res.data?.message || "创建失败");
      }
    } catch (e) {
      message.error("创建失败，请重试");
    }
  }

  async function handleUpdate(id, values) {
    try {
      const res = await apiJson(`/api/v1/memory/extract-fields/${id}`, {
        method: "PATCH",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("更新成功");
        loadFields();
        setModalVisible(false);
      } else {
        message.error(res.data?.message || "更新失败");
      }
    } catch (e) {
      message.error("更新失败，请重试");
    }
  }

  async function handleDelete(id) {
    Modal.confirm({
      title: "确认删除？",
      okText: "删除",
      cancelText: "取消",
      onOk: async () => {
        try {
          const res = await apiJson(`/api/v1/memory/extract-fields/${id}`, { method: "DELETE" });
          if (res.code === 0) {
            message.success("已软删");
            loadFields();
          } else {
            message.error(res.data?.message || "删除失败");
          }
        } catch (e) {
          message.error("删除失败，请重试");
        }
      },
    });
  }

  async function handleReloadCache() {
    try {
      const res = await apiJson("/api/v1/memory/extract-fields/reload-cache");
      if (res.code === 0) {
        message.success(`缓存已重载 (${res.data.field_count} 个字段)`);
        loadFields();
      } else {
        message.error(res.data?.message || "重载失败");
      }
    } catch (e) {
      message.error("网络错误");
    }
  }

  const columns = [
    { title: "名称", dataIndex: "label", render: (text) => <Tag>{text}</Tag> },
    { title: "字段键", dataIndex: "field_key" },
    { title: "类别", dataIndex: "category", render: (text) => <Tag color="blue">{text}</Tag> },
    { title: "状态", dataIndex: "enabled", render: (v) => (v ? <Tag color="green">启用</Tag> : <Tag color="gray">停用</Tag>) },
    { title: "操作", render: (_, record) => (
      <Space>
        <Button type="link" onClick={() => { setEditingId(record.id); form.setFieldsValue(record); setModalVisible(true); }}>编辑</Button>
        <Button type="link" danger onClick={() => handleDelete(record.id)}>软删</Button>
      </Space>
    )},
  ];

  return (
    <AdminLayout title="记忆抽取白名单">
        <div>
          <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
            <Col span={12}>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingId(null); form.resetFields(); setModalVisible(true); }}>
                新增字段
              </Button>
            </Col>
            <Col span={12} style={{ textAlign: "right" }}>
              <Button onClick={handleReloadCache}>重载缓存 → Redis</Button>
            </Col>
          </Row>
          <Table
            loading={loading}
            dataSource={fields}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 10 }}
          />
        </div>

      {/* 新增/编辑抽屉 */}
      {modalVisible && (
        <Modal
          title={editingId ? "编辑记忆字段" : "新增记忆抽取字段"}
          open={true}
          onCancel={() => { setModalVisible(false); setEditingId(null); form.resetFields(); }}
          footer={[
            <Button key="cancel" onClick={() => { setModalVisible(false); setEditingId(null); form.resetFields(); }}>取消</Button>,
            <Button key="confirm" type="primary" onClick={() => form.submit()}>保存</Button>,
          ]}
        >
          <Form form={form} layout="vertical" onFinish={(values) => {
            if (editingId) handleUpdate(editingId, values);
            else handleCreate(values);
          }}>
            <Form.Item name="category" label="类别" rules={[{ required: true }]}>
              <Select options={CATEGORIES} />
            </Form.Item>
            <Form.Item name="field_key" label="字段键（key）" rules={[{ required: true, pattern: /^[a-z][a-z0-9_]{0,63}$/ }]}>
              <Input placeholder="如：hobby, display_name" />
            </Form.Item>
            <Form.Item name="label" label="显示名" rules={[{ required: true }]}>
              <Input placeholder="如：爱好、姓名" />
            </Form.Item>
            <Form.Item name="description" label="描述">
              <Input.TextArea rows={3} placeholder="用于抽取提示词的业务说明" />
            </Form.Item>
            <Form.Item name="enabled" label="默认启用" initialValue={true}>
              <Checkbox />
            </Form.Item>
            <Form.Item name="priority" label="排序优先级" initialValue={100}>
              <InputNumber min={1} max={1000} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="remark" label="备注">
              <Input.TextArea rows={2} placeholder="内部备注" />
            </Form.Item>
          </Form>
        </Modal>
      )}
    </AdminLayout>
  );
}