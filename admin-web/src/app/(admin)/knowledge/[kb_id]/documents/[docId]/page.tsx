/**
 * 文档详情：闸门清单 + Steps/四 Tab（切块/评测/发布/版本）+ 原始文件预览。
 * @author 赵振明
 * @date 2026-11-25 10:26:45
 */
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Input,
  Space,
  Steps,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { EyeOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useAdminPageTitle } from "@/components/AdminTitle";
import { apiJson } from "@/lib/api";
import { ChunkWorkbench } from "../../../_components/ChunkWorkbench";
import {
  OriginalFilePreview,
  type PreviewKind,
} from "../../../_components/OriginalFilePreview";

const { Title, Paragraph, Text } = Typography;

type HitDetail = {
  question: string;
  expected_chunk_hint?: string | null;
  hit: boolean;
  reason?: string;
  hint_in_document?: boolean;
  top_contents?: string[];
};

type LastHitTest = {
  hit_rate?: number;
  hits?: number;
  total?: number;
  details?: HitDetail[];
};

type DocStatus = {
  status?: string;
  hit_rate?: number | null;
  qa_count?: number;
  stage?: string | null;
  reason?: string | null;
  last_hit_test?: LastHitTest | null;
  title?: string;
  filename?: string;
  ext?: string;
  preview_kind?: PreviewKind;
};

type QaItem = {
  question: string;
  expected_chunk_hint?: string | null;
};

type TabKey = "chunks" | "qa" | "publish" | "versions";

/**
 * 命中原因业务文案。
 */
function reasonLabel(reason?: string): string {
  if (reason === "hit") return "已命中";
  if (reason === "hint_not_in_doc") return "期望句不在原文";
  if (reason === "not_in_top_k") return "检索未排进前几";
  return reason || "—";
}

/**
 * 按文档状态推断默认 Tab。
 */
function defaultTab(info: DocStatus): TabKey {
  const st = info.status || "";
  const qaOk = (info.qa_count || 0) >= 5;
  const hitOk = info.hit_rate != null && Number(info.hit_rate) >= 0.8;
  const chunkOk = st === "ready" || st === "published";
  if (st === "pending_review" || st === "processing" || st === "draft") {
    return "chunks";
  }
  if (chunkOk && qaOk && hitOk) return "publish";
  if (chunkOk) return "qa";
  return "chunks";
}

