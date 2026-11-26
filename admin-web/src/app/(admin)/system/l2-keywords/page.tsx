/**
 * L2 关键词规则：按固定分类卡片 + 短语标签云呈现。
 *
 * @author 赵振明
 * @date 2026-09-09 15:08:00
 */
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Checkbox,
  Collapse,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
} from "antd";
import { PlusOutlined, ExperimentOutlined } from "@ant-design/icons";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";
import { isL2KeywordDeletable } from "./deletable";

type KeywordItem = {
  id: string;
  category: string;
  phrase: string;
  match_mode: "contains" | "equals" | "prefix" | string;
  enabled: boolean;
  priority: number;
  remark?: string | null;
  origin?: string;
  seed_code?: string | null;
  revision?: number;
};

type TestResult = {
  matched?: boolean;
  layer?: string;
  intent?: string;
  confidence?: number;
  reason?: string;
  match?: { phrase?: string; candidate_intent?: string };
  gate_action?: string | null;
  gate_reason?: string | null;
  would_short_circuit?: boolean;
  clarify_kind?: string | null;
};

/** 固定分类：界面只展示中文名与用途，code 仅作提交值。 */
const CATEGORIES = [
  {
    value: "explicit_kb",
    label: "显式查库",
    hint: "用户明确要求查知识库时命中，例如「查询知识库」「在知识库里找」。",
  },
  {
    value: "leave",
    label: "请假相关",
    hint: "仅办理金句入库（我要请假/申请年假…）。线索短词（请假/年假）不进种子，仅代码侧识别。",
  },
  {
    value: "meta_reply",
    label: "纠正与元追问",
    hint: "短纠正骨架即可；勿再加「我没让你总结」等已被「我没让你」覆盖的长短语。",
  },
  {
    value: "doc_dump",
    label: "文档全文",
    hint: "默认无种子；运营可自加。无把握请留空交 L3。",
  },
  {
    value: "doc_summarize",
    label: "文档总结",
    hint: "默认无种子；勿再添加单独「总结」等短词。",
  },
  {
    value: "doc_critique",
    label: "文档审查",
    hint: "默认无种子；勿再添加「不合理」「审查」等泛化词。",
  },
  {
    value: "person_search_verb",
    label: "人物检索动作",
    hint: "默认无种子；人名优先词典。勿添加「看看」「查一下」。",
  },
] as const;

const MATCH_MODES = [
  { value: "contains", label: "包含" },
  { value: "equals", label: "等于" },
  { value: "prefix", label: "前缀" },
];

const PAGE_SIZE = 200;

/** 匹配模式短徽标。 */
function matchBadge(mode: string): string {
  if (mode === "equals") return "等";
  if (mode === "prefix") return "前";
  return "含";
}

/** 拉取全部关键词（page_size=200，必要时翻页）。 */
async function fetchAllKeywords(): Promise<KeywordItem[]> {
  const all: KeywordItem[] = [];
  let page = 1;
  let total = Infinity;
  while (all.length < total) {
    const res = await apiJson<{
      items: KeywordItem[];
      total?: number;
      page?: number;
      page_size?: number;
    }>(`/api/v1/intent/l2-keywords?page=${page}&page_size=${PAGE_SIZE}`);
    if (res.code !== 0) {
      throw new Error(res.message || "加载失败");
    }
    const items = res.data?.items ?? [];
    total = Number(res.data?.total ?? items.length);
    all.push(...items);
    if (items.length === 0 || items.length < PAGE_SIZE) break;
    page += 1;
  }
  return all;
}

/** 组内排序：priority 升序，同优先级按短语。 */
function sortItems(items: KeywordItem[]): KeywordItem[] {
  return [...items].sort((a, b) => {
    const pd = (a.priority ?? 100) - (b.priority ?? 100);
    if (pd !== 0) return pd;
    return String(a.phrase || "").localeCompare(String(b.phrase || ""), "zh");
  });
}

