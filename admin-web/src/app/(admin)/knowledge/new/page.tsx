/**
 * 新建知识库表单。
 * @author 赵振明
 * @date 2026-11-20 14:22:56
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { App, Button, Form, Input, Radio, Select, Space, Typography } from "antd";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

const { Title, Paragraph } = Typography;

type DeptItem = { id: string; name: string };

export default function KnowledgeNewPage() {
  useAdminPageTitle("新建知识库");
  const { message } = App.useApp();
  const router = useRouter();
  const [form] = Form.useForm();
  const [depts, setDepts] = useState<DeptItem[]>([]);
  const [busy, setBusy] = useState(false);
  const visibility = Form.useWatch("visibility", form);

  const loadDepts = useCallback(async () => {
    try {
      const res = await apiJson<{ items: DeptItem[] }>("/api/v1/departments");
      if (res.code === 0) {
        setDepts(res.data?.items || []);
      }
    } catch {
      /* 部门可选；失败不阻断公开库 */
    }
  }, []);

  useEffect(() => {
    void loadDepts();
  }, [loadDepts]);

  async function onFinish(values: {
    name: string;
    description?: string;
    visibility: "public" | "department";
    owner_department_id?: string;
  }) {
    setBusy(true);
    try {
      const res = await apiJson<{ id: string }>("/api/v1/knowledge-bases", {
        method: "POST",
        body: JSON.stringify({
          name: values.name.trim(),
          description: values.description?.trim() || "",
          visibility: values.visibility,
          owner_department_id:
            values.visibility === "department"
              ? values.owner_department_id || null
              : null,
        }),
      });
      if (res.code !== 0 || !res.data?.id) {
        message.error(res.message || "创建失败");
        return;
      }
      message.success("已创建知识库");
      router.push(`/knowledge/${encodeURIComponent(res.data.id)}`);
    } catch (err) {
      message.error(`创建失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ padding: 20, maxWidth: 560 }}>
      <Title level={3}>新建知识库</Title>
      <Paragraph type="secondary">仅平台超管可创建；部门私有须选择归属部门。</Paragraph>
      <Form
        form={form}
        layout="vertical"
        initialValues={{ visibility: "public" }}
        onFinish={(v) => void onFinish(v)}
      >
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, message: "请填写名称" }]}
        >
          <Input maxLength={100} placeholder="例如：人事制度库" />
        </Form.Item>
        <Form.Item name="description" label="描述">
          <Input.TextArea rows={3} maxLength={500} />
        </Form.Item>
        <Form.Item name="visibility" label="可见性" rules={[{ required: true }]}>
          <Radio.Group>
            <Radio value="public">公司内公开</Radio>
            <Radio value="department">部门私有</Radio>
          </Radio.Group>
        </Form.Item>
        {visibility === "department" ? (
          <Form.Item
            name="owner_department_id"
            label="归属部门"
            rules={[{ required: true, message: "请选择归属部门" }]}
          >
            <Select
              options={depts.map((d) => ({ value: d.id, label: d.name }))}
              placeholder="选择部门"
              showSearch
              optionFilterProp="label"
            />
          </Form.Item>
        ) : null}
        <Space>
          <Button type="primary" htmlType="submit" loading={busy}>
            创建
          </Button>
          <Link href="/knowledge">
            <Button>取消</Button>
          </Link>
        </Space>
      </Form>
    </div>
  );
}
