/**
 * 知识库详情：文档检索列表 + 上传入库弹窗（分类联动 + 切块模式）。
 * @author 赵振明
 * @date 2026-11-20 16:06:00
 */
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { UploadFile } from "antd/es/upload/interface";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";

const { Title, Paragraph, Text } = Typography;

type ChunkMode = "auto" | "coarse" | "balanced" | "fine" | "custom";

type ChunkProfile = {
  mode: string;
  resolved_mode?: string;
  char_count: number;
  parent_size: number;
  child_size: number;
  overlap: number;
  est_parent_count: number;
  est_child_count: number;
};

type KbItem = {
  id: string;
  name: string;
  visibility: string;
  owner_department_id?: string | null;
};

type DocItem = {
  id: string;
  title: string;
  status: string;
  hit_rate?: number | null;
  qa_count?: number;
  stage?: string | null;
  deleted_at?: string | null;
};

type CatItem = {
  id: string;
  code: string;
  name: string;
  parent_id?: string | null;
  schema_code?: string | null;
  enabled?: boolean;
};

/**
 * 文件转 base64（去掉 data URL 前缀）。
 */
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",")[1] : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/**
 * 估算文件字符量：文本类按解码长度，二进制按体积近似。
 */
async function estimateFileChars(file: File): Promise<number> {
  const name = (file.name || "").toLowerCase();
  const isText =
    name.endsWith(".txt") ||
    name.endsWith(".md") ||
    name.endsWith(".json") ||
    name.endsWith(".csv");
  if (isText) {
    const text = await file.text();
    return text.length;
  }
  // pdf/docx/xlsx：体积近似字符（偏保守，避免估太短导致切块过碎）
  return Math.max(800, Math.round(file.size * 0.55));
}

/**
 * 文档状态展示文案。
 */
function statusLabel(doc: DocItem): string {
  if (doc.deleted_at) return "已软删";
  if (doc.status === "processing" && doc.stage) return `入库中 · ${doc.stage}`;
  const map: Record<string, string> = {
    processing: "入库中",
    pending_review: "待审切块",
    ready: "已确认",
    failed: "失败",
    published: "已发布",
    draft: "草稿",
  };
  return map[doc.status] || doc.status;
}

