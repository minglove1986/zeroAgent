"use client";
import { useState, useEffect } from "react";
import { AdminLayout } from "@/components/AdminLayout";
import { message, Button, Table, Input, Space, Tag, Modal, Row, Col, Form, Select, InputNumber, Checkbox, Spin } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useRouter } from "next/navigation";
import { apiJson } from "@/lib/api";

type KeywordItem = Record<string, any>;

const CATEGORIES = [
  { value: "explicit_kb", label: "显式查库" },
  { value: "leave", label: "请假" },
  { value: "meta_reply", label: "纠正/元追问" },
  { value: "doc_dump", label: "文档全文" },
  { value: "doc_summarize", label: "文档总结" },
  { value: "doc_critique", label: "文档审查" },
  { value: "person_search_verb", label: "人物检索动作" },
];

const MATCH_MODES = [
  { value: "contains", label: "包含" },
  { value: "equals", label: "等于" },
  { value: "prefix", label: "前缀" },
];

export default function L2KeywordsPage() {
  const [keywords, setKeywords] = useState<KeywordItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [testVisible, setTestVisible] = useState(false);
  const [testForm] = Form.useForm();
  const [testResult, setTestResult] = useState<any>(null);
  const [testLoading, setTestLoading] = useState(false);
  const router = useRouter();

  useEffect(() => {
    loadKeywords();
  }, []);

  async function loadKeywords() {
    try {
      const res = await apiJson("/api/v1/intent/l2-keywords");
      if (res.code === 0) setKeywords(res.data.items || []);
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
      const res = await apiJson("/api/v1/intent/l2-keywords", { method: "POST", body: JSON.stringify(values) });
      if (res.code === 0) { message.success("创建成功"); loadKeywords(); setModalVisible(false); }
      else message.error(res.data?.message || "创建失败");
    } catch (e) { message.error("创建失败，请重试"); }
  }

  async function handleUpdate(id, values) {
    try {
      const res = await apiJson(`/api/v1/intent/l2-keywords/${id}`, { method: "PATCH", body: JSON.stringify(values) });
      if (res.code === 0) { message.success("更新成功"); loadKeywords(); setModalVisible(false); }
      else message.error(res.data?.message || "更新失败");
    } catch (e) { message.error("更新失败，请重试"); }
  }

  async function handleDelete(id) {
    Modal.confirm({ title: "确认删除？", okText: "删除", cancelText: "取消", onOk: async () => {
      try {
        const res = await apiJson(`/api/v1/intent/l2-keywords/${id}`, { method: "DELETE" });
        if (res.code === 0) { message.success("已软删"); loadKeywords(); }
        else message.error(res.data?.message || "删除失败");
      } catch (e) { message.error("删除失败，请重试"); }
    }});
  }

  async function handleReloadCache() {
    try {
      const res = await apiJson("/api/v1/intent/l2-keywords/reload-cache");
      if (res.code === 0) message.success(`缓存已重载 (${res.data.phrase_count} 个短语)`);
      else message.error(res.data?.message || "重载失败");
    } catch (e) { message.error("网络错误"); }
  }

  async function handleTestRun() {
    const values = testForm.getFieldValue();
    setTestLoading(true);
    setTestResult(null);
    try {
      const candidates = editingId ? [{ category: values.category, phrase: values.phrase, match_mode: values.match_mode, priority: values.priority }] : [];
      const res = await apiJson("/api/v1/intent/l2-keywords/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: values.text, candidates }),
      });
      if (res.code === 0) setTestResult(res.data);
      else message.error(res.data?.message || "试跑失败");
    } catch (e) { message.error("网络错误，请检查后端服务"); } finally { setTestLoading(false); }
  }

  const columns = [
    { title: "分类", dataIndex: "category", render: (text) => <Tag color="cyan">{text}</Tag> },
    { title: "短语", dataIndex: "phrase" },
    { title: "模式", dataIndex: "match_mode", render: (text) => (<Tag>{text === "contains" ? "包含" : text === "equals" ? "等于" : "前缀"}</Tag>) },
    { title: "优先级", dataIndex: "priority" },
    { title: "状态", dataIndex: "enabled", render: (v) => (v ? <Tag color="green">启用</Tag> : <Tag color="gray">停用</Tag>) },
    { title: "操作", render: (_, record) => (
      <Space>
        <Button type="link" onClick={() => { setEditingId(record.id); testForm.setFieldsValue(record); setModalVisible(true); }}>编辑</Button>
        <Button type="link" danger onClick={() => handleDelete(record.id)}>软删</Button>
        <Button type="link" onClick={() => { setTestResult(null); testForm.resetFields(); testForm.setFieldsValue({ text: record.phrase + "测试", candidates: [] }); setTestVisible(true); }}>试跑</Button>
      </Space>
    )},
  ];

  return (
    <AdminLayout title="L2 关键词规则">
        <div>
          <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
            <Col span={12}>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingId(null); testForm.resetFields(); setModalVisible(true); }}>
                新增词项
              </Button>
            </Col>
            <Col span={12} style={{ textAlign: "right" }}>
              <Button onClick={handleReloadCache}>重载缓存 → Redis</Button>
            </Col>
          </Row>
          <Table loading={loading} dataSource={keywords} columns={columns} rowKey="id" pagination={{ pageSize: 10 }} />
        </div>

      {/* 新增/编辑抽屉 */}
      {modalVisible && (
        <Modal title={editingId ? "编辑 L2 关键词" : "新增 L2 关键词"} open={true} onCancel={() => { setModalVisible(false); setEditingId(null); testForm.resetFields(); }} footer={[
          <Button key="cancel" onClick={() => { setModalVisible(false); setEditingId(null); testForm.resetFields(); }}>取消</Button>,
          <Button key="confirm" type="primary" onClick={() => testForm.submit()}>保存</Button>
        ]}>
          <Form form={testForm} layout="vertical" onFinish={(values) => { if (editingId) handleUpdate(editingId, values); else handleCreate(values); }}>
            <Form.Item name="category" label="分类" rules={[{ required: true }]}><Select options={CATEGORIES} /></Form.Item>
            <Form.Item name="phrase" label="短语原文" rules={[{ required: true, min: 1, max: 128 }]}><Input placeholder="如：请假、别总结" /></Form.Item>
            <Form.Item name="match_mode" label="匹配模式" initialValue="contains" rules={[{ required: true }]}>
              <Select options={MATCH_MODES} />
            </Form.Item>
            <Form.Item name="enabled" label="默认启用" initialValue={true}><Checkbox /></Form.Item>
            <Form.Item name="priority" label="排序优先级" initialValue={100}><InputNumber min={1} max={1000} style={{ width: "100%" }} /></Form.Item>
            <Form.Item name="remark" label="备注"><Input.TextArea rows={2} placeholder="内部备注（可选）" /></Form.Item>
          </Form>
        </Modal>
      )}

      {/* 试跑抽屉 */}
      {testVisible && (
        <Modal title="L2 规则服务端真实试跑（无副作用）" open={true} width={800} onClose={() => { setTestVisible(false); setTestResult(null); }} footer={[
          <Button key="back" onClick={() => { setTestVisible(false); setTestResult(null); }}>返回</Button>,
          <Button key="confirm" type="primary" disabled={testLoading} onClick={handleTestRun}>{testLoading ? "试跑中…" : "开始试跑"}</Button>
        ]}>
          <Form form={testForm} layout="vertical">
            <Form.Item name="text" label="输入测试语句" rules={[{ required: true, min: 1, max: 512 }]}><TextArea rows={4} placeholder="例如：帮我总结赵世龙的简历" /></Form.Item>
            {testResult && (
              <div style={{ marginTop: 20, padding: 15, background: "#f5f5f5", borderRadius: 6 }}>
                <h4 style={{ margin: "0 0 10px 0" }}>试跑结果：</h4>
                {testResult.matched ? (
                  <>
                    <p><strong>命中层级：</strong>{testResult.layer}</p>
                    <p><strong>最终意图：</strong>{testResult.intent}</p>
                    <p><strong>置信度：</strong>{(testResult.confidence * 100).toFixed(1)}%</p>
                    <p><strong>命中短语：</strong>{testResult.match?.phrase || "-"}</p>
                    <p><strong>原因：</strong>{testResult.reason || testResult.match || "未命中，将继续进入 L3"}</p>
                  </>
                ) : (
                  <p><strong>L2 未命中，将继续进入 L3（LLM 分类器）。</strong></p>
                )}
              </div>
            )}
          </Form>
        </Modal>
      )}
    </AdminLayout>
  );
}