export default function L2KeywordsPage() {
  const { message, modal } = App.useApp();
  const [keywords, setKeywords] = useState<KeywordItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [categoryLocked, setCategoryLocked] = useState(false);
  const [testVisible, setTestVisible] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [editForm] = Form.useForm();
  const [testForm] = Form.useForm();

  useAdminPageTitle("L2 关键词规则");

  const loadKeywords = useCallback(async () => {
    setLoading(true);
    try {
      const items = await fetchAllKeywords();
      setKeywords(items);
    } catch (e) {
      console.error(e);
      message.error(e instanceof Error ? e.message : "网络错误");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadKeywords();
  }, [loadKeywords]);

  const grouped = useMemo(() => {
    const map = new Map<string, KeywordItem[]>();
    for (const c of CATEGORIES) map.set(c.value, []);
    for (const item of keywords) {
      const list = map.get(item.category);
      if (list) list.push(item);
      else {
        // 未知分类仍展示，避免丢词
        const extra = map.get(item.category) ?? [];
        extra.push(item);
        map.set(item.category, extra);
      }
    }
    for (const [k, list] of map) map.set(k, sortItems(list));
    return map;
  }, [keywords]);

  /** 打开新增：可预填并锁定分类。 */
  function openCreate(category?: string) {
    setEditingId(null);
    setCategoryLocked(Boolean(category));
    editForm.resetFields();
    editForm.setFieldsValue({
      category: category || undefined,
      match_mode: "contains",
      enabled: true,
      priority: 100,
    });
    setModalVisible(true);
  }

  /** 打开编辑。 */
  function openEdit(record: KeywordItem) {
    setEditingId(record.id);
    setCategoryLocked(false);
    editForm.setFieldsValue({
      category: record.category,
      phrase: record.phrase,
      match_mode: record.match_mode,
      enabled: record.enabled,
      priority: record.priority,
      remark: record.remark,
    });
    setModalVisible(true);
  }

  /** 关闭编辑弹窗。 */
  function closeEditModal() {
    setModalVisible(false);
    setEditingId(null);
    setCategoryLocked(false);
    editForm.resetFields();
  }

  async function handleCreate(values: Record<string, unknown>) {
    try {
      const res = await apiJson("/api/v1/intent/l2-keywords", {
        method: "POST",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("创建成功");
        closeEditModal();
        await loadKeywords();
      } else message.error(res.message || "创建失败");
    } catch {
      message.error("创建失败，请重试");
    }
  }

  async function handleUpdate(id: string, values: Record<string, unknown>) {
    try {
      const res = await apiJson(`/api/v1/intent/l2-keywords/${id}`, {
        method: "PATCH",
        body: JSON.stringify(values),
      });
      if (res.code === 0) {
        message.success("更新成功");
        closeEditModal();
        await loadKeywords();
      } else message.error(res.message || "更新失败");
    } catch {
      message.error("更新失败，请重试");
    }
  }

  /**
   * 软删短语：系统种子与自定义均可删；确认框走 App.useApp().modal。
   */
  function handleDelete(item: KeywordItem) {
    if (!isL2KeywordDeletable(item.origin)) {
      message.warning("当前短语不可删除");
      return;
    }
    modal.confirm({
      title: "确认软删该短语？",
      content:
        item.origin === "system"
          ? `系统种子「${item.phrase}」软删后可「恢复默认」找回`
          : `「${item.phrase}」`,
      okText: "删除",
      okType: "danger",
      cancelText: "取消",
      onOk: async () => {
        try {
          const res = await apiJson(`/api/v1/intent/l2-keywords/${item.id}`, {
            method: "DELETE",
          });
          if (res.code === 0) {
            message.success("已软删");
            closeEditModal();
            await loadKeywords();
          } else message.error(res.message || "删除失败");
        } catch {
          message.error("删除失败，请重试");
        }
      },
    });
  }

  async function handleReloadCache() {
    try {
      const res = await apiJson<{ phrase_count: number }>(
        "/api/v1/intent/l2-keywords/reload-cache",
        { method: "POST" },
      );
      if (res.code === 0) {
        message.success(`缓存已重载 (${res.data?.phrase_count ?? 0} 个短语)`);
      } else message.error(res.message || "重载失败");
    } catch {
      message.error("网络错误");
    }
  }

  async function handleTestRun() {
    let values: { text?: string };
    try {
      values = await testForm.validateFields();
    } catch {
      return;
    }
    setTestLoading(true);
    setTestResult(null);
    try {
      const res = await apiJson<TestResult>("/api/v1/intent/l2-keywords/test", {
        method: "POST",
        body: JSON.stringify({ text: values.text, candidates: [] }),
      });
      if (res.code === 0) setTestResult(res.data ?? null);
      else message.error(res.message || "试跑失败");
    } catch {
      message.error("网络错误，请检查后端服务");
    } finally {
      setTestLoading(false);
    }
  }

  /** 渲染单个短语 Tag；× 软删，正文点击编辑（关闭图标不打开编辑）。 */
  function renderPhraseTag(item: KeywordItem) {
    const disabled = !item.enabled;
    const deletable = isL2KeywordDeletable(item.origin);
    return (
      <Tag
        key={item.id}
        closable={deletable}
        title={
          deletable
            ? "点击文字编辑；关闭图标软删（系统种子可恢复默认）"
            : "点击编辑"
        }
        color={disabled ? undefined : "cyan"}
        style={{
          marginInlineEnd: 8,
          marginBottom: 8,
          cursor: "pointer",
          opacity: disabled ? 0.55 : 1,
          borderStyle: disabled ? "dashed" : undefined,
          color: disabled ? "var(--text-secondary)" : undefined,
        }}
        onClick={(e) => {
          const t = e.target as HTMLElement | null;
          if (t?.closest?.(".ant-tag-close-icon")) return;
          e.preventDefault();
          openEdit(item);
        }}
        onClose={(e) => {
          e.preventDefault();
          e.stopPropagation();
          window.setTimeout(() => handleDelete(item), 0);
        }}
      >
        {item.phrase}
        <span
          style={{
            marginLeft: 6,
            fontSize: 11,
            opacity: 0.75,
          }}
        >
          {matchBadge(item.match_mode)}
          {item.origin === "system" ? "·种" : ""}
        </span>
      </Tag>
    );
  }

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          gap: 8,
          marginBottom: 16,
          flexWrap: "wrap",
        }}
      >
        <Button
          icon={<ExperimentOutlined />}
          onClick={() => {
            setTestResult(null);
            testForm.resetFields();
            setTestVisible(true);
          }}
        >
          试跑
        </Button>
        <Button onClick={() => void handleReloadCache()}>重载缓存 → Redis</Button>
      </div>

      <Spin spinning={loading}>
        <Collapse
          defaultActiveKey={CATEGORIES.map((c) => c.value)}
          items={CATEGORIES.map((cat) => {
            const items = grouped.get(cat.value) ?? [];
            const enabledCount = items.filter((i) => i.enabled).length;
            return {
              key: cat.value,
              label: (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      flexWrap: "wrap",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 15, fontWeight: 600 }}>{cat.label}</span>
                      <Tag style={{ margin: 0 }}>
                        启用 {enabledCount} / 共 {items.length}
                      </Tag>
                    </div>
                    <Button
                      type="dashed"
                      size="small"
                      icon={<PlusOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        openCreate(cat.value);
                      }}
                    >
                      新增短语
                    </Button>
                  </div>
                  <span style={{ fontSize: 12, color: "var(--text-secondary)", fontWeight: 400 }}>
                    {cat.hint}
                  </span>
                </div>
              ),
              children: (
                <div style={{ minHeight: 32, paddingTop: 4 }}>
                  {items.length === 0 ? (
                    <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>
                      暂无短语，点击「新增短语」添加
                    </span>
                  ) : (
                    items.map(renderPhraseTag)
                  )}
                </div>
              ),
            };
          })}
        />
      </Spin>

      <Modal
        title={editingId ? "编辑 L2 关键词" : "新增 L2 关键词"}
        open={modalVisible}
        onCancel={closeEditModal}
        footer={(() => {
          const editing = editingId
            ? keywords.find((k) => k.id === editingId)
            : undefined;
          const canDelete = Boolean(
            editing && isL2KeywordDeletable(editing.origin),
          );
          return [
            editingId && canDelete ? (
              <Button
                key="delete"
                danger
                onClick={() => {
                  if (editing) handleDelete(editing);
                }}
              >
                删除
              </Button>
            ) : null,
            <Button key="cancel" onClick={closeEditModal}>
              取消
            </Button>,
            <Button key="confirm" type="primary" onClick={() => editForm.submit()}>
              保存
            </Button>,
          ];
        })()}
        destroyOnClose
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(values) => {
            if (editingId) void handleUpdate(editingId, values);
            else void handleCreate(values);
          }}
        >
          {editingId &&
            keywords.find((k) => k.id === editingId)?.origin === "system" && (
              <p
                style={{
                  marginTop: 0,
                  marginBottom: 12,
                  fontSize: 13,
                  color: "var(--text-secondary)",
                }}
              >
                系统种子可软删；需要找回时用「恢复默认」按出厂词表重建。
              </p>
            )}
          <Form.Item
            name="category"
            label="分类"
            rules={[{ required: true }]}
            extra={
              categoryLocked
                ? "已锁定为当前分类"
                : "请按意图用途选择分类（界面显示中文名）；短泛化词慎用「包含」"
            }
          >
            <Select
              options={CATEGORIES.map((c) => ({
                value: c.value,
                label: c.label,
              }))}
              disabled={categoryLocked}
            />
          </Form.Item>
          <Form.Item
            name="phrase"
            label="短语原文"
            rules={[{ required: true, min: 1, max: 128 }]}
          >
            <Input placeholder="如：请假、别总结" />
          </Form.Item>
          <Form.Item
            name="match_mode"
            label="匹配模式"
            initialValue="contains"
            rules={[{ required: true }]}
          >
            <Select options={MATCH_MODES} />
          </Form.Item>
          <Form.Item
            name="enabled"
            label="启用"
            valuePropName="checked"
            initialValue={true}
          >
            <Checkbox>启用该短语</Checkbox>
          </Form.Item>
          <Form.Item name="priority" label="排序优先级" initialValue={100}>
            <InputNumber min={1} max={1000} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} placeholder="内部备注（可选）" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="L2 规则服务端真实试跑（无副作用）"
        open={testVisible}
        width={720}
        onCancel={() => {
          setTestVisible(false);
          setTestResult(null);
        }}
        footer={[
          <Button
            key="back"
            onClick={() => {
              setTestVisible(false);
              setTestResult(null);
            }}
          >
            返回
          </Button>,
          <Button
            key="confirm"
            type="primary"
            loading={testLoading}
            onClick={() => void handleTestRun()}
          >
            开始试跑
          </Button>,
        ]}
        destroyOnClose
      >
        <Form form={testForm} layout="vertical">
          <Form.Item
            name="text"
            label="输入测试语句"
            rules={[{ required: true, min: 1, max: 512 }]}
          >
            <Input.TextArea
              rows={4}
              placeholder="例如：帮我总结赵世龙的简历"
            />
          </Form.Item>
        </Form>
        {testResult && (
          <div
            style={{
              marginTop: 12,
              padding: 15,
              background: "var(--bg-muted, #f5f5f5)",
              borderRadius: 6,
            }}
          >
            <h4 style={{ margin: "0 0 10px 0" }}>试跑结果：</h4>
            {testResult.matched ? (
              <Space direction="vertical" size={4}>
                <p style={{ margin: 0 }}>
                  <strong>命中层级：</strong>
                  {testResult.layer}
                </p>
                <p style={{ margin: 0 }}>
                  <strong>候选意图：</strong>
                  {testResult.match?.candidate_intent || testResult.intent || "—"}
                </p>
                <p style={{ margin: 0 }}>
                  <strong>门槛后意图：</strong>
                  {testResult.intent}
                </p>
                <p style={{ margin: 0 }}>
                  <strong>门槛：</strong>
                  {testResult.gate_action || "—"}
                  {testResult.gate_reason ? `（${testResult.gate_reason}）` : ""}
                </p>
                <p style={{ margin: 0 }}>
                  <strong>是否短路：</strong>
                  {testResult.would_short_circuit ? "是" : "否"}
                  {testResult.clarify_kind
                    ? ` → 澄清 ${testResult.clarify_kind}`
                    : ""}
                </p>
                <p style={{ margin: 0 }}>
                  <strong>置信度：</strong>
                  {((testResult.confidence ?? 0) * 100).toFixed(1)}%
                </p>
                <p style={{ margin: 0 }}>
                  <strong>命中短语：</strong>
                  {testResult.match?.phrase || "-"}
                </p>
                <p style={{ margin: 0 }}>
                  <strong>原因：</strong>
                  {testResult.reason || "—"}
                </p>
                <p style={{ margin: 0, opacity: 0.75, fontSize: 12 }}>
                  试跑无会话文档检索上下文；文档类门槛按「未解析」预测澄清，与生产可能略有差异。
                </p>
              </Space>
            ) : (
              <p style={{ margin: 0 }}>
                <strong>L2 未命中，将继续进入 L3（LLM 分类器）。</strong>
              </p>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