export default function KnowledgeDetailPage() {
  useAdminPageTitle("知识库详情");
  const { message } = App.useApp();
  const params = useParams();
  const kbId = String(params?.kb_id || "");

  const [kb, setKb] = useState<KbItem | null>(null);
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [cats, setCats] = useState<CatItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [level1Id, setLevel1Id] = useState<string | undefined>();
  const [level2Id, setLevel2Id] = useState<string | undefined>();
  const [chunkMode, setChunkMode] = useState<ChunkMode>("auto");
  const [charHint, setCharHint] = useState(0);
  const [chunkProfile, setChunkProfile] = useState<ChunkProfile | null>(null);
  const [parentSize, setParentSize] = useState(1400);
  const [childSize, setChildSize] = useState(550);
  const [chunkOverlap, setChunkOverlap] = useState(80);
  const [form] = Form.useForm();

  /** 一级：根分类（parent 为空）。 */
  const level1Options = useMemo(
    () =>
      cats
        .filter((c) => !c.parent_id)
        .map((c) => ({ value: c.id, label: c.name })),
    [cats],
  );

  /** 二级：选中一级下的子分类。 */
  const level2Options = useMemo(() => {
    if (!level1Id) return [];
    return cats
      .filter((c) => c.parent_id === level1Id)
      .map((c) => ({ value: c.id, label: c.name }));
  }, [cats, level1Id]);

  /** 一级自身是否可挂文档（有 schema 且无子节点）。 */
  const level1IsLeaf = useMemo(() => {
    if (!level1Id) return false;
    const row = cats.find((c) => c.id === level1Id);
    if (!row?.schema_code) return false;
    return !cats.some((c) => c.parent_id === level1Id);
  }, [cats, level1Id]);

  const filteredDocs = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return docs;
    return docs.filter(
      (d) =>
        d.title.toLowerCase().includes(q) ||
        d.id.toLowerCase().includes(q) ||
        (d.status || "").toLowerCase().includes(q),
    );
  }, [docs, keyword]);

  const loadKbMeta = useCallback(async () => {
    const res = await apiJson<{ items: KbItem[] }>("/api/v1/knowledge-bases");
    if (res.code !== 0) throw new Error(res.message || "加载知识库失败");
    const found = (res.data?.items || []).find((k) => k.id === kbId) || null;
    setKb(found);
    if (!found) throw new Error("知识库不存在或无权访问");
  }, [kbId]);

  const loadDocs = useCallback(async () => {
    if (!kbId) return;
    const res = await apiJson<{ items: DocItem[] }>(
      `/api/v1/documents?kb_id=${encodeURIComponent(kbId)}&include_deleted=1`,
    );
    if (res.code !== 0) throw new Error(res.message || "加载文档失败");
    setDocs(res.data?.items || []);
  }, [kbId]);

  const loadCats = useCallback(async () => {
    const res = await apiJson<{ items: CatItem[] }>("/api/v1/doc-categories");
    if (res.code !== 0) throw new Error(res.message || "加载分类失败");
    setCats(res.data?.items || []);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([loadKbMeta(), loadDocs(), loadCats()]);
    } catch (err) {
      message.error((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [loadKbMeta, loadDocs, loadCats, message]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const processing = docs.filter(
      (d) => d.status === "processing" && !d.deleted_at,
    );
    if (!processing.length) return;
    const t = setInterval(() => {
      void loadDocs();
    }, 2000);
    return () => clearInterval(t);
  }, [docs, loadDocs]);

  /**
   * 按模式/字符数向后端取推荐切块尺寸。
   */
  const refreshChunkProfile = useCallback(
    async (opts: {
      chars: number;
      mode: ChunkMode;
      parent?: number;
      child?: number;
      overlap?: number;
    }) => {
      try {
        const res = await apiJson<ChunkProfile>(
          "/api/v1/documents/chunk-recommend",
          {
            method: "POST",
            body: JSON.stringify({
              char_count: opts.chars,
              mode: opts.mode,
              parent_size: opts.mode === "custom" ? opts.parent : undefined,
              child_size: opts.mode === "custom" ? opts.child : undefined,
              overlap: opts.mode === "custom" ? opts.overlap : undefined,
            }),
          },
        );
        if (res.code !== 0 || !res.data) return;
        setChunkProfile(res.data);
        if (opts.mode !== "custom") {
          setParentSize(res.data.parent_size);
          setChildSize(res.data.child_size);
          setChunkOverlap(res.data.overlap);
        }
      } catch {
        /* 推荐失败不阻断上传 */
      }
    },
    [],
  );

  /**
   * 打开入库弹窗并重置表单。
   */
  function openUploadModal() {
    form.resetFields();
    setFileList([]);
    setLevel1Id(undefined);
    setLevel2Id(undefined);
    setChunkMode("auto");
    setCharHint(0);
    setChunkProfile(null);
    setParentSize(1400);
    setChildSize(550);
    setChunkOverlap(80);
    const defaultL1 =
      cats.find((c) => !c.parent_id && c.code === "hr")?.id ||
      cats.find((c) => !c.parent_id)?.id;
    if (defaultL1) {
      setLevel1Id(defaultL1);
      const children = cats.filter((c) => c.parent_id === defaultL1);
      const prefer =
        children.find((c) => c.code === "hr.resume")?.id || children[0]?.id;
      setLevel2Id(prefer);
      form.setFieldsValue({
        level1_id: defaultL1,
        level2_id: prefer,
        title: undefined,
      });
    }
    setUploadOpen(true);
  }

  /**
   * 选文件后估算长度并拉取推荐。
   */
  async function onFileChange(fl: UploadFile[]) {
    setFileList(fl);
    const raw = fl[0]?.originFileObj as File | undefined;
    if (!raw) {
      setCharHint(0);
      setChunkProfile(null);
      return;
    }
    const chars = await estimateFileChars(raw);
    setCharHint(chars);
    await refreshChunkProfile({
      chars,
      mode: chunkMode,
      parent: parentSize,
      child: childSize,
      overlap: chunkOverlap,
    });
  }

  /**
   * 切换切块模式并刷新推荐。
   */
  async function onChunkModeChange(mode: ChunkMode) {
    setChunkMode(mode);
    await refreshChunkProfile({
      chars: charHint,
      mode,
      parent: parentSize,
      child: childSize,
      overlap: chunkOverlap,
    });
  }

  /**
   * 一级变更：清空二级并默认选第一个子节点。
   */
  function onLevel1Change(id: string) {
    setLevel1Id(id);
    const children = cats.filter((c) => c.parent_id === id);
    const next = children[0]?.id;
    setLevel2Id(next);
    form.setFieldsValue({ level1_id: id, level2_id: next });
  }

  /**
   * 解析当前选中的挂载分类（优先二级，一级叶子则用一级）。
   */
  function resolveCategoryId(): string | null {
    if (level2Id) return level2Id;
    if (level1IsLeaf && level1Id) return level1Id;
    return null;
  }

  async function onUpload(values: { title?: string }) {
    const raw = fileList[0]?.originFileObj as File | undefined;
    if (!raw) {
      message.error("请选择文件");
      return;
    }
    const categoryId = resolveCategoryId();
    if (!categoryId) {
      message.error(
        level2Options.length > 0 ? "请选择二级分类" : "请选择分类",
      );
      return;
    }
    if (chunkMode === "custom" && childSize >= parentSize) {
      message.error("子块尺寸须小于父块尺寸");
      return;
    }
    setBusy(true);
    try {
      const content_b64 = await fileToBase64(raw);
      const res = await apiJson<{ document_id: string; status: string }>(
        "/api/v1/documents/upload",
        {
          method: "POST",
          body: JSON.stringify({
            kb_id: kbId,
            title: (values.title || "").trim() || raw.name,
            filename: raw.name,
            content_b64,
            category_ids: [categoryId],
            primary_category_id: categoryId,
            chunk_mode: chunkMode,
            parent_size: parentSize,
            child_size: childSize,
            chunk_overlap: chunkOverlap,
            char_count_hint: charHint,
          }),
        },
      );
      if (res.code !== 0) {
        message.error(res.message || "上传失败");
        return;
      }
      message.success(`已上传 ${res.data?.document_id}（${res.data?.status}）`);
      setUploadOpen(false);
      setFileList([]);
      await loadDocs();
    } catch (err) {
      message.error(`上传失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onPublish(docId: string) {
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(docId)}/publish`,
        { method: "POST", body: "{}" },
      );
      if (res.code !== 0) {
        message.error(res.message || "发布失败");
        return;
      }
      message.success("已发布");
      await loadDocs();
    } catch (err) {
      message.error(`发布失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteDoc(docId: string) {
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(docId)}`,
        { method: "DELETE" },
      );
      if (res.code !== 0) {
        message.error(res.message || "删除失败");
        return;
      }
      message.success("已软删");
      await loadDocs();
    } catch (err) {
      message.error(`删除失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const columns: ColumnsType<DocItem> = [
    {
      title: "标题",
      dataIndex: "title",
      render: (title: string, row) => (
        <Link
          href={`/knowledge/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(row.id)}`}
        >
          {title}
        </Link>
      ),
    },
    {
      title: "状态",
      key: "status",
      width: 140,
      render: (_, row) => <Tag>{statusLabel(row)}</Tag>,
    },
    {
      title: "召回率",
      dataIndex: "hit_rate",
      width: 100,
      render: (v?: number | null) =>
        v == null ? "—" : `${(Number(v) * 100).toFixed(1)}%`,
    },
    {
      title: "QA",
      dataIndex: "qa_count",
      width: 70,
      render: (n?: number) => n ?? 0,
    },
    {
      title: "操作",
      key: "actions",
      width: 260,
      render: (_, row) => (
        <Space wrap size="small">
          <Link
            href={`/knowledge/${encodeURIComponent(kbId)}/documents/${encodeURIComponent(row.id)}`}
          >
            <Button type="link" size="small">
              详情/切块
            </Button>
          </Link>
          {!row.deleted_at && row.status === "ready" ? (
            <Button
              type="link"
              size="small"
              disabled={busy}
              onClick={() => void onPublish(row.id)}
            >
              发布
            </Button>
          ) : null}
          {!row.deleted_at ? (
            <Popconfirm
              title="确认软删该文档？"
              onConfirm={() => void onDeleteDoc(row.id)}
            >
              <Button type="link" size="small" danger disabled={busy}>
                删除
              </Button>
            </Popconfirm>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 20 }}>
      <Space
        style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}
        align="start"
      >
        <div>
          <Title level={3} style={{ margin: 0 }}>
            {kb?.name || "知识库详情"}
          </Title>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            ID：<Text code>{kbId}</Text>
            {kb ? (
              <>
                {" · "}
                {kb.visibility === "public" ? "公司公开" : "部门私有"}
              </>
            ) : null}
          </Paragraph>
        </div>
        <Space>
          <Link href={`/knowledge/${encodeURIComponent(kbId)}/permissions`}>
            <Button>权限</Button>
          </Link>
          <Link href="/knowledge">
            <Button>返回列表</Button>
          </Link>
        </Space>
      </Space>

      <Space
        style={{
          width: "100%",
          justifyContent: "space-between",
          marginBottom: 16,
          flexWrap: "wrap",
          rowGap: 8,
        }}
      >
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: "rgba(0,0,0,0.45)" }} />}
          placeholder="搜索文档标题 / ID / 状态"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          style={{ width: 320, maxWidth: "100%" }}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openUploadModal}>
          上传文档
        </Button>
      </Space>

      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={filteredDocs}
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 条` }}
      />

      <Modal
        title="入库内容"
        open={uploadOpen}
        onCancel={() => setUploadOpen(false)}
        onOk={() => form.submit()}
        okText="确认入库"
        confirmLoading={busy}
        destroyOnClose
        width={640}
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 8 }}
          onFinish={(v) => void onUpload(v)}
        >
          <Form.Item name="title" label="标题">
            <Input placeholder="默认使用文件名" maxLength={200} />
          </Form.Item>

          <Form.Item
            name="level1_id"
            label="一级分类"
            rules={[{ required: true, message: "请选择一级分类" }]}
          >
            <Select
              placeholder="请选择"
              options={level1Options}
              value={level1Id}
              onChange={onLevel1Change}
            />
          </Form.Item>

          {level1IsLeaf ? (
            <Paragraph type="secondary" style={{ marginTop: -8 }}>
              该一级分类可直接挂载文档，无需二级。
            </Paragraph>
          ) : (
            <Form.Item
              name="level2_id"
              label="二级分类"
              rules={[
                {
                  required: level2Options.length > 0,
                  message: "请选择二级分类",
                },
              ]}
            >
              <Select
                placeholder={
                  level1Id ? "请选择二级分类" : "请先选择一级分类"
                }
                options={level2Options}
                value={level2Id}
                disabled={!level1Id || level2Options.length === 0}
                onChange={(id: string) => {
                  setLevel2Id(id);
                  form.setFieldsValue({ level2_id: id });
                }}
              />
            </Form.Item>
          )}

          <Form.Item label="文件" required>
            <Upload
              beforeUpload={() => false}
              maxCount={1}
              fileList={fileList}
              onChange={({ fileList: fl }) => void onFileChange(fl)}
              accept=".pdf,.txt,.md,.json,.docx,.xlsx"
            >
              <Button>选择文件</Button>
            </Upload>
            <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
              支持 pdf / txt / md / json / docx / xlsx
              {charHint > 0 ? ` · 估算约 ${charHint.toLocaleString()} 字` : ""}
            </Text>
          </Form.Item>

          <Form.Item label="切块模式" required>
            <Radio.Group
              value={chunkMode}
              onChange={(e) => void onChunkModeChange(e.target.value)}
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: "auto", label: "智能推荐" },
                { value: "coarse", label: "粗粒度" },
                { value: "balanced", label: "均衡" },
                { value: "fine", label: "细粒度" },
                { value: "custom", label: "自定义" },
              ]}
            />
            <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
              子块过碎会稀释检索；推荐按文档长短自动放大父/子块窗口。可再手动微调。
            </Paragraph>
          </Form.Item>

          <Space wrap size="middle" style={{ width: "100%", marginBottom: 8 }}>
            <div>
              <Text type="secondary">父块尺寸</Text>
              <InputNumber
                min={200}
                max={8000}
                step={100}
                value={parentSize}
                style={{ width: 120, display: "block" }}
                onChange={(v) => {
                  const next = typeof v === "number" ? v : parentSize;
                  setParentSize(next);
                  setChunkMode("custom");
                  void refreshChunkProfile({
                    chars: charHint,
                    mode: "custom",
                    parent: next,
                    child: childSize,
                    overlap: chunkOverlap,
                  });
                }}
              />
            </div>
            <div>
              <Text type="secondary">子块尺寸</Text>
              <InputNumber
                min={80}
                max={4000}
                step={50}
                value={childSize}
                style={{ width: 120, display: "block" }}
                onChange={(v) => {
                  const next = typeof v === "number" ? v : childSize;
                  setChildSize(next);
                  setChunkMode("custom");
                  void refreshChunkProfile({
                    chars: charHint,
                    mode: "custom",
                    parent: parentSize,
                    child: next,
                    overlap: chunkOverlap,
                  });
                }}
              />
            </div>
            <div>
              <Text type="secondary">重叠</Text>
              <InputNumber
                min={0}
                max={2000}
                step={10}
                value={chunkOverlap}
                style={{ width: 100, display: "block" }}
                onChange={(v) => {
                  const next = typeof v === "number" ? v : chunkOverlap;
                  setChunkOverlap(next);
                  setChunkMode("custom");
                  void refreshChunkProfile({
                    chars: charHint,
                    mode: "custom",
                    parent: parentSize,
                    child: childSize,
                    overlap: next,
                  });
                }}
              />
            </div>
          </Space>

          {chunkProfile ? (
            <Paragraph style={{ marginBottom: 0 }}>
              <Tag color="blue">
                约 {chunkProfile.est_parent_count} 个父块
              </Tag>
              <Tag color="green">
                约 {chunkProfile.est_child_count} 个可检索子块
              </Tag>
              <Text type="secondary">
                （父 {chunkProfile.parent_size} / 子 {chunkProfile.child_size} /
                重叠 {chunkProfile.overlap}）
              </Text>
            </Paragraph>
          ) : (
            <Text type="secondary">选择文件后显示推荐块数</Text>
          )}
        </Form>
      </Modal>
    </div>
  );
}
