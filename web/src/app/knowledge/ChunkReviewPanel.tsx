/**
 * 文档切块预览：手改、LLM 建议对比、确认 / 打回待审。
 * @author 赵振明
 * @date 2026-07-24 15:38:12
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { apiJson, type ApiBody } from "@/lib/api";

export type ChunkItem = {
  id: string;
  ordinal: number;
  content: string;
  content_len: number;
};

type LlmSuggestItem = {
  chunk_id: string;
  original: string;
  proposed: string;
};

type ChunkReviewPanelProps = {
  documentId: string;
  docTitle: string;
  docStatus: string;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onError: (msg: string) => void;
  onMsg: (msg: string) => void;
  onRefreshDocs: () => Promise<void>;
  onClose: () => void;
};

function apiError(body: ApiBody, fallback: string): string {
  if (body.message) return body.message;
  if (body.code !== undefined && body.code !== 0) return `${fallback}（${body.code}）`;
  return fallback;
}

const COLLAPSE_LEN = 480;

export function ChunkReviewPanel({
  documentId,
  docTitle,
  docStatus,
  busy,
  setBusy,
  onError,
  onMsg,
  onRefreshDocs,
  onClose,
}: ChunkReviewPanelProps) {
  const editable = docStatus === "pending_review";
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [llmItems, setLlmItems] = useState<LlmSuggestItem[]>([]);
  const [llmContractLike, setLlmContractLike] = useState(false);
  const [selectedApply, setSelectedApply] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);

  const loadChunks = useCallback(async () => {
    setLoading(true);
    onError("");
    try {
      const body = await apiJson<{ items: ChunkItem[] }>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks`,
      );
      if (body.code !== 0) throw new Error(apiError(body, "加载切块失败"));
      const items = body.data?.items || [];
      setChunks(items);
      setDrafts(Object.fromEntries(items.map((c) => [c.id, c.content])));
      setCollapsed(
        Object.fromEntries(
          items.map((c) => [c.id, (c.content || "").length > COLLAPSE_LEN]),
        ),
      );
      setLlmItems([]);
      setSelectedApply({});
    } catch (err) {
      onError(err instanceof Error ? err.message : "加载切块失败");
    } finally {
      setLoading(false);
    }
  }, [documentId, onError]);

  useEffect(() => {
    void loadChunks();
  }, [loadChunks]);

  async function onSaveChunk(chunkId: string) {
    const content = (drafts[chunkId] ?? "").trim();
    if (!content) {
      onError("切块内容不能为空");
      return;
    }
    onError("");
    onMsg("");
    setBusy(true);
    try {
      const body = await apiJson<ChunkItem>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/${encodeURIComponent(chunkId)}`,
        { method: "PUT", body: JSON.stringify({ content }) },
      );
      if (body.code !== 0) throw new Error(apiError(body, "保存切块失败"));
      const saved = body.data;
      setChunks((prev) => prev.map((c) => (c.id === chunkId ? saved : c)));
      setDrafts((prev) => ({ ...prev, [chunkId]: saved.content }));
      onMsg(`已保存切块 #${saved.ordinal}`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "保存切块失败");
    } finally {
      setBusy(false);
    }
  }

  async function onLlmSuggest() {
    onError("");
    onMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{
        items: LlmSuggestItem[];
        contract_like?: boolean;
      }>(`/api/v1/documents/${encodeURIComponent(documentId)}/chunks/llm-clean`, {
        method: "POST",
        body: JSON.stringify({ scope: "all", mode: "suggest" }),
      });
      if (body.code !== 0) throw new Error(apiError(body, "大模型清理预览失败"));
      const items = body.data?.items || [];
      setLlmItems(items);
      setLlmContractLike(!!body.data?.contract_like);
      const sel: Record<string, boolean> = {};
      for (const it of items) {
        if (it.original !== it.proposed) sel[it.chunk_id] = true;
      }
      setSelectedApply(sel);
      const changed = items.filter((it) => it.original !== it.proposed).length;
      onMsg(
        changed
          ? `已生成 ${items.length} 块对比，其中 ${changed} 块有建议修改`
          : `已预览 ${items.length} 块，未发现需清理内容`,
      );
    } catch (err) {
      onError(err instanceof Error ? err.message : "大模型清理预览失败");
    } finally {
      setBusy(false);
    }
  }

  async function onApplyLlm(forceApply = false) {
    const chunkIds = Object.entries(selectedApply)
      .filter(([, v]) => v)
      .map(([id]) => id);
    if (!chunkIds.length) {
      onError("请勾选要应用的切块");
      return;
    }
    onError("");
    onMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ items: LlmSuggestItem[] }>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/llm-clean`,
        {
          method: "POST",
          body: JSON.stringify({
            scope: "selected",
            mode: "apply",
            chunk_ids: chunkIds,
            force_apply: forceApply,
          }),
        },
      );
      if (body.code === 40901 && !forceApply) {
        const hint =
          body.message ||
          "合同类文档须二次确认后才能应用 LLM 清理";
        const ok = window.confirm(`${hint}\n\n确认强制应用所选切块？`);
        if (ok) {
          setBusy(false);
          await onApplyLlm(true);
          return;
        }
        onError(hint);
        return;
      }
      if (body.code !== 0) throw new Error(apiError(body, "应用 LLM 清理失败"));
      onMsg(`已应用 ${chunkIds.length} 块清理结果`);
      setLlmItems([]);
      setSelectedApply({});
      await loadChunks();
    } catch (err) {
      onError(err instanceof Error ? err.message : "应用 LLM 清理失败");
    } finally {
      setBusy(false);
    }
  }

  async function onConfirmChunks() {
    const ok = window.confirm("确认后将写入向量并进入「已确认」状态，是否继续？");
    if (!ok) return;
    onError("");
    onMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ status: string; chunks?: number }>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/confirm`,
        { method: "POST", body: "{}" },
      );
      if (body.code !== 0) throw new Error(apiError(body, "确认切块失败"));
      onMsg(`切块已确认，文档状态：${body.data?.status || "ready"}`);
      setLlmItems([]);
      await onRefreshDocs();
      onClose();
    } catch (err) {
      onError(err instanceof Error ? err.message : "确认切块失败");
    } finally {
      setBusy(false);
    }
  }

  async function onReopen() {
    const ok = window.confirm("打回后文档将回到「待审切块」，需重新确认后才能发布。是否继续？");
    if (!ok) return;
    onError("");
    onMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ status: string }>(
        `/api/v1/documents/${encodeURIComponent(documentId)}/chunks/reopen`,
        { method: "POST", body: "{}" },
      );
      if (body.code !== 0) throw new Error(apiError(body, "打回待审失败"));
      onMsg("已打回待审切块");
      await onRefreshDocs();
      onClose();
    } catch (err) {
      onError(err instanceof Error ? err.message : "打回待审失败");
    } finally {
      setBusy(false);
    }
  }

  function toggleCollapse(chunkId: string) {
    setCollapsed((prev) => ({ ...prev, [chunkId]: !prev[chunkId] }));
  }

  return (
    <div className="kb-perms kb-chunks">
      <h3>
        切块预览 · {docTitle}
        <span className="kb-list-id"> {documentId}</span>
      </h3>
      <p className="kb-hint">
        {editable
          ? "可手改每块正文；建议先用「大模型清理（预览）」对比后再应用；全部确认后点「确认切块」。"
          : docStatus === "ready"
            ? "文档已确认切块，当前为只读查看；可打回待审后重新编辑。"
            : "当前状态不可编辑切块。"}
        {llmContractLike ? " 检测到合同类文档，应用清理需二次确认。" : ""}
      </p>

      <div className="kb-perm-actions">
        {editable ? (
          <>
            <button
              className="btn btn-ghost"
              type="button"
              disabled={busy || loading}
              onClick={() => void onLlmSuggest()}
            >
              大模型清理（预览）
            </button>
            <button
              className="btn"
              type="button"
              disabled={busy || loading}
              onClick={() => void onConfirmChunks()}
            >
              确认切块
            </button>
          </>
        ) : null}
        {docStatus === "ready" ? (
          <button
            className="btn btn-ghost"
            type="button"
            disabled={busy}
            onClick={() => void onReopen()}
          >
            打回再审
          </button>
        ) : null}
        <button
          className="btn btn-ghost"
          type="button"
          disabled={busy}
          onClick={() => void loadChunks()}
        >
          刷新切块
        </button>
        <button className="btn btn-ghost" type="button" onClick={onClose}>
          关闭
        </button>
      </div>

      {loading ? <p className="kb-empty">加载切块中…</p> : null}

      {!loading && chunks.length === 0 ? (
        <p className="kb-empty">暂无切块（请等待入库完成）</p>
      ) : null}

      {!loading
        ? chunks.map((c) => {
            const draft = drafts[c.id] ?? c.content;
            const isCollapsed = collapsed[c.id];
            const showToggle = draft.length > COLLAPSE_LEN;
            const previewItem = llmItems.find((it) => it.chunk_id === c.id);
            return (
              <div className="kb-chunk-block" key={c.id}>
                <div className="kb-chunk-head">
                  <strong>
                    块 #{c.ordinal}
                  </strong>
                  <span className="kb-list-id">
                    {c.id} · {draft.length} 字
                  </span>
                  {showToggle ? (
                    <button
                      className="btn btn-ghost btn-sm"
                      type="button"
                      onClick={() => toggleCollapse(c.id)}
                    >
                      {isCollapsed ? "展开" : "折叠"}
                    </button>
                  ) : null}
                </div>
                {editable ? (
                  <>
                    <textarea
                      className="kb-chunk-textarea"
                      value={draft}
                      rows={isCollapsed ? 4 : 10}
                      onChange={(e) =>
                        setDrafts((prev) => ({ ...prev, [c.id]: e.target.value }))
                      }
                    />
                    <div className="kb-chunk-actions">
                      <button
                        className="btn btn-sm"
                        type="button"
                        disabled={busy || draft.trim() === c.content}
                        onClick={() => void onSaveChunk(c.id)}
                      >
                        保存本块
                      </button>
                    </div>
                  </>
                ) : (
                  <pre className="kb-chunk-readonly">
                    {isCollapsed ? `${draft.slice(0, COLLAPSE_LEN)}…` : draft}
                  </pre>
                )}

                {previewItem && previewItem.original !== previewItem.proposed ? (
                  <div className="kb-chunk-compare">
                    <label className="kb-chunk-compare-label">
                      <input
                        type="checkbox"
                        checked={!!selectedApply[c.id]}
                        disabled={!editable || busy}
                        onChange={(e) =>
                          setSelectedApply((prev) => ({
                            ...prev,
                            [c.id]: e.target.checked,
                          }))
                        }
                      />
                      应用 LLM 建议
                    </label>
                    <div className="kb-chunk-compare-grid">
                      <div>
                        <div className="kb-hint">原文</div>
                        <pre className="kb-chunk-diff">{previewItem.original}</pre>
                      </div>
                      <div>
                        <div className="kb-hint">建议</div>
                        <pre className="kb-chunk-diff is-proposed">{previewItem.proposed}</pre>
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })
        : null}

      {editable && llmItems.some((it) => it.original !== it.proposed) ? (
        <div className="kb-perm-actions">
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => void onApplyLlm(false)}
          >
            应用所选 LLM 建议
          </button>
        </div>
      ) : null}
    </div>
  );
}
