/**
 * 文档切块台：父块下挂子块的树状列表 + 手改/C2 + 确认/打回 + 重新切块。
 * @author 赵振明
 * @date 2026-11-20 17:25:11
 */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Collapse,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Radio,
  Space,
  Tag,
  Typography,
} from "antd";
import { apiJson } from "@/lib/api";
import { useSystemNotify } from "@/lib/system-notify";

type SummaryProgress = {
  document_id?: string;
  total: number;
  done: number;
  status: "idle" | "running" | "done" | "failed" | string;
  message?: string | null;
};

const { Text, Paragraph, Title } = Typography;
const { TextArea } = Input;

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

type ChunkMeta = {
  schema_version?: number;
  title?: string;
  doc_type?: string;
  category_codes?: string[];
  person_name?: string;
  project_name?: string;
  keywords?: string[];
  source?: string;
};

type ChunkItem = {
  id: string;
  ordinal: number;
  content: string;
  content_len?: number;
  chunk_role?: string | null;
  parent_chunk_id?: string | null;
  summary?: string | null;
  metadata?: ChunkMeta | null;
};

type MetaDraft = {
  person_name: string;
  project_name: string;
  keywords: string;
  doc_type: string;
};

type ChunkTreeNode = {
  parent: ChunkItem;
  children: ChunkItem[];
};

type Props = {
  documentId: string;
  docStatus: string;
  onStatusChange?: () => void;
};

/**
 * 规范化角色：空视为 child（兼容旧数据）。
 */
function roleOf(c: ChunkItem): "parent" | "child" {
  return c.chunk_role === "parent" ? "parent" : "child";
}

/**
 * 将扁平切块组装为「父 → 子[]」树；无父归属的子块单独返回。
 */
function buildChunkTree(chunks: ChunkItem[]): {
  nodes: ChunkTreeNode[];
  orphans: ChunkItem[];
} {
  const parents = chunks
    .filter((c) => roleOf(c) === "parent")
    .slice()
    .sort((a, b) => a.ordinal - b.ordinal);
  const parentIds = new Set(parents.map((p) => p.id));
  const childrenByParent = new Map<string, ChunkItem[]>();
  const orphans: ChunkItem[] = [];

  for (const c of chunks) {
    if (roleOf(c) === "parent") continue;
    const pid = c.parent_chunk_id || "";
    if (pid && parentIds.has(pid)) {
      const list = childrenByParent.get(pid) || [];
      list.push(c);
      childrenByParent.set(pid, list);
    } else {
      orphans.push(c);
    }
  }

  for (const list of childrenByParent.values()) {
    list.sort((a, b) => a.ordinal - b.ordinal);
  }

  const nodes: ChunkTreeNode[] = parents.map((parent) => ({
    parent,
    children: childrenByParent.get(parent.id) || [],
  }));

  orphans.sort((a, b) => a.ordinal - b.ordinal);
  return { nodes, orphans };
}

