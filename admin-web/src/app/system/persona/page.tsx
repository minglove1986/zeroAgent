/**
 * 系统人格提示词配置页。
 *
 * @author 赵振明
 * @date 2026-07-29 16:00:36
 */
"use client";

import { useEffect, useState } from "react";
import {
  Button,
  Form,
  Input,
  Modal,
  Switch,
  message,
  Space,
  Typography,
  Divider,
  Card,
} from "antd";
import { AdminLayout } from "@/components/AdminLayout";
import { apiJson } from "@/lib/api";

type PersonaData = {
  id: string;
  title: string;
  system_prompt: string;
  enabled: boolean;
  revision: number;
  platform_safety?: string;
  cache?: { redis_ok?: boolean; degraded?: boolean; catalog_version?: number };
  cache_refreshed?: boolean;
};

type TrialResult = {
  reply: string;
  used_persona: boolean;
};

export default function SystemPersonaPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [trialLoading, setTrialLoading] = useState(false);
  const [form] = Form.useForm();
  const [trialForm] = Form.useForm();
  const [revision, setRevision] = useState(1);
  const [cacheHint, setCacheHint] = useState("");
  const [platformSafety, setPlatformSafety] = useState("");
  const [trialResult, setTrialResult] = useState<TrialResult | null>(null);

  async function load() {
    setLoading(true);
    try {
      const res = await apiJson<PersonaData>("/api/v1/system/persona");
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "加载失败");
        return;
      }
      form.setFieldsValue({
        title: res.data.title,
        system_prompt: res.data.system_prompt,
        enabled: res.data.enabled,
      });
      setRevision(res.data.revision);
      setPlatformSafety(res.data.platform_safety || "");
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

  useEffect(() => {
    void load();
  }, []);

  async function onSave(values: {
    title: string;
    system_prompt: string;
    enabled: boolean;
  }) {
    setSaving(true);
    try {
      const res = await apiJson<PersonaData>("/api/v1/system/persona", {
        method: "PUT",
        body: JSON.stringify({
          ...values,
          expected_revision: revision,
        }),
      });
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "保存失败");
        return;
      }
      message.success(
        res.data.cache_refreshed === false
          ? "已保存，但缓存刷新失败，请点「重载缓存」"
          : "已保存并生效",
      );
      setRevision(res.data.revision);
      await load();
    } catch {
      message.error("保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function onReload() {
    try {
      const res = await apiJson("/api/v1/system/persona/reload-cache", {
        method: "POST",
      });
      if (res.code === 0) {
        message.success("缓存已重载");
        await load();
      } else {
        message.error(res.message || "重载失败");
      }
    } catch {
      message.error("网络错误");
    }
  }

  function onResetDefault() {
    Modal.confirm({
      title: "确认恢复默认？",
      content: "将标题与人格提示词恢复为系统种子文案，启用状态保持不变。",
      okText: "恢复默认",
      cancelText: "取消",
      onOk: async () => {
        const res = await apiJson<PersonaData>("/api/v1/system/persona/reset-default", {
          method: "POST",
        });
        if (res.code !== 0 || !res.data) {
          message.error(res.message || "恢复失败");
          return;
        }
        message.success("已恢复默认种子");
        setRevision(res.data.revision);
        await load();
      },
    });
  }

  async function onTrial(values: { message: string; use_draft: boolean }) {
    setTrialLoading(true);
    setTrialResult(null);
    try {
      const draft = form.getFieldValue("system_prompt") as string | undefined;
      const body: { message: string; system_prompt?: string } = {
        message: values.message,
      };
      if (values.use_draft) {
        body.system_prompt = draft || "";
      }
      const res = await apiJson<TrialResult>("/api/v1/system/persona/test", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "试聊失败");
        return;
      }
      setTrialResult(res.data);
    } catch {
      message.error("试聊网络错误");
    } finally {
      setTrialLoading(false);
    }
  }

  return (
    <AdminLayout title="系统人格">
      <Typography.Paragraph type="secondary">
        无 Agent 绑定时必用；新建 Agent 可勾选「继承系统人格」。修改后立即对勾选继承的
        Agent 生效。平台安全段由研发受控，始终最前注入且不可改写。
      </Typography.Paragraph>
      {cacheHint ? (
        <Typography.Text type="secondary" style={{ display: "block", marginBottom: 16 }}>
          {cacheHint}
        </Typography.Text>
      ) : null}

      {platformSafety ? (
        <Card size="small" title="平台安全（只读）" style={{ maxWidth: 720, marginBottom: 24 }}>
          <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
            {platformSafety}
          </Typography.Paragraph>
        </Card>
      ) : null}

      <Form
        form={form}
        layout="vertical"
        style={{ maxWidth: 720 }}
        onFinish={(v) => void onSave(v)}
        disabled={loading}
      >
        <Form.Item
          name="title"
          label="名称"
          rules={[{ required: true, message: "请输入名称" }]}
        >
          <Input maxLength={100} placeholder="如：公司智能助手" />
        </Form.Item>
        <Form.Item
          name="system_prompt"
          label="人格提示词"
          rules={[
            { required: true, message: "请输入提示词" },
            { max: 4000, message: "最多 4000 字" },
          ]}
          extra="建议 300～800 字，硬上限 4000"
        >
          <Input.TextArea
            rows={10}
            showCount
            maxLength={4000}
            placeholder="例如：你是某某公司的智能助手，说话礼貌、简洁……"
          />
        </Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Space wrap>
          <Button type="primary" htmlType="submit" loading={saving}>
            保存
          </Button>
          <Button onClick={() => void onReload()}>重载缓存</Button>
          <Button danger onClick={onResetDefault}>
            恢复默认
          </Button>
        </Space>
      </Form>

      <Divider />

      <Typography.Title level={5}>人设试聊（无副作用）</Typography.Title>
      <Typography.Paragraph type="secondary">
        仅调用模型一轮回复，不写记忆、不改业务状态。可选用表单中未保存的草稿人格。
      </Typography.Paragraph>
      <Form
        form={trialForm}
        layout="vertical"
        style={{ maxWidth: 720 }}
        initialValues={{ use_draft: true }}
        onFinish={(v) => void onTrial(v)}
      >
        <Form.Item
          name="message"
          label="试聊内容"
          rules={[{ required: true, message: "请输入试聊内容" }]}
        >
          <Input.TextArea rows={3} maxLength={2000} showCount placeholder="例如：你好，你是谁？" />
        </Form.Item>
        <Form.Item name="use_draft" label="使用上方草稿人格" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Button type="default" htmlType="submit" loading={trialLoading}>
          开始试聊
        </Button>
      </Form>
      {trialResult ? (
        <Card size="small" title="试聊回复" style={{ maxWidth: 720, marginTop: 16 }}>
          <Typography.Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
            {trialResult.used_persona ? "已注入人格段" : "未注入人格段（停用或空）"}
          </Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
            {trialResult.reply || "（空回复）"}
          </Typography.Paragraph>
        </Card>
      ) : null}
    </AdminLayout>
  );
}