export default function KnowledgeDocumentPage() {
  useAdminPageTitle("文档详情");
  const { message } = App.useApp();
  const params = useParams();
  const kbId = String(params?.kb_id || "");
  const docId = String(params?.docId || "");
  const [info, setInfo] = useState<DocStatus>({});
  const [qaItems, setQaItems] = useState<QaItem[]>([{ question: "" }]);
  const [hitDetails, setHitDetails] = useState<HitDetail[]>([]);
  const [rowHitMap, setRowHitMap] = useState<Record<number, HitDetail>>({});
  const [versions, setVersions] = useState<
    { id: string; version_no: number; title: string; created_at?: string | null }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [testingRow, setTestingRow] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("chunks");
  const [tabInited, setTabInited] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  const hitByQuestion = useMemo(() => {
    const map = new Map<string, HitDetail>();
    for (const d of hitDetails) {
      map.set((d.question || "").trim(), d);
    }
    return map;
  }, [hitDetails]);

  const chunkOk =
    info.status === "ready" || info.status === "published";
  const qaOk = (info.qa_count || 0) >= 5;
  const hitOk = info.hit_rate != null && Number(info.hit_rate) >= 0.8;
  const canPublish = chunkOk && qaOk && hitOk && info.status !== "published";

  const stepCurrent = useMemo(() => {
    if (!chunkOk) return 0;
    if (!(qaOk && hitOk)) return 1;
    return 2;
  }, [chunkOk, qaOk, hitOk]);

  const loadStatus = useCallback(async () => {
    const res = await apiJson<DocStatus>(
      `/api/v1/documents/${encodeURIComponent(docId)}/status`,
    );
    if (res.code !== 0) throw new Error(res.message || "加载状态失败");
    const data = res.data || {};
    setInfo(data);
    if (data.last_hit_test?.details?.length) {
      setHitDetails(data.last_hit_test.details);
    }
    return data;
  }, [docId]);

  const loadQa = useCallback(async () => {
    const res = await apiJson<{ items: QaItem[] }>(
      `/api/v1/documents/${encodeURIComponent(docId)}/qa-pairs`,
    );
    if (res.code !== 0) throw new Error(res.message || "加载问答失败");
    const items = res.data?.items || [];
    setQaItems(items.length ? items : [{ question: "" }]);
  }, [docId]);

  const loadVersions = useCallback(async () => {
    const res = await apiJson<{
      items: { id: string; version_no: number; title: string; created_at?: string | null }[];
    }>(`/api/v1/documents/${encodeURIComponent(docId)}/versions`);
    if (res.code !== 0) throw new Error(res.message || "加载版本失败");
    setVersions(res.data?.items || []);
  }, [docId]);

  const refresh = useCallback(async () => {
    try {
      const data = await loadStatus();
      await Promise.all([loadQa(), loadVersions()]);
      if (!tabInited) {
        setActiveTab(defaultTab(data || {}));
        setTabInited(true);
      }
    } catch (err) {
      message.error((err as Error).message);
    }
  }, [loadStatus, loadQa, loadVersions, message, tabInited]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  /**
   * 应用整表命中结果。
   */
  function applyHitResult(data?: {
    hit_rate?: number;
    hits?: number;
    total?: number;
    details?: HitDetail[];
  } | null) {
    if (!data) return;
    if (data.details?.length) {
      setHitDetails(data.details);
      setRowHitMap({});
    }
    const rate = Number(data.hit_rate ?? 0);
    const hits = data.hits ?? 0;
    const total = data.total ?? 0;
    const pct = (rate * 100).toFixed(1);
    if (rate >= 0.8) {
      message.success(`召回率 ${pct}%（${hits}/${total}），可达发布门槛`);
    } else {
      message.warning(`召回率 ${pct}%（${hits}/${total}），未达 80%`);
    }
  }

  async function onGenerateQa() {
    setBusy(true);
    try {
      const res = await apiJson<{
        qa_count: number;
        hit_rate?: number | null;
        hit_test?: {
          hit_rate?: number;
          hits?: number;
          total?: number;
          details?: HitDetail[];
        };
      }>(
        `/api/v1/documents/${encodeURIComponent(docId)}/generate-qa?run_hit_test=1`,
        { method: "POST", body: "{}" },
      );
      if (res.code !== 0) {
        message.error(res.message || "生成失败");
        return;
      }
      message.success(`已生成 ${res.data?.qa_count ?? 0} 条问答`);
      applyHitResult(
        res.data?.hit_test || { hit_rate: res.data?.hit_rate ?? undefined },
      );
      await refresh();
    } catch (err) {
      message.error(`生成失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onSaveQa() {
    const items = qaItems
      .map((q) => ({
        question: q.question.trim(),
        expected_chunk_hint: (q.expected_chunk_hint || "").trim() || null,
      }))
      .filter((q) => q.question);
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(docId)}/qa-pairs`,
        { method: "PUT", body: JSON.stringify({ items }) },
      );
      if (res.code !== 0) {
        message.error(res.message || "保存失败");
        return;
      }
      message.success("已保存；请点「重测全部」更新召回率");
      setHitDetails([]);
      setRowHitMap({});
      await refresh();
    } catch (err) {
      message.error(`保存失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onHitTest() {
    setBusy(true);
    try {
      const res = await apiJson<{
        hit_rate: number;
        hits: number;
        total: number;
        details?: HitDetail[];
      }>(
        `/api/v1/documents/${encodeURIComponent(docId)}/hit-test`,
        { method: "POST", body: "{}" },
      );
      if (res.code !== 0) {
        message.error(res.message || "命中测试失败");
        return;
      }
      applyHitResult(res.data);
      await loadStatus();
    } catch (err) {
      message.error(`命中测试失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  /**
   * 单条命中：用当前行未保存内容；不改整文档召回率。
   */
  async function onHitTestOne(idx: number) {
    const row = qaItems[idx];
    const question = (row?.question || "").trim();
    if (!question) {
      message.error("请先填写问题");
      return;
    }
    setTestingRow(idx);
    try {
      const res = await apiJson<HitDetail>(
        `/api/v1/documents/${encodeURIComponent(docId)}/hit-test/one`,
        {
          method: "POST",
          body: JSON.stringify({
            question,
            expected_chunk_hint: (row.expected_chunk_hint || "").trim() || null,
          }),
        },
      );
      if (res.code !== 0 || !res.data) {
        message.error(res.message || "单条测试失败");
        return;
      }
      setRowHitMap((prev) => ({ ...prev, [idx]: res.data as HitDetail }));
      message[res.data.hit ? "success" : "warning"](
        res.data.hit ? "本条命中" : `本条未命中：${reasonLabel(res.data.reason)}`,
      );
    } catch (err) {
      message.error(`单条测试失败：${(err as Error).message}`);
    } finally {
      setTestingRow(null);
    }
  }

  async function onPublish() {
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
      await loadStatus();
    } catch (err) {
      message.error(`发布失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onRollback(versionId: string) {
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(docId)}/versions/${encodeURIComponent(versionId)}/rollback`,
        { method: "POST", body: "{}" },
      );
      if (res.code !== 0) {
        message.error(res.message || "回滚失败");
        return;
      }
      message.success("已回滚并重新入库");
      setTabInited(false);
      await refresh();
    } catch (err) {
      message.error(`回滚失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  /**
   * 行命中态：优先单条测结果，否则用整表明细。
   */
  function detailForRow(row: QaItem, idx: number): HitDetail | undefined {
    if (rowHitMap[idx]) return rowHitMap[idx];
    return hitByQuestion.get((row.question || "").trim());
  }

  const qaColumns: ColumnsType<QaItem & { key: number }> = [
    {
      title: "命中",
      key: "hit",
      width: 130,
      fixed: "left",
      render: (_v, row, idx) => {
        const detail = detailForRow(row, idx);
        if (!detail) return <Tag>未测</Tag>;
        if (detail.hit) return <Tag color="success">命中</Tag>;
        return (
          <Space direction="vertical" size={0}>
            <Tag color="error">未命中</Tag>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {reasonLabel(detail.reason)}
            </Text>
          </Space>
        );
      },
    },
    {
      title: "问题",
      dataIndex: "question",
      render: (v, _r, idx) => (
        <Input
          value={v}
          onChange={(e) => {
            const nv = e.target.value;
            setQaItems((prev) =>
              prev.map((p, i) => (i === idx ? { ...p, question: nv } : p)),
            );
          }}
        />
      ),
    },
    {
      title: "期望原文句",
      dataIndex: "expected_chunk_hint",
      width: 280,
      render: (v, _r, idx) => (
        <Input.TextArea
          autoSize={{ minRows: 1, maxRows: 3 }}
          placeholder="须为切块中连续出现的原句"
          value={v || ""}
          onChange={(e) => {
            const nv = e.target.value;
            setQaItems((prev) =>
              prev.map((p, i) =>
                i === idx ? { ...p, expected_chunk_hint: nv } : p,
              ),
            );
          }}
        />
      ),
    },
    {
      title: "操作",
      key: "ops",
      width: 100,
      render: (_v, _r, idx) => (
        <Button
          size="small"
          loading={testingRow === idx}
          disabled={busy || testingRow !== null}
          onClick={() => void onHitTestOne(idx)}
        >
          测本条
        </Button>
      ),
    },
    {
      title: "召回预览",
      key: "top",
      width: 240,
      render: (_v, row, idx) => {
        const detail = detailForRow(row, idx);
        const tops = detail?.top_contents || [];
        if (!tops.length) return <Text type="secondary">—</Text>;
        return (
          <Paragraph
            type="secondary"
            ellipsis={{ rows: 2, tooltip: tops.join("\n---\n") }}
            style={{ marginBottom: 0, fontSize: 12 }}
          >
            {tops[0]}
          </Paragraph>
        );
      },
    },
  ];

  const gateCard = (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Space wrap size={[12, 8]}>
        <Text strong>发布条件</Text>
        <Tag color={chunkOk ? "success" : "default"}>
          {chunkOk ? "✓" : "○"} 切块已确认
        </Tag>
        <Tag color={qaOk ? "success" : "default"}>
          {qaOk ? "✓" : "○"} 问答 ≥ 5（当前 {info.qa_count ?? 0}）
        </Tag>
        <Tag color={hitOk ? "success" : "default"}>
          {hitOk ? "✓" : "○"} 召回率 ≥ 80%
          {info.hit_rate == null
            ? "（未测）"
            : `（${(Number(info.hit_rate) * 100).toFixed(1)}%` +
              (info.last_hit_test?.hits != null &&
              info.last_hit_test?.total != null
                ? `，${info.last_hit_test.hits}/${info.last_hit_test.total}`
                : "") +
              "）"}
        </Tag>
        {info.status === "published" ? <Tag color="blue">已发布</Tag> : null}
      </Space>
    </Card>
  );

  return (
    <div style={{ padding: 20 }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Title level={3} style={{ margin: 0 }}>
          文档详情
          {info.title ? (
            <Text type="secondary" style={{ fontSize: 16, marginLeft: 12 }}>
              {info.title}
            </Text>
          ) : null}
        </Title>
        <Space>
          <Button
            type="primary"
            ghost
            icon={<EyeOutlined />}
            onClick={() => setPreviewOpen(true)}
          >
            预览原始文件
          </Button>
          <Link href={`/knowledge/${encodeURIComponent(kbId)}`}>
            <Button>返回知识库</Button>
          </Link>
        </Space>
      </Space>

      <Descriptions
        bordered
        size="small"
        column={2}
        style={{ maxWidth: 960, margin: "16px 0" }}
      >
        <Descriptions.Item label="文档 ID">{docId}</Descriptions.Item>
        <Descriptions.Item label="知识库">{kbId}</Descriptions.Item>
        <Descriptions.Item label="文件">
          {info.filename || info.title || "—"}
          {info.ext ? `（${info.ext}）` : ""}
        </Descriptions.Item>
        <Descriptions.Item label="状态">{info.status || "—"}</Descriptions.Item>
        <Descriptions.Item label="阶段">{info.stage || "—"}</Descriptions.Item>
      </Descriptions>

      <OriginalFilePreview
        open={previewOpen}
        documentId={docId}
        meta={{
          title: info.title,
          filename: info.filename,
          ext: info.ext,
          preview_kind: info.preview_kind,
        }}
        onClose={() => setPreviewOpen(false)}
      />

      {gateCard}

      <Steps
        size="small"
        current={stepCurrent}
        style={{ maxWidth: 720, marginBottom: 20 }}
        items={[
          { title: "切块审阅" },
          { title: "质量评测" },
          { title: "发布" },
        ]}
      />

      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as TabKey)}
        items={[
          {
            key: "chunks",
            label: "① 切块审阅",
            children: (
              <div>
                <Paragraph type="secondary">
                  先确认切块（含子块嵌入）。父块摘要可在后台生成，不影响本步主流程。
                </Paragraph>
                <ChunkWorkbench
                  documentId={docId}
                  docStatus={info.status || ""}
                  onStatusChange={() => void loadStatus()}
                />
              </div>
            ),
          },
          {
            key: "qa",
            label: "② 质量评测",
            children: (
              <div>
                <Paragraph type="secondary">
                  用问答检查「搜不搜得到」。可一键生成并测评；也可改单条后点「测本条」（无需先保存）。
                  发布看的是「重测全部」后的总召回率。
                </Paragraph>
                {!chunkOk ? (
                  <Alert
                    type="info"
                    showIcon
                    style={{ marginBottom: 12 }}
                    message="请先在「切块审阅」确认切块"
                    action={
                      <Button size="small" onClick={() => setActiveTab("chunks")}>
                        去切块
                      </Button>
                    }
                  />
                ) : null}
                <Space style={{ marginBottom: 12 }} wrap>
                  <Button type="primary" loading={busy} onClick={() => void onGenerateQa()}>
                    一键生成并测评
                  </Button>
                  <Button loading={busy} onClick={() => void onSaveQa()}>
                    保存问答
                  </Button>
                  <Button loading={busy} onClick={() => void onHitTest()}>
                    重测全部
                  </Button>
                  <Button
                    onClick={() =>
                      setQaItems((prev) => [
                        ...prev,
                        { question: "", expected_chunk_hint: "" },
                      ])
                    }
                  >
                    加一行
                  </Button>
                </Space>
                <Table
                  rowKey={(_, i) => String(i)}
                  pagination={false}
                  scroll={{ x: 1100 }}
                  columns={qaColumns}
                  dataSource={qaItems.map((q, i) => ({ ...q, key: i }))}
                />
              </div>
            ),
          },
          {
            key: "publish",
            label: "③ 发布",
            children: (
              <div style={{ maxWidth: 640 }}>
                <Paragraph type="secondary">
                  三项条件全部满足后即可发布到知识库，供对话检索使用。
                </Paragraph>
                <Card size="small" style={{ marginBottom: 16 }}>
                  <Space direction="vertical" style={{ width: "100%" }}>
                    <div>
                      {chunkOk ? (
                        <Tag color="success">切块已确认</Tag>
                      ) : (
                        <>
                          <Tag color="error">切块未确认</Tag>
                          <Button type="link" onClick={() => setActiveTab("chunks")}>
                            去切块审阅
                          </Button>
                        </>
                      )}
                    </div>
                    <div>
                      {qaOk ? (
                        <Tag color="success">问答 ≥ 5</Tag>
                      ) : (
                        <>
                          <Tag color="error">问答不足 5 条</Tag>
                          <Button type="link" onClick={() => setActiveTab("qa")}>
                            去质量评测
                          </Button>
                        </>
                      )}
                    </div>
                    <div>
                      {hitOk ? (
                        <Tag color="success">召回率达标</Tag>
                      ) : (
                        <>
                          <Tag color="error">召回率未达标或未测</Tag>
                          <Button type="link" onClick={() => setActiveTab("qa")}>
                            去重测全部
                          </Button>
                        </>
                      )}
                    </div>
                  </Space>
                </Card>
                {info.status === "published" ? (
                  <Alert type="success" showIcon message="文档已发布" />
                ) : (
                  <Button
                    type="primary"
                    size="large"
                    loading={busy}
                    disabled={!canPublish}
                    onClick={() => void onPublish()}
                  >
                    发布
                  </Button>
                )}
              </div>
            ),
          },
          {
            key: "versions",
            label: "版本",
            children: (
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                style={{ maxWidth: 720 }}
                dataSource={versions}
                columns={[
                  { title: "版本号", dataIndex: "version_no", width: 80 },
                  { title: "标题", dataIndex: "title" },
                  {
                    title: "时间",
                    dataIndex: "created_at",
                    width: 180,
                    render: (t?: string | null) =>
                      t ? String(t).replace("T", " ").slice(0, 19) : "—",
                  },
                  {
                    title: "操作",
                    width: 100,
                    render: (_, row) => (
                      <Button
                        type="link"
                        size="small"
                        disabled={busy}
                        onClick={() => void onRollback(row.id)}
                      >
                        回滚
                      </Button>
                    ),
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </div>
  );
}