export function ChunkWorkbench({ documentId, docStatus, onStatusChange }: Props) {
  const { message } = App.useApp();
  const { notify } = useSystemNotify();
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [metaDrafts, setMetaDrafts] = useState<Record<string, MetaDraft>>({});
  const [splitAt, setSplitAt] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const awaitingSummaryRef = useRef(false);
  const lastProgressDoneRef = useRef(-1);
  const progressStatusRef = useRef<string>("idle");
  const lastFailMsgRef = useRef<string | null>(null);
  const [summaryProgress, setSummaryProgress] = useState<SummaryProgress | null>(
    null,
  );
  const [rechunkOpen, setRechunkOpen] = useState(false);
  const [chunkMode, setChunkMode] = useState<ChunkMode>("auto");
  const [parentSize, setParentSize] = useState(1400);
  const [childSize, setChildSize] = useState(550);
  const [chunkOverlap, setChunkOverlap] = useState(80);
  const [chunkProfile, setChunkProfile] = useState<ChunkProfile | null>(null);
  // 本地覆盖：重新切块/确认后立刻用接口返回状态，避免父页异步刷新前看不到「确认切块」
  const [statusOverride, setStatusOverride] = useState<string | null>(null);
  const effectiveStatus = statusOverride || docStatus || "";
  const editable = effectiveStatus === "pending_review";
  const canRechunk =
    !!effectiveStatus &&
    effectiveStatus !== "processing" &&
    effectiveStatus !== "uploading";

  useEffect(() => {
    // 父页状态追上后清掉覆盖，避免长期分叉
    setStatusOverride(null);
  }, [docStatus]);

  const { nodes, orphans } = useMemo(() => buildChunkTree(chunks), [chunks]);

  const stats = useMemo(() => {
    let parents = 0;
    let children = 0;
    let summarized = 0;
    for (const c of chunks) {
      if (roleOf(c) === "parent") {
        parents += 1;
        if ((c.summary || "").trim()) summarized += 1;
      } else {
        children += 1;
      }
    }
    return { parents, children, total: chunks.length, summarized };
  }, [chunks]);

  const load = useCallback(
    async (opts?: { quiet?: boolean }) => {
      if (!opts?.quiet) setLoading(true);
      try {
        const res = await apiJson<{ items: ChunkItem[] }>(
          `/api/v1/documents/${encodeURIComponent(documentId)}/chunks`,
        );
        if (res.code !== 0) {
          if (!opts?.quiet) message.error(res.message || "加载切块失败");
          return;
        }
        const items = res.data?.items || [];
        setChunks(items);
        const d: Record<string, string> = {};
        const md: Record<string, MetaDraft> = {};
        for (const c of items) {
          d[c.id] = c.content;
          const m = c.metadata || {};
          md[c.id] = {
            person_name: String(m.person_name || ""),
            project_name: String(m.project_name || ""),
            keywords: Array.isArray(m.keywords)
              ? m.keywords.join(", ")
              : String(m.keywords || ""),
            doc_type: String(m.doc_type || "generic"),
          };
        }
        setDrafts(d);
        setMetaDrafts(md);
      } catch (err) {
        if (!opts?.quiet) {
          message.error(`加载切块失败：${(err as Error).message}`);
        }
      } finally {
        if (!opts?.quiet) setLoading(false);
      }
    },
    [documentId, message],
  );

  /**
   * 拉取父块摘要进度（total/done），不触发整页 loading。
   */
  const fetchSummaryProgress = useCallback(async () => {
    try {
      const res = await apiJson<SummaryProgress>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/parent-summary-progress`,
      );
      if (res.code !== 0 || !res.data) return null;
      setSummaryProgress(res.data);
      return res.data;
    } catch {
      return null;
    }
  }, [documentId]);

  useEffect(() => {
    void load();
    void fetchSummaryProgress();
  }, [load, fetchSummaryProgress]);

  // 静默轮询进度接口；done 变化时再静默刷新切块（避免整页 loading 闪烁）
  useEffect(() => {
    const incomplete =
      stats.parents > 0 && stats.summarized < stats.parents;
    const failedStuck = progressStatusRef.current === "failed";
    const shouldPoll =
      awaitingSummaryRef.current ||
      ((effectiveStatus === "ready" || effectiveStatus === "published") &&
        incomplete &&
        !failedStuck);
    if (!shouldPoll) return;
    awaitingSummaryRef.current = true;

    let cancelled = false;
    const tick = async () => {
      const prog = await fetchSummaryProgress();
      if (cancelled || !prog) return;
      progressStatusRef.current = String(prog.status || "idle");
      const done = Number(prog.done) || 0;
      const total = Number(prog.total) || 0;
      if (done !== lastProgressDoneRef.current) {
        lastProgressDoneRef.current = done;
        await load({ quiet: true });
      }
      if (prog.status === "done" && total > 0 && done >= total) {
        if (awaitingSummaryRef.current) {
          awaitingSummaryRef.current = false;
          lastFailMsgRef.current = null;
          notify({
            type: "success",
            title: "父块摘要已生成",
            description: `已完成 ${done}/${total} 条 LLM 摘要，可参与检索。`,
            playSound: true,
          });
          onStatusChange?.();
        }
      } else if (prog.status === "failed") {
        awaitingSummaryRef.current = false;
        const failMsg = prog.message || "请点击「重试摘要」";
        if (lastFailMsgRef.current !== failMsg) {
          lastFailMsgRef.current = failMsg;
          notify({
            type: "error",
            title: "父块摘要生成失败",
            description: failMsg,
            playSound: true,
          });
        }
      }
    };

    void tick();
    const t = window.setInterval(() => {
      void tick();
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [
    effectiveStatus,
    stats.parents,
    stats.summarized,
    fetchSummaryProgress,
    load,
    notify,
    onStatusChange,
  ]);

  /**
   * 手动触发 / 重试父块摘要后台任务。
   */
  async function onRetryParentSummary() {
    setBusy(true);
    try {
      const res = await apiJson<{ queued?: boolean; total?: number }>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/parent-summary/run`,
        { method: "POST", body: "{}" },
      );
      if (res.code !== 0) {
        message.error(res.message || "触发摘要失败");
        return;
      }
      awaitingSummaryRef.current = true;
      lastProgressDoneRef.current = -1;
      lastFailMsgRef.current = null;
      progressStatusRef.current = "running";
      setSummaryProgress({
        total: Number(res.data?.total) || stats.parents,
        done: 0,
        status: "running",
        message: "手动触发",
      });
      notify({
        type: "info",
        title: "父块摘要生成中",
        description: `共 ${Number(res.data?.total) || stats.parents} 条任务，完成后将通知你。`,
        playSound: true,
        durationMs: 4200,
      });
      void fetchSummaryProgress();
    } catch (err) {
      message.error(`触发摘要失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  /**
   * 判断切块 metadata 草稿是否相对服务端有变更。
   */
  function metaDirty(chunkId: string, c: ChunkItem): boolean {
    const draft = metaDrafts[chunkId];
    if (!draft) return false;
    const m = c.metadata || {};
    const kw = Array.isArray(m.keywords)
      ? m.keywords.join(", ")
      : String(m.keywords || "");
    return (
      draft.person_name !== String(m.person_name || "") ||
      draft.project_name !== String(m.project_name || "") ||
      draft.keywords !== kw ||
      draft.doc_type !== String(m.doc_type || "generic")
    );
  }

  async function saveChunk(chunkId: string) {
    const content = (drafts[chunkId] || "").trim();
    if (!content) {
      message.error("切块内容不能为空");
      return;
    }
    const chunk = chunks.find((x) => x.id === chunkId);
    const body: { content: string; metadata?: MetaDraft } = { content };
    if (chunk && metaDirty(chunkId, chunk) && metaDrafts[chunkId]) {
      body.metadata = metaDrafts[chunkId];
    }
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`,
        { method: "PUT", body: JSON.stringify(body) },
      );
      if (res.code !== 0) {
        message.error(res.message || "保存失败");
        return;
      }
      message.success("已保存");
      await load();
    } catch (err) {
      message.error(`保存失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  /**
   * 将文档级 metadata 同步到未手改切块。
   */
  async function onSyncMetadata() {
    setBusy(true);
    try {
      const res = await apiJson<{ updated?: number }>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/sync-metadata`,
        { method: "POST", body: "{}" },
      );
      if (res.code !== 0) {
        message.error(res.message || "同步 metadata 失败");
        return;
      }
      message.success(`已同步 ${res.data?.updated ?? 0} 块 metadata`);
      await load();
    } catch (err) {
      message.error(`同步 metadata 失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  /**
   * 回填 metadata 并可选重建向量（ready/published）。
   */
  async function onBackfillMetadata(reembed: boolean) {
    setBusy(true);
    try {
      const res = await apiJson<{ updated?: number; embedded?: number }>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/backfill-metadata`,
        {
          method: "POST",
          body: JSON.stringify({ reembed }),
        },
      );
      if (res.code !== 0) {
        message.error(res.message || "回填失败");
        return;
      }
      message.success(
        reembed
          ? `已回填 ${res.data?.updated ?? 0} 块，重建向量 ${res.data?.embedded ?? 0}`
          : `已回填 ${res.data?.updated ?? 0} 块 metadata`,
      );
      await load();
      onStatusChange?.();
    } catch (err) {
      message.error(`回填失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onSplit(chunkId: string) {
    const offset = splitAt[chunkId];
    if (!offset || offset < 1) {
      message.error("请填写拆分偏移（≥1）");
      return;
    }
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}/split`,
        { method: "POST", body: JSON.stringify({ offset }) },
      );
      if (res.code !== 0) {
        message.error(res.message || "拆分失败");
        return;
      }
      message.success("已拆分");
      await load();
    } catch (err) {
      message.error(`拆分失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onMergeWithNext(chunkId: string) {
    const idx = chunks.findIndex((c) => c.id === chunkId);
    const left = chunks[idx];
    const right = chunks[idx + 1];
    if (!left || !right) return;
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/merge`,
        {
          method: "POST",
          body: JSON.stringify({ left_id: left.id, right_id: right.id }),
        },
      );
      if (res.code !== 0) {
        message.error(res.message || "合并失败");
        return;
      }
      message.success("已合并");
      await load();
    } catch (err) {
      message.error(`合并失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onMove(chunkId: string, dir: -1 | 1) {
    const idx = chunks.findIndex((c) => c.id === chunkId);
    const j = idx + dir;
    if (idx < 0 || j < 0 || j >= chunks.length) return;
    const ids = chunks.map((c) => c.id);
    const tmp = ids[idx];
    ids[idx] = ids[j];
    ids[j] = tmp;
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/reorder`,
        { method: "POST", body: JSON.stringify({ ordered_ids: ids }) },
      );
      if (res.code !== 0) {
        message.error(res.message || "调序失败");
        return;
      }
      await load();
    } catch (err) {
      message.error(`调序失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(chunkId: string) {
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`,
        { method: "DELETE" },
      );
      if (res.code !== 0) {
        message.error(res.message || "删除失败");
        return;
      }
      message.success("已删除");
      await load();
    } catch (err) {
      message.error(`删除失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    setBusy(true);
    try {
      const res = await apiJson<{
        parent_summaries?: number;
        parent_summary_queued?: boolean;
        parent_summary_total?: number;
      }>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/confirm`,
        { method: "POST", body: "{}" },
      );
      if (res.code !== 0) {
        message.error(res.message || "确认失败");
        onStatusChange?.();
        return;
      }
      if (res.data?.parent_summary_queued) {
        awaitingSummaryRef.current = true;
        lastProgressDoneRef.current = -1;
        const total = Number(res.data.parent_summary_total) || stats.parents;
        setSummaryProgress({
          total,
          done: 0,
          status: "running",
          message: "排队生成中",
        });
        message.success("切块已确认");
        notify({
          type: "info",
          title: "父块摘要生成中",
          description: `共 ${total} 条任务，进度见下方进度条。`,
          playSound: true,
          durationMs: 4200,
        });
      } else {
        const summarized = res.data?.parent_summaries;
        message.success(
          typeof summarized === "number"
            ? `切块已确认（父块摘要 ${summarized} 条）`
            : "切块已确认",
        );
      }
      setStatusOverride("ready");
      onStatusChange?.();
      await load();
    } catch (err) {
      message.error(`确认失败：${(err as Error).message}`);
      onStatusChange?.();
    } finally {
      setBusy(false);
    }
  }

  async function onReopen() {
    setBusy(true);
    try {
      const res = await apiJson(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/reopen`,
        { method: "POST", body: "{}" },
      );
      if (res.code !== 0) {
        message.error(res.message || "打回失败");
        return;
      }
      message.success("已打回待审");
      setStatusOverride("pending_review");
      onStatusChange?.();
      await load();
    } catch (err) {
      message.error(`打回失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  /**
   * 按模式拉取推荐切块尺寸（重新切块弹窗用）。
   */
  async function refreshChunkProfile(mode: ChunkMode, parent: number, child: number, overlap: number) {
    const chars = chunks.reduce((sum, c) => sum + (c.content?.length || 0), 0);
    try {
      const res = await apiJson<ChunkProfile>("/api/v1/documents/chunk-recommend", {
        method: "POST",
        body: JSON.stringify({
          char_count: Math.max(chars, 1),
          mode,
          parent_size: mode === "custom" ? parent : undefined,
          child_size: mode === "custom" ? child : undefined,
          overlap: mode === "custom" ? overlap : undefined,
        }),
      });
      if (res.code !== 0 || !res.data) return;
      setChunkProfile(res.data);
      if (mode !== "custom") {
        setParentSize(res.data.parent_size);
        setChildSize(res.data.child_size);
        setChunkOverlap(res.data.overlap);
      }
    } catch {
      /* 推荐失败不阻断 */
    }
  }

  /**
   * 打开重新切块弹窗并预填推荐。
   */
  function openRechunkModal() {
    setChunkMode("auto");
    setRechunkOpen(true);
    void refreshChunkProfile("auto", parentSize, childSize, chunkOverlap);
  }

  /**
   * 提交重新切块（默认同步；会清空现有切块/向量）。
   */
  async function onRechunk() {
    if (chunkMode === "custom" && childSize >= parentSize) {
      message.error("子块尺寸须小于父块尺寸");
      return;
    }
    setBusy(true);
    try {
      const res = await apiJson<{
        status?: string;
        chunks?: number;
        queued?: boolean;
      }>(`/api/v1/documents/${encodeURIComponent(documentId)}/rechunk`, {
        method: "POST",
        body: JSON.stringify({
          chunk_mode: chunkMode,
          parent_size: parentSize,
          child_size: childSize,
          chunk_overlap: chunkOverlap,
          queue: false,
        }),
      });
      if (res.code !== 0) {
        message.error(res.message || "重新切块失败");
        return;
      }
      const st = String(res.data?.status || "pending_review");
      const n = res.data?.chunks;
      setStatusOverride(st);
      if (st === "pending_review") {
        message.success(
          n != null
            ? `已重新切块（${n} 块），请确认切块`
            : "已重新切块，请确认切块",
        );
      } else if (st === "failed") {
        message.error(
          `重新切块失败（状态：${st}）。请检查源文件是否还在，或查看文档失败原因。`,
        );
      } else {
        message.success(
          n != null ? `已重新切块（${st}，${n} 块）` : `已重新切块（${st}）`,
        );
      }
      setRechunkOpen(false);
      onStatusChange?.();
      await load();
    } catch (err) {
      message.error(`重新切块失败：${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  /**
   * 渲染单个切块卡片（父/子共用操作区）。
   */
  function renderChunkCard(
    c: ChunkItem,
    opts: { role: "parent" | "child"; nested?: boolean },
  ) {
    const isParent = opts.role === "parent";
    const flatIdx = chunks.findIndex((x) => x.id === c.id);
    const preview = (drafts[c.id] ?? c.content).replace(/\s+/g, " ").slice(0, 80);

    return (
      <div
        key={c.id}
        style={{
          border: "1px solid var(--ant-color-border, #d9d9d9)",
          borderLeft: isParent ? "4px solid #1677ff" : "4px solid #52c41a",
          borderRadius: 8,
          padding: 12,
          marginBottom: opts.nested ? 8 : 0,
          marginLeft: opts.nested ? 0 : 0,
          background: isParent
            ? "rgba(22, 119, 255, 0.04)"
            : "var(--ant-color-bg-container, #fff)",
        }}
      >
        <Space style={{ marginBottom: 8 }} wrap>
          <Text strong>#{c.ordinal}</Text>
          {isParent ? (
            <Tag color="blue">父块</Tag>
          ) : (
            <>
              <Tag color="green">子块</Tag>
              <Tag>可检索</Tag>
            </>
          )}
          <Text type="secondary" copyable={{ text: c.id }}>
            {c.id}
          </Text>
          <Text type="secondary">
            {(drafts[c.id] ?? c.content).length} 字
          </Text>
          {!isParent ? (
            <Text type="secondary" ellipsis style={{ maxWidth: 280 }}>
              {preview}
              {(drafts[c.id] ?? c.content).length > 80 ? "…" : ""}
            </Text>
          ) : null}
        </Space>
        {isParent ? (
          <div
            style={{
              marginBottom: 10,
              padding: "10px 12px",
              borderRadius: 6,
              border: "1px solid rgba(114, 46, 209, 0.35)",
              background: "rgba(114, 46, 209, 0.06)",
            }}
          >
            <Space style={{ marginBottom: 6 }} wrap>
              <Text strong>检索摘要</Text>
              {(c.summary || "").trim() ? (
                <Tag color="purple">已生成 · {(c.summary || "").length} 字</Tag>
              ) : (
                <Tag>摘要待就绪</Tag>
              )}
            </Space>
            {(c.summary || "").trim() ? (
              <Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                {c.summary}
              </Paragraph>
            ) : (
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                {effectiveStatus === "ready" || effectiveStatus === "published"
                  ? "后台 LLM 生成中，完成后会系统通知。"
                  : "确认切块后由后台 LLM 异步生成摘要。"}
              </Paragraph>
            )}
          </div>
        ) : null}
        <div
          style={{
            marginBottom: 10,
            padding: "8px 10px",
            borderRadius: 6,
            border: "1px dashed var(--ant-color-border, #d9d9d9)",
            background: "rgba(0,0,0,0.02)",
          }}
        >
          <Space style={{ marginBottom: 6 }} wrap>
            <Text strong>检索 Metadata</Text>
            <Tag>{(c.metadata?.source as string) || "inherit"}</Tag>
            {c.metadata?.title ? (
              <Text type="secondary">标题：{c.metadata.title}</Text>
            ) : null}
          </Space>
          <Space wrap style={{ width: "100%" }} size="small">
            <Input
              size="small"
              style={{ width: 120 }}
              addonBefore="类型"
              value={metaDrafts[c.id]?.doc_type ?? c.metadata?.doc_type ?? ""}
              disabled={!editable || busy}
              onChange={(e) =>
                setMetaDrafts((prev) => ({
                  ...prev,
                  [c.id]: {
                    ...(prev[c.id] || {
                      person_name: "",
                      project_name: "",
                      keywords: "",
                      doc_type: "generic",
                    }),
                    doc_type: e.target.value,
                  },
                }))
              }
            />
            <Input
              size="small"
              style={{ width: 140 }}
              addonBefore="人名"
              value={metaDrafts[c.id]?.person_name ?? ""}
              disabled={!editable || busy}
              onChange={(e) =>
                setMetaDrafts((prev) => ({
                  ...prev,
                  [c.id]: {
                    ...(prev[c.id] || {
                      person_name: "",
                      project_name: "",
                      keywords: "",
                      doc_type: "generic",
                    }),
                    person_name: e.target.value,
                  },
                }))
              }
            />
            <Input
              size="small"
              style={{ width: 160 }}
              addonBefore="项目"
              value={metaDrafts[c.id]?.project_name ?? ""}
              disabled={!editable || busy}
              onChange={(e) =>
                setMetaDrafts((prev) => ({
                  ...prev,
                  [c.id]: {
                    ...(prev[c.id] || {
                      person_name: "",
                      project_name: "",
                      keywords: "",
                      doc_type: "generic",
                    }),
                    project_name: e.target.value,
                  },
                }))
              }
            />
            <Input
              size="small"
              style={{ minWidth: 220, flex: 1 }}
              addonBefore="关键词"
              placeholder="逗号分隔"
              value={metaDrafts[c.id]?.keywords ?? ""}
              disabled={!editable || busy}
              onChange={(e) =>
                setMetaDrafts((prev) => ({
                  ...prev,
                  [c.id]: {
                    ...(prev[c.id] || {
                      person_name: "",
                      project_name: "",
                      keywords: "",
                      doc_type: "generic",
                    }),
                    keywords: e.target.value,
                  },
                }))
              }
            />
          </Space>
        </div>
        <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
          {isParent ? "父块正文" : "子块正文"}
        </Text>
        <TextArea
          rows={isParent ? 3 : 4}
          value={drafts[c.id] ?? c.content}
          disabled={!editable || busy}
          onChange={(e) =>
            setDrafts((prev) => ({ ...prev, [c.id]: e.target.value }))
          }
        />
        {editable ? (
          <Space style={{ marginTop: 8 }} wrap>
            <Button
              size="small"
              disabled={
                busy ||
                ((drafts[c.id] ?? "") === c.content && !metaDirty(c.id, c))
              }
              onClick={() => void saveChunk(c.id)}
            >
              保存
            </Button>
            <InputNumber
              size="small"
              min={1}
              placeholder="拆分偏移"
              value={splitAt[c.id]}
              onChange={(v) =>
                setSplitAt((prev) => ({
                  ...prev,
                  [c.id]: typeof v === "number" ? v : 1,
                }))
              }
            />
            <Button size="small" disabled={busy} onClick={() => void onSplit(c.id)}>
              拆分
            </Button>
            <Button
              size="small"
              disabled={busy || flatIdx < 0 || flatIdx >= chunks.length - 1}
              onClick={() => void onMergeWithNext(c.id)}
            >
              与下块合并
            </Button>
            <Button
              size="small"
              disabled={busy || flatIdx <= 0}
              onClick={() => void onMove(c.id, -1)}
            >
              上移
            </Button>
            <Button
              size="small"
              disabled={busy || flatIdx < 0 || flatIdx >= chunks.length - 1}
              onClick={() => void onMove(c.id, 1)}
            >
              下移
            </Button>
            <Popconfirm
              title="确认删除该块？"
              onConfirm={() => void onDelete(c.id)}
            >
              <Button size="small" danger disabled={busy}>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ) : null}
      </div>
    );
  }

  const collapseItems = nodes.map((node) => {
    const p = node.parent;
    const childCount = node.children.length;
    const preview = (drafts[p.id] ?? p.content).replace(/\s+/g, " ").slice(0, 60);
    return {
      key: p.id,
      label: (
        <Space wrap>
          <Tag color="blue">父块</Tag>
          <Text strong>#{p.ordinal}</Text>
          <Tag>
            {childCount} 个子块
          </Tag>
          {(p.summary || "").trim() ? (
            <Tag color="purple">已摘要</Tag>
          ) : (
            <Tag>摘要未生成</Tag>
          )}
          <Text type="secondary">
            {(drafts[p.id] ?? p.content).length} 字
          </Text>
          <Text type="secondary" ellipsis style={{ maxWidth: 420 }}>
            {(p.summary || "").trim()
              ? `摘要：${p.summary}`
              : `正文预览：${preview}${(drafts[p.id] ?? p.content).length > 60 ? "…" : ""}`}
          </Text>
        </Space>
      ),
      children: (
        <div>
          {renderChunkCard(p, { role: "parent" })}
          <div
            style={{
              marginTop: 12,
              marginLeft: 16,
              paddingLeft: 16,
              borderLeft: "2px dashed #52c41a",
            }}
          >
            <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
              子块（检索用）
            </Text>
            {node.children.length === 0 ? (
              <Text type="secondary">暂无子块</Text>
            ) : (
              node.children.map((ch) =>
                renderChunkCard(ch, { role: "child", nested: true }),
              )
            )}
          </div>
        </div>
      ),
    };
  });

  return (
    <div>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button onClick={() => void load()} disabled={busy || loading}>
          刷新
        </Button>
        <Button
          loading={busy}
          disabled={!canRechunk || busy}
          onClick={() => openRechunkModal()}
        >
          重新切块
        </Button>
        <Button
          loading={busy}
          disabled={busy || loading}
          onClick={() => void onSyncMetadata()}
        >
          同步 Metadata
        </Button>
        <Popconfirm
          title="回填切块 Metadata，并对已确认/已发布文档重建向量？"
          onConfirm={() => void onBackfillMetadata(true)}
        >
          <Button loading={busy} disabled={busy || loading}>
            回填并重建向量
          </Button>
        </Popconfirm>
        {editable ? (
          <Button type="primary" loading={busy} onClick={() => void onConfirm()}>
            确认切块
          </Button>
        ) : null}
        {effectiveStatus === "ready" ? (
          <Button loading={busy} onClick={() => void onReopen()}>
            打回再审
          </Button>
        ) : null}
        <Tag>{effectiveStatus || "未知状态"}</Tag>
        <Tag color="blue">父块 {stats.parents}</Tag>
        <Tag color="green">子块 {stats.children}</Tag>
        <Tag color="purple">
          已摘要 {stats.summarized}/{stats.parents}
        </Tag>
        <Tag>合计 {stats.total}</Tag>
        {(effectiveStatus === "ready" || effectiveStatus === "published") &&
        stats.parents > 0 &&
        (stats.summarized < stats.parents ||
          summaryProgress?.status === "failed" ||
          summaryProgress?.status === "running") ? (
          <Button
            size="small"
            loading={busy}
            disabled={busy || summaryProgress?.status === "running"}
            onClick={() => void onRetryParentSummary()}
          >
            {summaryProgress?.status === "failed" ? "重试摘要" : "生成摘要"}
          </Button>
        ) : null}
      </Space>
      {summaryProgress &&
      (summaryProgress.status === "running" ||
        summaryProgress.status === "failed" ||
        (summaryProgress.total > 0 &&
          summaryProgress.done < summaryProgress.total)) ? (
        <div
          style={{
            marginBottom: 12,
            padding: "12px 14px",
            borderRadius: 8,
            border: "1px solid rgba(114, 46, 209, 0.35)",
            background: "rgba(114, 46, 209, 0.06)",
          }}
        >
          <Space style={{ marginBottom: 8 }} wrap>
            <Text strong>父块摘要进度</Text>
            <Tag color={summaryProgress.status === "failed" ? "error" : "processing"}>
              {summaryProgress.status === "failed"
                ? "失败"
                : summaryProgress.status === "done"
                  ? "完成"
                  : "处理中"}
            </Tag>
            <Text>
              已处理 {summaryProgress.done} / 共 {summaryProgress.total} 条
            </Text>
            {summaryProgress.message ? (
              <Text type="secondary">{summaryProgress.message}</Text>
            ) : null}
          </Space>
          <Progress
            percent={
              summaryProgress.total > 0
                ? Math.min(
                    100,
                    Math.round(
                      (summaryProgress.done / summaryProgress.total) * 100,
                    ),
                  )
                : 0
            }
            status={
              summaryProgress.status === "failed"
                ? "exception"
                : summaryProgress.status === "done"
                  ? "success"
                  : "active"
            }
            strokeColor="#722ed1"
          />
        </div>
      ) : null}
      {effectiveStatus === "failed" ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message="文档处理失败，无法确认切块"
          description="常见原因：源文件在存储中找不到。请重新上传版本或修复文件后再「重新切块」。成功后状态应为「待审切块」，才会出现确认按钮。"
        />
      ) : null}
      <Paragraph type="secondary">
        展开父块可见「检索摘要」与「检索 Metadata」。Metadata 在入库/重新切块时自动写入（标题、类型、人名/项目、关键词）；待审时可手改；点「确认切块」时写入向量库用于过滤。
        确认后先嵌子块并就绪；父块摘要由后台 LLM
        异步生成，页面展示「已处理/总任务」进度，完成后系统通知（含提示音）。
        {editable
          ? " 待审态可手改、拆分、合并相邻块、上下移与删除。"
          : " 当前状态只读；已确认可打回待审后再改。"}
        {" "}可用「重新切块」按当前文件重跑切块（会清空现有切块与向量）。
      </Paragraph>

      <Modal
        title="重新切块"
        open={rechunkOpen}
        onCancel={() => setRechunkOpen(false)}
        onOk={() => void onRechunk()}
        okText="开始切块"
        confirmLoading={busy}
        destroyOnClose
        width={560}
      >
        {(effectiveStatus === "published" || effectiveStatus === "ready") && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={
              effectiveStatus === "published"
                ? "已发布文档重新切块后将下架并进入待审，需再次确认与发布。"
                : "已确认文档重新切块后将回到待审，需再次确认。"
            }
          />
        )}
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          将按 OSS 原文删除现有切块/向量后重新切分。可选模式或自定义尺寸。
        </Paragraph>
        <div style={{ marginBottom: 12 }}>
          <Text strong>切块模式</Text>
          <div style={{ marginTop: 8 }}>
            <Radio.Group
              value={chunkMode}
              onChange={(e) => {
                const mode = e.target.value as ChunkMode;
                setChunkMode(mode);
                void refreshChunkProfile(mode, parentSize, childSize, chunkOverlap);
              }}
              optionType="button"
              buttonStyle="solid"
              options={[
                { label: "自动", value: "auto" },
                { label: "粗", value: "coarse" },
                { label: "均衡", value: "balanced" },
                { label: "细", value: "fine" },
                { label: "自定义", value: "custom" },
              ]}
            />
          </div>
        </div>
        <Space wrap style={{ marginBottom: 8 }}>
          <span>
            父块{" "}
            <InputNumber
              min={200}
              max={8000}
              value={parentSize}
              disabled={chunkMode !== "custom" || busy}
              onChange={(v) => {
                const next = typeof v === "number" ? v : 1400;
                setParentSize(next);
                setChunkMode("custom");
                void refreshChunkProfile("custom", next, childSize, chunkOverlap);
              }}
            />
          </span>
          <span>
            子块{" "}
            <InputNumber
              min={80}
              max={4000}
              value={childSize}
              disabled={chunkMode !== "custom" || busy}
              onChange={(v) => {
                const next = typeof v === "number" ? v : 550;
                setChildSize(next);
                setChunkMode("custom");
                void refreshChunkProfile("custom", parentSize, next, chunkOverlap);
              }}
            />
          </span>
          <span>
            重叠{" "}
            <InputNumber
              min={0}
              max={2000}
              value={chunkOverlap}
              disabled={chunkMode !== "custom" || busy}
              onChange={(v) => {
                const next = typeof v === "number" ? v : 80;
                setChunkOverlap(next);
                setChunkMode("custom");
                void refreshChunkProfile("custom", parentSize, childSize, next);
              }}
            />
          </span>
        </Space>
        {chunkProfile ? (
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>
            预估约 {chunkProfile.est_parent_count} 父块 / {chunkProfile.est_child_count}{" "}
            子块（按现有切块字数近似 {chunkProfile.char_count} 字）
          </Paragraph>
        ) : null}
      </Modal>
      {loading ? <Text type="secondary">加载中…</Text> : null}
      {!loading && nodes.length === 0 && orphans.length === 0 ? (
        <Text type="secondary">暂无切块</Text>
      ) : null}

      {!loading && nodes.length > 0 ? (
        <Collapse
          defaultActiveKey={nodes.slice(0, 3).map((n) => n.parent.id)}
          items={collapseItems}
          style={{ marginBottom: 16 }}
        />
      ) : null}

      {!loading && orphans.length > 0 ? (
        <div style={{ marginTop: 8 }}>
          <Title level={5} style={{ marginBottom: 8 }}>
            未归属子块
          </Title>
          <Paragraph type="secondary">
            这些子块没有有效父块关联（旧数据或父块已删）。
          </Paragraph>
          {orphans.map((ch) => renderChunkCard(ch, { role: "child" }))}
        </div>
      ) : null}
    </div>
  );
}
