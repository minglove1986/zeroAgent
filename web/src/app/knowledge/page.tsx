/**
 * 知识库管理闭环：列表/建库、上传、轮询、发布、软删/恢复、权限、问答命中。
 * @author 赵振明
 * @date 2026-07-23 14:42:13
 */
"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiJson, type ApiBody } from "@/lib/api";
import { ChunkReviewPanel } from "./ChunkReviewPanel";

type KbItem = {
  id: string;
  name: string;
  description?: string | null;
  owner_department_id?: string | null;
  visibility?: "public" | "department" | string | null;
  created_at?: string | null;
};

type DeptItem = {
  id: string;
  name: string;
  parent_id?: string | null;
};

type KbViewer = {
  is_platform_admin: boolean;
};

type DocItem = {
  id: string;
  title: string;
  status: string;
  hit_rate: number | null;
  qa_count: number;
  deleted_at: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  reason?: string | null;
  stage?: string | null;
  categories?: { id: string; code: string; name: string; is_primary: boolean }[];
};

type DocCategoryItem = {
  id: string;
  code: string;
  name: string;
  parent_id?: string | null;
  schema_code?: string | null;
};

type PermItem = {
  subject_type: "user" | "department" | "role";
  subject_id: string;
};

type DocStatus = {
  status: string;
  hit_rate: number | null;
  qa_count: number;
  stage?: string | null;
  reason?: string | null;
};

type QaItem = {
  id?: number;
  question: string;
  expected_chunk_hint?: string | null;
};

type HitDetail = {
  question: string;
  expected_chunk_hint?: string | null;
  hit: boolean;
  top_contents?: string[];
};

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const b64 = result.includes(",") ? result.split(",")[1] : result;
      resolve(b64);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/** 统一解析业务码 / HTTP 错误文案。 */
function apiError(body: ApiBody, fallback: string): string {
  if (body.message) return body.message;
  if (body.code !== undefined && body.code !== 0) return `${fallback}（${body.code}）`;
  return fallback;
}

function fmtHitRate(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

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

function visibilityLabel(v?: string | null): string {
  if (v === "department") return "部门私有";
  if (v === "public") return "公司内公开";
  return "可见性未设";
}

export default function KnowledgePage() {
  const [kbs, setKbs] = useState<KbItem[]>([]);
  const [departments, setDepartments] = useState<DeptItem[]>([]);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);
  const [selectedKbId, setSelectedKbId] = useState("");
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [perms, setPerms] = useState<PermItem[]>([]);
  const [showPerms, setShowPerms] = useState(false);
  const [kbName, setKbName] = useState("");
  const [kbVisibility, setKbVisibility] = useState<"public" | "department">("public");
  const [kbOwnerDeptId, setKbOwnerDeptId] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [docCategories, setDocCategories] = useState<DocCategoryItem[]>([]);
  const [uploadCategoryIds, setUploadCategoryIds] = useState<string[]>([]);
  const [primaryCategoryId, setPrimaryCategoryId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [kbFilter, setKbFilter] = useState("");
  const [qaDocId, setQaDocId] = useState("");
  const [qaItems, setQaItems] = useState<QaItem[]>([]);
  const [hitDetails, setHitDetails] = useState<HitDetail[]>([]);
  const [lastHitRate, setLastHitRate] = useState<number | null>(null);
  const [chunkDocId, setChunkDocId] = useState("");

  const selectedKb = kbs.find((k) => k.id === selectedKbId) || null;
  const canEditPerms = isPlatformAdmin;
  const deptNameById = Object.fromEntries(departments.map((d) => [d.id, d.name]));
  const leafCategories = docCategories.filter((c) => !!c.schema_code);

  const loadDepartments = useCallback(async () => {
    const body = await apiJson<{ items: DeptItem[] }>("/api/v1/departments");
    if (body.code !== 0) throw new Error(apiError(body, "加载部门失败"));
    const items = body.data?.items || [];
    setDepartments(items);
    setKbOwnerDeptId((prev) => prev || items[0]?.id || "");
  }, []);

  const loadDocCategories = useCallback(async () => {
    const body = await apiJson<{ items: DocCategoryItem[] }>("/api/v1/doc-categories");
    if (body.code !== 0) throw new Error(apiError(body, "加载文档分类失败"));
    const items = body.data?.items || [];
    setDocCategories(items);
    const leaf = items.filter((c) => c.schema_code);
    const def = leaf.find((c) => c.code === "hr.resume")?.id || leaf[0]?.id || "";
    setUploadCategoryIds((prev) => (prev.length ? prev : def ? [def] : []));
    setPrimaryCategoryId((prev) => prev || def);
  }, []);

  const loadKbs = useCallback(async (preferId?: string) => {
    const body = await apiJson<{ items: KbItem[]; viewer?: KbViewer }>(
      "/api/v1/knowledge-bases",
    );
    if (body.code !== 0) throw new Error(apiError(body, "加载知识库失败"));
    const items = body.data?.items || [];
    setKbs(items);
    setIsPlatformAdmin(!!body.data?.viewer?.is_platform_admin);
    setSelectedKbId((prev) => {
      if (preferId && items.some((k) => k.id === preferId)) return preferId;
      if (prev && items.some((k) => k.id === prev)) return prev;
      return items[0]?.id || "";
    });
  }, []);

  const loadDocs = useCallback(async (kbId: string) => {
    if (!kbId) {
      setDocs([]);
      return;
    }
    const body = await apiJson<{ items: DocItem[] }>(
      `/api/v1/documents?kb_id=${encodeURIComponent(kbId)}&include_deleted=1`,
    );
    if (body.code !== 0) throw new Error(apiError(body, "加载文档失败"));
    setDocs(body.data?.items || []);
  }, []);

  const loadPerms = useCallback(async (kbId: string) => {
    if (!kbId) {
      setPerms([]);
      return;
    }
    const body = await apiJson<{ items: PermItem[] }>(
      `/api/v1/knowledge-bases/${encodeURIComponent(kbId)}/permissions`,
    );
    if (body.code !== 0) throw new Error(apiError(body, "加载权限失败"));
    setPerms(body.data?.items || []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setError("");
      try {
        await Promise.all([loadKbs(), loadDepartments(), loadDocCategories()]);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadKbs, loadDepartments, loadDocCategories]);

  useEffect(() => {
    if (!selectedKbId) {
      setDocs([]);
      setPerms([]);
      return;
    }
    let cancelled = false;
    (async () => {
      setError("");
      try {
        await loadDocs(selectedKbId);
        if (showPerms) await loadPerms(selectedKbId);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedKbId, showPerms, loadDocs, loadPerms]);

  /** processing 文档每 2s 拉 status，直至离开该状态。 */
  useEffect(() => {
    const processing = docs.filter((d) => d.status === "processing" && !d.deleted_at);
    if (!processing.length) return;
    const t = setInterval(async () => {
      try {
        const updates = await Promise.all(
          processing.map(async (d) => {
            const body = await apiJson<DocStatus>(
              `/api/v1/documents/${encodeURIComponent(d.id)}/status`,
            );
            if (body.code !== 0) return null;
            return { id: d.id, ...body.data };
          }),
        );
        setDocs((prev) =>
          prev.map((row) => {
            const u = updates.find((x) => x && x.id === row.id);
            if (!u) return row;
            return {
              ...row,
              status: u.status,
              hit_rate: u.hit_rate,
              qa_count: u.qa_count,
              stage: u.stage ?? row.stage,
              reason: u.reason ?? row.reason,
            };
          }),
        );
      } catch {
        /* 轮询失败不打断页面；可稍后刷新 */
      }
    }, 2000);
    return () => clearInterval(t);
  }, [docs]);

  async function createKb() {
    const name = kbName.trim();
    if (!name) {
      setError("请填写知识库名称");
      return;
    }
    if (kbVisibility === "department" && !kbOwnerDeptId) {
      setError("部门私有库须选择归属部门");
      return;
    }
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ id: string; name: string }>("/api/v1/knowledge-bases", {
        method: "POST",
        body: JSON.stringify({
          name,
          description: "",
          visibility: kbVisibility,
          owner_department_id: kbOwnerDeptId || null,
        }),
      });
      if (body.code !== 0) throw new Error(apiError(body, "创建失败"));
      setKbName("");
      setMsg(`已创建知识库 ${body.data.name}`);
      await loadKbs(body.data.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function onDeleteKb(kbId: string, kbNameHint: string) {
    if (!isPlatformAdmin) {
      setError("仅平台超管可删除知识库");
      return;
    }
    const okConfirm = window.confirm(
      `确认删除知识库「${kbNameHint}」？\n其下文档将一并软删并退出检索。`,
    );
    if (!okConfirm) return;
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ id: string; deleted_at: string | null }>(
        `/api/v1/knowledge-bases/${encodeURIComponent(kbId)}`,
        { method: "DELETE" },
      );
      if (body.code !== 0) throw new Error(apiError(body, "删除知识库失败"));
      setMsg(`已删除知识库 ${kbNameHint}`);
      if (selectedKbId === kbId) {
        setSelectedKbId("");
        setDocs([]);
        setPerms([]);
      }
      await loadKbs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除知识库失败");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(e: FormEvent) {
    e.preventDefault();
    if (!selectedKbId || !file) {
      setError("请选择知识库并选择文件");
      return;
    }
    if (!uploadCategoryIds.length) {
      setError("请至少选择一个文档分类");
      return;
    }
    const primary =
      primaryCategoryId && uploadCategoryIds.includes(primaryCategoryId)
        ? primaryCategoryId
        : uploadCategoryIds[0];
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const content_b64 = await fileToBase64(file);
      const body = await apiJson<{ document_id: string; status: string; oss_key: string }>(
        "/api/v1/documents/upload",
        {
          method: "POST",
          body: JSON.stringify({
            kb_id: selectedKbId,
            title: title || file.name,
            filename: file.name,
            content_b64,
            category_ids: uploadCategoryIds,
            primary_category_id: primary,
          }),
        },
      );
      if (body.code !== 0) throw new Error(apiError(body, "上传失败"));
      setMsg(`已上传 ${body.data.document_id}，状态 ${body.data.status}`);
      setFile(null);
      setTitle("");
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function onPublish(docId: string) {
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const doc = docs.find((d) => d.id === docId);
      // 面板上可能刚测出 100%，但保存问答会清空库内 hit_rate——发布前自动补测一次
      if (doc && doc.qa_count >= 5 && (doc.hit_rate == null || doc.hit_rate < 0.8)) {
        const hitBody = await apiJson<{
          hit_rate: number;
          hits: number;
          total: number;
        }>(`/api/v1/documents/${encodeURIComponent(docId)}/hit-test`, {
          method: "POST",
          body: "{}",
        });
        if (hitBody.code !== 0) throw new Error(apiError(hitBody, "发布前命中测试失败"));
        const rate = hitBody.data?.hit_rate;
        setLastHitRate(rate ?? null);
        if (rate == null || rate < 0.8) {
          throw new Error(
            `召回率 ${rate == null ? "—" : `${(rate * 100).toFixed(1)}%`} 未达 80%，无法发布`,
          );
        }
        await loadDocs(selectedKbId);
      }
      const body = await apiJson<{ id: string; status: string }>(
        `/api/v1/documents/${encodeURIComponent(docId)}/publish`,
        { method: "POST", body: "{}" },
      );
      if (body.code !== 0) throw new Error(apiError(body, "发布失败"));
      setMsg(`已发布 ${docId}`);
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "发布失败");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(docId: string) {
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson(`/api/v1/documents/${encodeURIComponent(docId)}`, {
        method: "DELETE",
      });
      if (body.code !== 0) throw new Error(apiError(body, "删除失败"));
      setMsg(`已软删 ${docId}`);
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function onRecover(docId: string) {
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson(`/api/v1/documents/${encodeURIComponent(docId)}/recover`, {
        method: "POST",
        body: "{}",
      });
      if (body.code !== 0) throw new Error(apiError(body, "恢复失败"));
      setMsg("已恢复元数据，需重新上传/入库后才能检索");
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复失败");
    } finally {
      setBusy(false);
    }
  }

  function openChunkPanel(docId: string) {
    setError("");
    setMsg("");
    setChunkDocId(docId);
    setQaDocId("");
    setQaItems([]);
    setHitDetails([]);
    setLastHitRate(null);
  }

  async function openQaPanel(docId: string) {
    setError("");
    setMsg("");
    setChunkDocId("");
    setQaDocId(docId);
    setHitDetails([]);
    setLastHitRate(null);
    setBusy(true);
    try {
      const body = await apiJson<{ items: QaItem[]; qa_count: number }>(
        `/api/v1/documents/${encodeURIComponent(docId)}/qa-pairs`,
      );
      if (body.code !== 0) throw new Error(apiError(body, "加载问答失败"));
      const items = body.data?.items || [];
      setQaItems(
        items.length
          ? items
          : [{ question: "", expected_chunk_hint: "" }],
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载问答失败");
    } finally {
      setBusy(false);
    }
  }

  async function onGenerateQa(docId: string) {
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{
        qa_count: number;
        hit_rate: number | null;
        items?: QaItem[];
        hit_test?: { details?: HitDetail[]; hit_rate?: number };
      }>(`/api/v1/documents/${encodeURIComponent(docId)}/generate-qa?run_hit_test=1`, {
        method: "POST",
        body: "{}",
      });
      if (body.code !== 0) throw new Error(apiError(body, "生成问答失败"));
      const rate = body.data?.hit_rate ?? body.data?.hit_test?.hit_rate ?? null;
      setQaDocId(docId);
      setQaItems(body.data?.items || []);
      setHitDetails(body.data?.hit_test?.details || []);
      setLastHitRate(rate);
      const pct = rate == null ? "—" : `${(rate * 100).toFixed(1)}%`;
      if (rate != null && rate < 0.8) {
        setMsg(`已生成 ${body.data?.qa_count} 条问答；召回率 ${pct}，未达 80%，请改题后重测或重新生成`);
      } else {
        setMsg(`已生成 ${body.data?.qa_count} 条问答；召回率 ${pct}`);
      }
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成问答失败");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveQa() {
    if (!qaDocId) return;
    const items = qaItems
      .map((q) => ({
        question: q.question.trim(),
        expected_chunk_hint: (q.expected_chunk_hint || "").trim() || null,
      }))
      .filter((q) => q.question);
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ qa_count: number }>(
        `/api/v1/documents/${encodeURIComponent(qaDocId)}/qa-pairs`,
        { method: "PUT", body: JSON.stringify({ items }) },
      );
      if (body.code !== 0) throw new Error(apiError(body, "保存问答失败"));
      setMsg(`已保存 ${body.data?.qa_count} 条问答（需重跑命中测试）`);
      setLastHitRate(null);
      setHitDetails([]);
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存问答失败");
    } finally {
      setBusy(false);
    }
  }

  async function onHitTest() {
    if (!qaDocId) return;
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{
        hit_rate: number;
        hits: number;
        total: number;
        details: HitDetail[];
      }>(`/api/v1/documents/${encodeURIComponent(qaDocId)}/hit-test`, {
        method: "POST",
        body: "{}",
      });
      if (body.code !== 0) throw new Error(apiError(body, "命中测试失败"));
      const rate = body.data?.hit_rate ?? null;
      setLastHitRate(rate);
      setHitDetails(body.data?.details || []);
      const pct = rate == null ? "—" : `${(rate * 100).toFixed(1)}%`;
      const miss = (body.data?.details || []).filter((d) => !d.hit).length;
      if (rate != null && rate < 0.8) {
        setMsg(`召回率 ${pct}（${body.data?.hits}/${body.data?.total}），未达 80%；未命中 ${miss} 条，请改 hint 后重测`);
      } else {
        setMsg(`召回率 ${pct}（${body.data?.hits}/${body.data?.total}）`);
      }
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "命中测试失败");
    } finally {
      setBusy(false);
    }
  }

  async function togglePerms() {
    const next = !showPerms;
    setShowPerms(next);
    if (next && selectedKbId) {
      setError("");
      try {
        await loadPerms(selectedKbId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载权限失败");
      }
    }
  }

  function addPermRow() {
    setPerms((prev) => [...prev, { subject_type: "user", subject_id: "" }]);
  }

  function updatePerm(idx: number, patch: Partial<PermItem>) {
    setPerms((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  }

  function removePerm(idx: number) {
    setPerms((prev) => prev.filter((_, i) => i !== idx));
  }

  async function savePerms() {
    if (!selectedKbId) return;
    const items = perms
      .map((p) => ({
        subject_type: p.subject_type,
        subject_id: p.subject_id.trim(),
      }))
      .filter((p) => p.subject_id);
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ items: PermItem[] }>(
        `/api/v1/knowledge-bases/${encodeURIComponent(selectedKbId)}/permissions`,
        {
          method: "PUT",
          body: JSON.stringify({ items }),
        },
      );
      if (body.code !== 0) throw new Error(apiError(body, "保存权限失败（仅超管）"));
      setPerms(body.data?.items || items);
      setMsg("权限已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存权限失败（仅超管）");
    } finally {
      setBusy(false);
    }
  }

  const filteredKbs = kbFilter.trim()
    ? kbs.filter(
        (k) =>
          k.name.toLowerCase().includes(kbFilter.trim().toLowerCase()) ||
          k.id.toLowerCase().includes(kbFilter.trim().toLowerCase()),
      )
    : kbs;

  const processingHint = docs.some((d) => d.status === "processing" && !d.deleted_at);

  return (
    <div className="kb-page">
      <AppNav />
      <main className="kb-main">
        <header className="kb-header">
          <h1>知识库管理</h1>
          <p className="kb-sub">
            建库 → 权限 → 上传入库 → 发布 / 软删恢复。Web 上传 → OSS → Celery（无 OpenIM）。
          </p>
          {msg ? <p className="kb-msg">{msg}</p> : null}
          {error ? <p className="err">{error}</p> : null}
          {processingHint ? (
            <p className="kb-hint">有文档仍处理中，每 2 秒自动刷新状态；可稍后手动刷新。</p>
          ) : null}
        </header>

        <div className="kb-layout">
          <aside className="kb-side">
            <h2>知识库</h2>
            <div className="field">
              <label htmlFor="kbFilter">搜索</label>
              <input
                id="kbFilter"
                value={kbFilter}
                onChange={(e) => setKbFilter(e.target.value)}
                placeholder="名称或 ID"
              />
            </div>
            <ul className="kb-list">
              {filteredKbs.length === 0 ? (
                <li className="kb-empty">暂无知识库（无权限或尚未创建）</li>
              ) : (
                filteredKbs.map((k) => (
                  <li key={k.id} className="kb-list-row">
                    <button
                      type="button"
                      className={
                        k.id === selectedKbId ? "kb-list-item is-active" : "kb-list-item"
                      }
                      onClick={() => setSelectedKbId(k.id)}
                    >
                      <span className="kb-list-name">{k.name}</span>
                      <span className="kb-list-meta">
                        {visibilityLabel(k.visibility)}
                        {k.owner_department_id
                          ? ` · ${deptNameById[k.owner_department_id] || k.owner_department_id}`
                          : ""}
                      </span>
                      <span className="kb-list-id">{k.id}</span>
                    </button>
                    {isPlatformAdmin ? (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm kb-list-del"
                        disabled={busy}
                        title="删除知识库"
                        onClick={(e) => {
                          e.stopPropagation();
                          void onDeleteKb(k.id, k.name);
                        }}
                      >
                        删除
                      </button>
                    ) : null}
                  </li>
                ))
              )}
            </ul>
            <div className="kb-create">
              <h3>新建知识库</h3>
              <div className="field">
                <label htmlFor="kbName">名称</label>
                <input
                  id="kbName"
                  value={kbName}
                  onChange={(e) => setKbName(e.target.value)}
                  placeholder="仅超管可创建"
                />
              </div>
              <div className="field">
                <label htmlFor="kbVisibility">可见性</label>
                <select
                  id="kbVisibility"
                  value={kbVisibility}
                  onChange={(e) =>
                    setKbVisibility(e.target.value as "public" | "department")
                  }
                >
                  <option value="public">公司内公开</option>
                  <option value="department">部门私有</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="kbOwnerDept">归属部门</label>
                <select
                  id="kbOwnerDept"
                  value={kbOwnerDeptId}
                  onChange={(e) => setKbOwnerDeptId(e.target.value)}
                >
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </div>
              <button className="btn" type="button" disabled={busy} onClick={createKb}>
                新建
              </button>
            </div>
          </aside>

          <section className="kb-panel">
            {!selectedKb ? (
              <p className="kb-empty">请选择或创建知识库</p>
            ) : (
              <>
                <div className="kb-panel-head">
                  <div>
                    <h2>{selectedKb.name}</h2>
                    <p className="kb-list-id">{selectedKb.id}</p>
                  </div>
                  <button
                    className="btn btn-ghost"
                    type="button"
                    disabled={busy}
                    onClick={togglePerms}
                  >
                    {showPerms ? "收起权限" : "权限"}
                  </button>
                </div>

                <div className="kb-upload">
                  <h3>上传文档</h3>
                  <form onSubmit={onUpload}>
                    <div className="field">
                      <label htmlFor="title">标题（可空，默认文件名）</label>
                      <input
                        id="title"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="file">文件</label>
                      <input
                        id="file"
                        type="file"
                        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                      />
                    </div>
                    <div className="field">
                      <span className="kb-field-label">文档分类（可多选）</span>
                      <div className="kb-cat-grid">
                        {leafCategories.map((c) => {
                          const checked = uploadCategoryIds.includes(c.id);
                          return (
                            <label key={c.id} className="kb-cat-item">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => {
                                  setUploadCategoryIds((prev) => {
                                    const next = checked
                                      ? prev.filter((x) => x !== c.id)
                                      : [...prev, c.id];
                                    if (!next.includes(primaryCategoryId)) {
                                      setPrimaryCategoryId(next[0] || "");
                                    }
                                    return next;
                                  });
                                }}
                              />
                              {c.name}
                              <span className="kb-list-id">{c.code}</span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                    <div className="field">
                      <label htmlFor="primaryCat">主分类</label>
                      <select
                        id="primaryCat"
                        value={
                          uploadCategoryIds.includes(primaryCategoryId)
                            ? primaryCategoryId
                            : uploadCategoryIds[0] || ""
                        }
                        onChange={(e) => setPrimaryCategoryId(e.target.value)}
                      >
                        {uploadCategoryIds.map((id) => {
                          const c = leafCategories.find((x) => x.id === id);
                          return (
                            <option key={id} value={id}>
                              {c?.name || id}
                            </option>
                          );
                        })}
                      </select>
                    </div>
                    <button
                      className="btn"
                      type="submit"
                      disabled={busy || !selectedKbId || !file}
                    >
                      {busy ? "处理中…" : "上传并入队"}
                    </button>
                  </form>
                </div>

                <div className="kb-docs">
                  <div className="kb-docs-head">
                    <h3>文档</h3>
                    <button
                      className="btn btn-ghost btn-sm"
                      type="button"
                      disabled={busy || !selectedKbId}
                      onClick={() => loadDocs(selectedKbId).catch((err) =>
                        setError(err instanceof Error ? err.message : "刷新失败"),
                      )}
                    >
                      刷新
                    </button>
                  </div>
                  <div className="kb-table-wrap">
                    <table className="kb-table">
                      <thead>
                        <tr>
                          <th>标题</th>
                          <th>分类</th>
                          <th>状态</th>
                          <th>hit_rate</th>
                          <th>qa_count</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {docs.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="kb-empty">
                              暂无文档
                            </td>
                          </tr>
                        ) : (
                          docs.map((d) => {
                            const soft = !!d.deleted_at;
                            return (
                              <tr key={d.id} className={soft ? "is-deleted" : undefined}>
                                <td>
                                  <div>{d.title}</div>
                                  <div className="kb-list-id">{d.id}</div>
                                  {d.status === "failed" && d.reason ? (
                                    <div className="kb-list-id">{d.reason}</div>
                                  ) : null}
                                </td>
                                <td>
                                  {(d.categories || []).length === 0 ? (
                                    <span className="kb-list-id">—</span>
                                  ) : (
                                    (d.categories || []).map((c) => (
                                      <span
                                        key={c.id}
                                        className={
                                          c.is_primary ? "kb-cat-tag is-primary" : "kb-cat-tag"
                                        }
                                      >
                                        {c.name}
                                      </span>
                                    ))
                                  )}
                                </td>
                                <td>{statusLabel(d)}</td>
                                <td>{fmtHitRate(d.hit_rate)}</td>
                                <td>{d.qa_count}</td>
                                <td className="kb-actions">
                                  {soft ? (
                                    <button
                                      className="btn btn-ghost btn-sm"
                                      type="button"
                                      disabled={busy}
                                      onClick={() => onRecover(d.id)}
                                    >
                                      恢复
                                    </button>
                                  ) : (
                                    <>
                                      {d.status === "pending_review" ||
                                      d.status === "ready" ? (
                                        <button
                                          className="btn btn-ghost btn-sm"
                                          type="button"
                                          disabled={busy}
                                          onClick={() => openChunkPanel(d.id)}
                                        >
                                          {d.status === "pending_review"
                                            ? "审切块"
                                            : "切块预览"}
                                        </button>
                                      ) : null}
                                      {d.status === "ready" || d.status === "published" ? (
                                        <>
                                          <button
                                            className="btn btn-ghost btn-sm"
                                            type="button"
                                            disabled={busy}
                                            onClick={() => onGenerateQa(d.id)}
                                          >
                                            生成问答并测
                                          </button>
                                          <button
                                            className="btn btn-ghost btn-sm"
                                            type="button"
                                            disabled={busy}
                                            onClick={() => openQaPanel(d.id)}
                                          >
                                            问答/命中
                                          </button>
                                        </>
                                      ) : null}
                                      {d.status === "ready" ? (
                                        <button
                                          className="btn btn-sm"
                                          type="button"
                                          disabled={busy}
                                          onClick={() => onPublish(d.id)}
                                        >
                                          发布
                                        </button>
                                      ) : null}
                                      {d.status !== "processing" ? (
                                        <button
                                          className="btn btn-ghost btn-sm"
                                          type="button"
                                          disabled={busy}
                                          onClick={() => onDelete(d.id)}
                                        >
                                          删除
                                        </button>
                                      ) : null}
                                    </>
                                  )}
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {chunkDocId ? (
                  <ChunkReviewPanel
                    documentId={chunkDocId}
                    docTitle={docs.find((d) => d.id === chunkDocId)?.title || chunkDocId}
                    docStatus={docs.find((d) => d.id === chunkDocId)?.status || ""}
                    busy={busy}
                    setBusy={setBusy}
                    onError={setError}
                    onMsg={setMsg}
                    onRefreshDocs={() => loadDocs(selectedKbId)}
                    onClose={() => setChunkDocId("")}
                  />
                ) : null}

                {qaDocId ? (
                  <div className="kb-perms">
                    <h3>问答 / 命中 · {qaDocId}</h3>
                    <p className="kb-hint">
                      发布要求：问答 ≥5 且召回率 ≥80%。未达标时可改 hint 重测，或重新生成。
                      {lastHitRate != null ? ` 当前测试召回率 ${fmtHitRate(lastHitRate)}` : ""}
                    </p>
                    {qaItems.map((q, idx) => (
                      <div className="kb-perm-row" key={`qa-${idx}`}>
                        <input
                          value={q.question}
                          placeholder="question"
                          onChange={(e) =>
                            setQaItems((prev) =>
                              prev.map((row, i) =>
                                i === idx ? { ...row, question: e.target.value } : row,
                              ),
                            )
                          }
                        />
                        <input
                          value={q.expected_chunk_hint || ""}
                          placeholder="expected_chunk_hint（原文短句）"
                          onChange={(e) =>
                            setQaItems((prev) =>
                              prev.map((row, i) =>
                                i === idx
                                  ? { ...row, expected_chunk_hint: e.target.value }
                                  : row,
                              ),
                            )
                          }
                        />
                        <button
                          className="btn btn-ghost btn-sm"
                          type="button"
                          onClick={() =>
                            setQaItems((prev) => prev.filter((_, i) => i !== idx))
                          }
                        >
                          删行
                        </button>
                      </div>
                    ))}
                    <div className="kb-perm-actions">
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={() =>
                          setQaItems((prev) => [
                            ...prev,
                            { question: "", expected_chunk_hint: "" },
                          ])
                        }
                      >
                        增行
                      </button>
                      <button
                        className="btn"
                        type="button"
                        disabled={busy}
                        onClick={onSaveQa}
                      >
                        保存问答
                      </button>
                      <button
                        className="btn"
                        type="button"
                        disabled={busy}
                        onClick={onHitTest}
                      >
                        重跑命中
                      </button>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        disabled={busy}
                        onClick={() => onGenerateQa(qaDocId)}
                      >
                        重新生成并测
                      </button>
                      <button
                        className="btn btn-ghost"
                        type="button"
                        onClick={() => {
                          setQaDocId("");
                          setQaItems([]);
                          setHitDetails([]);
                          setLastHitRate(null);
                        }}
                      >
                        关闭
                      </button>
                    </div>
                    {hitDetails.length ? (
                      <div style={{ marginTop: "1rem" }}>
                        <h4>命中明细</h4>
                        {hitDetails.map((d, i) => (
                          <div key={`hit-${i}`} className={d.hit ? undefined : "err"}>
                            <strong>{d.hit ? "命中" : "未命中"}</strong> · {d.question}
                            {d.expected_chunk_hint ? (
                              <div className="kb-hint">hint: {d.expected_chunk_hint}</div>
                            ) : null}
                            {!d.hit && d.top_contents?.length ? (
                              <div className="kb-hint">
                                召回预览: {d.top_contents[0]}
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {showPerms ? (
                  <div className="kb-perms">
                    <h3>权限（并集）</h3>
                    <p className="kb-hint">
                      {canEditPerms
                        ? "保存为全量替换；仅平台超管可编辑。"
                        : "只读查看；仅平台超管可增删/保存权限。"}
                    </p>
                    {perms.length === 0 ? (
                      <p className="kb-empty">暂无权限条目</p>
                    ) : (
                      perms.map((p, idx) => (
                        <div className="kb-perm-row" key={`perm-${idx}`}>
                          <select
                            value={p.subject_type}
                            disabled={!canEditPerms}
                            onChange={(e) =>
                              updatePerm(idx, {
                                subject_type: e.target.value as PermItem["subject_type"],
                              })
                            }
                          >
                            <option value="user">user</option>
                            <option value="department">department</option>
                            <option value="role">role</option>
                          </select>
                          <input
                            value={p.subject_id}
                            disabled={!canEditPerms}
                            onChange={(e) =>
                              updatePerm(idx, { subject_id: e.target.value })
                            }
                            placeholder="subject_id"
                          />
                          {canEditPerms ? (
                            <button
                              className="btn btn-ghost btn-sm"
                              type="button"
                              onClick={() => removePerm(idx)}
                            >
                              删行
                            </button>
                          ) : null}
                        </div>
                      ))
                    )}
                    {canEditPerms ? (
                      <div className="kb-perm-actions">
                        <button className="btn btn-ghost" type="button" onClick={addPermRow}>
                          增行
                        </button>
                        <button
                          className="btn"
                          type="button"
                          disabled={busy}
                          onClick={savePerms}
                        >
                          保存权限
                        </button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
