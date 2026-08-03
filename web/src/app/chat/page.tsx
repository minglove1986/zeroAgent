/**
 * 系统对话页：豆包式布局 — 侧栏历史会话 + 主区消息流 + 悬浮输入卡片。
 * 支持流式中排队发送、停止生成、supersede pending 卡与焦点恢复。
 * @author 赵振明
 * @date 2026-07-30 15:29:48
 */
"use client";

import {
  ChangeEvent,
  FormEvent,
  KeyboardEvent,
  MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import { AppNav } from "@/components/AppNav";
import { BrandMark } from "@/components/BrandMark";
import { MarkdownBody } from "@/components/MarkdownBody";
import { ProcessPanel } from "@/components/ProcessPanel";
import { apiJson } from "@/lib/api";
import {
  applyProcessEvent,
  collapseProcess,
  emptyProcess,
  hasVisibleProcess,
  type LiveProcess,
} from "@/lib/chatProcess";
import {
  CHAT_SEND_QUEUE_MAX,
  clearQueue,
  dequeueForSend,
  enqueue,
  markStatus,
  removeQueued,
  type QueueItem,
} from "@/lib/chatSendQueue";
import { postSse } from "@/lib/sse";

const STORAGE_KEY = "za_active_conversation_id";
/** 发请求后、首个 SSE 前的本地占位阶段，避免出队续发时「假闲」 */
const PENDING_STAGE_ID = "_pending";

type StreamPhase = "idle" | "streaming" | "stopping" | "draining";

type CardPayload = {
  card_id: string;
  type: string;
  title: string;
  body_md?: string;
  required?: boolean;
  options?: { id: string; label: string }[];
};

type ChatItem =
  | {
      kind: "user";
      text: string;
      queueLocalId?: string;
      queueStatus?: "queued" | "sending" | "failed";
    }
  | {
      kind: "assistant";
      text: string;
      messageId?: string;
      rating?: "up" | "down";
      citations?: { title?: string; snippet?: string }[];
      process?: LiveProcess;
      stopped?: boolean;
    }
  | { kind: "system"; text: string }
  | { kind: "card"; card: CardPayload; skipped?: boolean };

type UsageInfo = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  source?: string;
};

type ContextInfo = {
  tokens: number;
  window_tokens: number;
};

type ConvListItem = {
  id: string;
  title: string | null;
  preview: string;
  user_id?: string;
};

type ConvDetail = {
  id: string;
  title: string | null;
  agent_id?: string | null;
  selected_model?: string | null;
  messages: { id: string; role: string; content: string | null; content_type?: string }[];
  pending_cards: CardPayload[];
  feedbacks?: Record<string, { rating: string; comment?: string | null }>;
  usage_summary?: UsageInfo;
  context?: ContextInfo;
};

type ModelOption = {
  model_name: string;
  display_name: string;
  max_input_tokens?: number | null;
  is_system_default?: boolean;
};

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function stripOldProcess(items: ChatItem[]): ChatItem[] {
  return items.map((it) =>
    it.kind === "assistant" && it.process ? { ...it, process: undefined } : it,
  );
}

/**
 * 去掉发请求占位阶段；真实 stage / 正文到达后调用。
 */
function dropPendingStage(process: LiveProcess): LiveProcess {
  const stages = process.stages.filter((s) => s.id !== PENDING_STAGE_ID);
  if (stages.length === process.stages.length) return process;
  return { ...process, stages };
}

/**
 * 本轮尚未有助手气泡时，立刻插入「思考中」占位（覆盖 HTTP pending 空窗）。
 */
function ensurePendingAssistantProcess(items: ChatItem[]): ChatItem[] {
  return upsertAssistantProcess(items, (prev) => {
    if (prev.stages.some((s) => s.id === PENDING_STAGE_ID) || hasVisibleProcess(prev)) {
      return prev;
    }
    return {
      stages: [{ id: PENDING_STAGE_ID, label: "思考中", status: "running" }],
      thought: "",
      collapsed: false,
    };
  });
}

function upsertAssistantProcess(
  items: ChatItem[],
  mutator: (prev: LiveProcess) => LiveProcess,
  text = "",
): ChatItem[] {
  const next = [...items];
  for (let i = next.length - 1; i >= 0; i -= 1) {
    const it = next[i];
    if (it.kind === "assistant" && !it.messageId) {
      next[i] = {
        ...it,
        process: mutator(it.process ?? emptyProcess()),
      };
      return next;
    }
  }
  next.push({
    kind: "assistant",
    text,
    process: mutator(emptyProcess()),
  });
  return next;
}

/** 更新本轮未落库助手气泡正文，必须保留已有 process。 */
function patchPendingAssistantText(
  items: ChatItem[],
  text: string,
  citations?: { title?: string; snippet?: string }[],
): ChatItem[] {
  const next = [...items];
  for (let i = next.length - 1; i >= 0; i -= 1) {
    const it = next[i];
    if (it.kind === "assistant" && !it.messageId) {
      next[i] = {
        ...it,
        text,
        ...(citations ? { citations } : {}),
      };
      return next;
    }
  }
  next.push({
    kind: "assistant",
    text,
    ...(citations ? { citations } : {}),
  });
  return next;
}

/**
 * 将本轮未落库助手气泡标为已停止（保留半截正文）。
 */
function markLastAssistantStopped(items: ChatItem[]): ChatItem[] {
  const next = [...items];
  for (let i = next.length - 1; i >= 0; i -= 1) {
    const it = next[i];
    if (it.kind === "assistant" && !it.messageId) {
      next[i] = { ...it, stopped: true };
      return next;
    }
  }
  next.push({ kind: "assistant", text: "", stopped: true });
  return next;
}

/**
 * 判断错误是否为用户停止触发的 AbortError。
 */
function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === "AbortError";
}

function messagesToItems(
  messages: ConvDetail["messages"],
  pendingCards: CardPayload[],
  feedbacks?: ConvDetail["feedbacks"],
): ChatItem[] {
  const out: ChatItem[] = [];
  for (const m of messages) {
    const text = m.content || "";
    if (m.role === "user") {
      out.push({ kind: "user", text });
    } else if (m.role === "assistant") {
      const fb = feedbacks?.[m.id];
      const rating =
        fb?.rating === "up" || fb?.rating === "down" ? fb.rating : undefined;
      out.push({ kind: "assistant", text, messageId: m.id, rating });
    } else {
      out.push({ kind: "system", text });
    }
  }
  for (const card of pendingCards) {
    out.push({ kind: "card", card });
  }
  return out;
}

function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  const d = new Date(iso);
  const today = new Date();
  const ymd = (x: Date) => `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`;
  if (ymd(d) === ymd(today)) return "今天";
  if (ymd(d) === ymd(new Date(today.getTime() - 86_400_000))) return "昨天";
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  return d.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

export default function ChatPage() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [streamPhase, setStreamPhase] = useState<StreamPhase>("idle");
  const [sendQueue, setSendQueue] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pendingCard, setPendingCard] = useState<CardPayload | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [agents, setAgents] = useState<{ id: string; name: string; memory_access?: string }[]>(
    [],
  );
  const [agentId, setAgentId] = useState("");
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [lastUsage, setLastUsage] = useState<UsageInfo | null>(null);
  const [sessionUsage, setSessionUsage] = useState<UsageInfo | null>(null);
  const [contextInfo, setContextInfo] = useState<ContextInfo | null>(null);
  const [convList, setConvList] = useState<ConvListItem[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [deepThink, setDeepThink] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [hoverMsgId, setHoverMsgId] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<HTMLElement>(null);
  const restoredRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sendQueueRef = useRef<QueueItem[]>([]);
  const streamPhaseRef = useRef<StreamPhase>("idle");
  const pendingCardRef = useRef<CardPayload | null>(null);
  const sessionGenRef = useRef(0);

  const busy = streamPhase !== "idle";

  /**
   * 同步队列到 state + ref，避免出队时闭包陈旧。
   */
  function syncQueue(next: QueueItem[]) {
    sendQueueRef.current = next;
    setSendQueue(next);
  }

  /**
   * 发送/入队/回到可输入后，将焦点拉回输入框。
   */
  function focusComposer() {
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
    });
  }

  /**
   * 切会话/新对话前：中止当前流并清空本会话队列。
   */
  function resetStreamSession() {
    sessionGenRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    syncQueue(clearQueue());
    streamPhaseRef.current = "idle";
    setStreamPhase("idle");
  }

  /**
   * 本地将指定 pending 卡标为已跳过（服务端由 supersede 作废）。
   */
  function skipLocalPendingCard(cardId: string | null | undefined) {
    if (!cardId) return;
    setItems((prev) =>
      prev.map((it) =>
        it.kind === "card" && it.card.card_id === cardId
          ? { ...it, skipped: true }
          : it,
      ),
    );
    setPendingCard(null);
    pendingCardRef.current = null;
    setSelected([]);
  }

  useEffect(() => {
    pendingCardRef.current = pendingCard;
  }, [pendingCard]);

  useEffect(() => {
    streamPhaseRef.current = streamPhase;
  }, [streamPhase]);

  const persistConversationId = useCallback((id: string) => {
    setConversationId(id);
    try {
      sessionStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* ignore */
    }
  }, []);

  const refreshConvList = useCallback(async () => {
    try {
      const body = await apiJson<{ items: ConvListItem[] }>("/api/v1/conversations");
      if (body.code === 0) setConvList(body.data.items || []);
    } catch {
      /* 列表加载静默失败 */
    }
  }, []);

  const loadConversation = useCallback(
    async (id: string) => {
      const body = await apiJson<ConvDetail>(`/api/v1/conversations/${id}`);
      if (body.code !== 0) {
        throw new Error(body.message || "加载会话失败");
      }
      const pending = body.data.pending_cards || [];
      setItems(messagesToItems(body.data.messages || [], pending, body.data.feedbacks));
      setPendingCard(pending.length ? pending[pending.length - 1] : null);
      setSelected([]);
      setSessionUsage(body.data.usage_summary || null);
      setContextInfo(body.data.context || null);
      setLastUsage(null);
      setAgentId(body.data.agent_id || "");
      setSelectedModel(body.data.selected_model || "");
      persistConversationId(body.data.id);
    },
    [persistConversationId],
  );

  const applyContextWindowForModel = useCallback(
    (modelName: string, options: ModelOption[], tokens?: number) => {
      const hit = options.find((m) => m.model_name === modelName);
      const win = Number(hit?.max_input_tokens || 0);
      if (win > 0) {
        setContextInfo((prev) => ({
          tokens: typeof tokens === "number" ? tokens : prev?.tokens ?? 0,
          window_tokens: win,
        }));
        return;
      }
      // 目录无窗口时保留已有占用，窗口回落不瞎改（等服务端 context）
      if (typeof tokens === "number") {
        setContextInfo((prev) => ({
          tokens,
          window_tokens: prev?.window_tokens || 0,
        }));
      }
    },
    [],
  );

  const refreshModelOptions = useCallback(
    async (cid: string | null, aid: string | null) => {
      try {
        const qs = cid
          ? `conversation_id=${encodeURIComponent(cid)}`
          : aid
            ? `agent_id=${encodeURIComponent(aid)}`
            : "";
        // 无会话时拉系统对话白名单（不传 agent）
        const path = qs
          ? `/api/v1/llm-models/available?${qs}`
          : "/api/v1/llm-models/available";
        const body = await apiJson<{
          items: ModelOption[];
          selected_model?: string | null;
        }>(path);
        if (body.code !== 0 || !body.data) {
          setModelOptions([]);
          return;
        }
        const items = body.data.items || [];
        setModelOptions(items);
        const names = new Set(items.map((m) => m.model_name));
        const sel = (body.data.selected_model || "").trim();
        if (sel && !names.has(sel)) {
          // 会话里残留停用/未放行模型：清回默认，避免发送再炸
          setSelectedModel("");
          if (cid) {
            try {
              await apiJson(`/api/v1/conversations/${cid}`, {
                method: "PATCH",
                body: JSON.stringify({ selected_model: null }),
              });
            } catch {
              /* ignore */
            }
          }
          setError(
            `模型「${sel}」当前不可用，已自动切回默认，请选择可用模型后再发送`,
          );
          const def = items.find((m) => m.is_system_default) || items[0];
          if (def) {
            setSelectedModel(def.model_name);
            applyContextWindowForModel(def.model_name, items);
          }
        } else if (sel) {
          setSelectedModel(sel);
          applyContextWindowForModel(sel, items);
        } else if (items.length) {
          const def = items.find((m) => m.is_system_default) || items[0];
          applyContextWindowForModel(def.model_name, items);
        }
      } catch {
        setModelOptions([]);
      }
    },
    [applyContextWindowForModel],
  );

  useEffect(() => {
    void refreshModelOptions(conversationId, agentId || null);
  }, [conversationId, agentId, refreshModelOptions]);

  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    (async () => {
      setLoading(true);
      setError("");
      try {
        let saved: string | null = null;
        try {
          saved = sessionStorage.getItem(STORAGE_KEY);
        } catch {
          saved = null;
        }
        if (saved) {
          await loadConversation(saved);
        }
        await refreshConvList();
      } catch (err) {
        try {
          sessionStorage.removeItem(STORAGE_KEY);
        } catch {
          /* ignore */
        }
        setConversationId(null);
        setItems([]);
        setError(err instanceof Error ? err.message : "恢复会话失败，可重新开始");
      } finally {
        setLoading(false);
      }
    })();
  }, [loadConversation, refreshConvList]);

  useEffect(() => {
    void (async () => {
      try {
        const body = await apiJson<{
          items: { id: string; name: string; memory_access?: string }[];
        }>("/api/v1/agents");
        if (body.code === 0) setAgents(body.data.items || []);
      } catch {
        /* 可选：无 Agent 列表时仍可系统对话 */
      }
    })();
  }, []);

  /**
   * 确保有会话 id；建新后仅在 sessionGen 仍匹配时持久化，避免切会话竞态绑错 conversationId。
   * @author 赵振明
   * @date 2026-07-30 15:07:46
   */
  const ensureConversation = useCallback(
    async (gen: number) => {
      if (conversationId) return conversationId;
      const body = await apiJson<{ id: string }>("/api/v1/conversations", {
        method: "POST",
        body: JSON.stringify({
          title: "系统对话",
          agent_id: agentId || null,
        }),
      });
      if (body.code !== 0) throw new Error(body.message);
      const cid = body.data.id;
      // 建会话 await 期间若已切会话：禁止写 storage/state，中止本次发送
      if (sessionGenRef.current !== gen) {
        const err = new Error("session switched");
        err.name = "AbortError";
        throw err;
      }
      persistConversationId(cid);
      if (selectedModel) {
        try {
          await apiJson(`/api/v1/conversations/${cid}`, {
            method: "PATCH",
            body: JSON.stringify({ selected_model: selectedModel }),
          });
        } catch {
          /* 选模落库失败不阻断发送；发送时仍可能 40031 */
        }
      }
      void refreshConvList();
      return cid;
    },
    [
      conversationId,
      persistConversationId,
      agentId,
      selectedModel,
      refreshConvList,
    ],
  );

  /**
   * 仅滚动消息流容器，禁止 scrollIntoView 连带滚动 html/body，
   * 否则历史消息加载后会把顶部 AppNav 顶出视口（部分遮挡）。
   * @author 赵振明
   * @date 2026-07-22 17:01:23
   */
  useEffect(() => {
    const stream = streamRef.current;
    if (!stream) return;
    // 防御：若此前 scrollIntoView 已改过文档滚动位，先复位
    if (typeof window !== "undefined" && window.scrollY !== 0) {
      window.scrollTo(0, 0);
    }
    if (document.documentElement.scrollTop !== 0) {
      document.documentElement.scrollTop = 0;
    }
    if (document.body.scrollTop !== 0) {
      document.body.scrollTop = 0;
    }
    stream.scrollTo({ top: stream.scrollHeight, behavior: "smooth" });
  }, [items, pendingCard]);

  // 自动撑高 textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  async function startNewChat() {
    resetStreamSession();
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    setConversationId(null);
    setItems([]);
    setPendingCard(null);
    pendingCardRef.current = null;
    setSelected([]);
    setError("");
    setInput("");
    setLastUsage(null);
    setSessionUsage(null);
    setContextInfo(null);
    setSelectedModel("");
    setModelOptions([]);
    focusComposer();
  }

  /** 会话级切换模型；无会话时先记本地，建会话后再落库。 */
  async function onSelectModel(next: string) {
    if (streamPhaseRef.current !== "idle") return;
    const prev = selectedModel;
    setSelectedModel(next);
    applyContextWindowForModel(next, modelOptions);
    if (!conversationId) {
      setError("");
      return;
    }
    try {
      const body = await apiJson<{
        selected_model?: string | null;
        context?: ContextInfo;
      }>(`/api/v1/conversations/${conversationId}`, {
        method: "PATCH",
        body: JSON.stringify({ selected_model: next || null }),
      });
      if (body.code !== 0) {
        setSelectedModel(prev);
        applyContextWindowForModel(prev, modelOptions);
        setError(body.message || "切换模型失败");
        return;
      }
      setSelectedModel(body.data?.selected_model || "");
      if (body.data?.context) {
        setContextInfo(body.data.context);
      } else {
        applyContextWindowForModel(body.data?.selected_model || next, modelOptions);
      }
      setError("");
    } catch {
      setSelectedModel(prev);
      applyContextWindowForModel(prev, modelOptions);
      setError("切换模型失败");
    }
  }

  /**
   * 软删侧栏历史会话；若删当前会话则回到新对话。
   */
  async function deleteConversation(id: string, e: MouseEvent<HTMLButtonElement>) {
    e.stopPropagation();
    e.preventDefault();
    const okConfirm = window.confirm("确定删除该会话？删除后列表中不再显示。");
    if (!okConfirm) return;
    try {
      setError("");
      const body = await apiJson<{ deleted?: boolean }>(`/api/v1/conversations/${id}`, {
        method: "DELETE",
      });
      if (body.code !== 0) {
        throw new Error(body.message || "删除失败");
      }
      setConvList((prev) => prev.filter((c) => c.id !== id));
      if (conversationId === id) {
        await startNewChat();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除会话失败");
    }
  }

  async function selectConversation(id: string) {
    resetStreamSession();
    try {
      setLoading(true);
      setError("");
      await loadConversation(id);
      focusComposer();
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换会话失败");
    } finally {
      setLoading(false);
    }
  }

  /**
   * 取消仍为 queued 的排队项：调用 removeQueued，并移除对应乐观用户气泡。
   * @author 赵振明
   * @date 2026-07-30 15:00:12
   */
  function onRemoveQueued(localId: string) {
    const before = sendQueueRef.current;
    const next = removeQueued(before, localId);
    if (next.length === before.length) {
      return;
    }
    syncQueue(next);
    setItems((prev) =>
      prev.filter(
        (it) =>
          !(
            it.kind === "user" &&
            it.queueLocalId === localId &&
            it.queueStatus === "queued"
          ),
      ),
    );
    focusComposer();
  }

  /**
   * 失败项重试：标回 queued；空闲则立即泵送，流式中则等待 settle 出队，不堵后续。
   * @author 赵振明
   * @date 2026-07-30 15:00:12
   */
  function onRetryFailedQueue(localId: string) {
    const hit = sendQueueRef.current.find(
      (i) => i.localId === localId && i.status === "failed",
    );
    if (!hit) {
      return;
    }
    const next = markStatus(sendQueueRef.current, localId, "queued");
    syncQueue(next);
    setItems((prev) =>
      prev.map((it) =>
        it.kind === "user" && it.queueLocalId === localId
          ? { ...it, queueStatus: "queued" }
          : it,
      ),
    );

    if (streamPhaseRef.current !== "idle") {
      return;
    }
    if (sendQueueRef.current.some((i) => i.status === "sending")) {
      return;
    }
    const deq = dequeueForSend(sendQueueRef.current);
    if (!deq) {
      return;
    }
    const pc = pendingCardRef.current;
    if (pc) {
      skipLocalPendingCard(pc.card_id);
    }
    syncQueue(deq.rest);
    streamPhaseRef.current = "draining";
    setStreamPhase("draining");
    void sendText(deq.head.text, {
      skipUserBubble: true,
      queueLocalId: deq.head.localId,
    });
  }

  /**
   * 流结束后：有排队则出队串行发送，否则回到 idle 并聚焦输入框。
   */
  function settleAfterStream(
    gen: number,
    queueLocalId: string | undefined,
    outcome: "ok" | "failed" | "aborted",
  ) {
    if (gen !== sessionGenRef.current) {
      return;
    }
    if (abortRef.current) {
      abortRef.current = null;
    }

    let next = sendQueueRef.current;
    if (queueLocalId) {
      next = markStatus(
        next,
        queueLocalId,
        outcome === "failed" ? "failed" : "sent",
      );
      setItems((prev) =>
        prev.map((it) =>
          it.kind === "user" && it.queueLocalId === queueLocalId
            ? {
                ...it,
                queueStatus: outcome === "failed" ? "failed" : undefined,
              }
            : it,
        ),
      );
    }

    const deq = dequeueForSend(next);
    if (deq) {
      const pc = pendingCardRef.current;
      if (pc) {
        skipLocalPendingCard(pc.card_id);
      }
      syncQueue(deq.rest);
      streamPhaseRef.current = "draining";
      setStreamPhase("draining");
      void sendText(deq.head.text, {
        skipUserBubble: true,
        queueLocalId: deq.head.localId,
      });
      return;
    }

    syncQueue(next);
    streamPhaseRef.current = "idle";
    setStreamPhase("idle");
    focusComposer();
  }

  /**
   * 发起 messages/send（始终 supersede_pending_card）；支持 Abort 与出队续发。
   */
  async function sendText(
    text: string,
    opts?: { skipUserBubble?: boolean; queueLocalId?: string },
  ) {
    const gen = sessionGenRef.current;
    setError("");
    streamPhaseRef.current = "streaming";
    setStreamPhase("streaming");

    if (!opts?.skipUserBubble) {
      setItems((prev) =>
        ensurePendingAssistantProcess([
          ...stripOldProcess(prev),
          { kind: "user", text },
        ]),
      );
    } else if (opts.queueLocalId) {
      setItems((prev) =>
        ensurePendingAssistantProcess(
          stripOldProcess(
            prev.map((it) =>
              it.kind === "user" && it.queueLocalId === opts.queueLocalId
                ? { ...it, queueStatus: "sending" as const }
                : it,
            ),
          ),
        ),
      );
    } else {
      setItems((prev) => ensurePendingAssistantProcess(stripOldProcess(prev)));
    }

    let assistant = "";
    const citations: { title?: string; snippet?: string }[] = [];
    let outcome: "ok" | "failed" | "aborted" = "ok";
    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const cid = await ensureConversation(gen);
      if (gen !== sessionGenRef.current) {
        return;
      }
      await postSse(
        "/api/v1/messages/send",
        {
          conversation_id: cid,
          content: text,
          supersede_pending_card: true,
        },
        (event, data) => {
          if (gen !== sessionGenRef.current) return;
          if (event === "stage" || event === "thought_delta") {
            flushSync(() => {
              setItems((prev) =>
                upsertAssistantProcess(prev, (p) =>
                  applyProcessEvent(dropPendingStage(p), event, data as Record<string, unknown>),
                ),
              );
            });
            return;
          }
          if (event === "content_delta") {
            assistant += String(data.delta ?? "");
            const snapshot = assistant;
            const cites = [...citations];
            flushSync(() => {
              setItems((prev) => {
                const withText = patchPendingAssistantText(prev, snapshot, cites);
                return upsertAssistantProcess(withText, (p) => dropPendingStage(p));
              });
            });
          } else if (event === "citation") {
            citations.push({
              title: String(data.title ?? ""),
              snippet: String(data.snippet ?? ""),
            });
          } else if (event === "card") {
            const card = data as unknown as CardPayload;
            setPendingCard(card);
            pendingCardRef.current = card;
            setSelected([]);
            setItems((prev) => [...prev, { kind: "card", card }]);
          } else if (event === "message_end") {
            const status = String(data.status ?? "");
            const mid = data.message_id ? String(data.message_id) : "";
            if (data.usage && typeof data.usage === "object") {
              const u = data.usage as UsageInfo;
              setLastUsage(u);
              setSessionUsage((prev) => ({
                prompt_tokens: (prev?.prompt_tokens || 0) + (u.prompt_tokens || 0),
                completion_tokens:
                  (prev?.completion_tokens || 0) + (u.completion_tokens || 0),
                total_tokens: (prev?.total_tokens || 0) + (u.total_tokens || 0),
                source: u.source,
              }));
            }
            if (data.context && typeof data.context === "object") {
              setContextInfo(data.context as ContextInfo);
            }
            if (mid) {
              setItems((prev) => {
                const next = [...prev];
                for (let i = next.length - 1; i >= 0; i -= 1) {
                  const it = next[i];
                  if (it.kind === "assistant" && !it.messageId) {
                    next[i] = {
                      ...it,
                      messageId: mid,
                      process: hasVisibleProcess(it.process)
                        ? collapseProcess(it.process!)
                        : it.process,
                    };
                    break;
                  }
                }
                return next;
              });
            } else {
              setItems((prev) =>
                upsertAssistantProcess(prev, (p) => collapseProcess(p)),
              );
            }
            if (status === "rejected_no_citation") {
              setItems((prev) => [
                ...prev,
                { kind: "system", text: "已拒绝展示：RAG 无有效 citation（D14）" },
              ]);
            }
            void refreshConvList();
          }
        },
        { signal: ac.signal },
      );
    } catch (err) {
      if (isAbortError(err)) {
        outcome = "aborted";
        if (gen === sessionGenRef.current) {
          setItems((prev) => markLastAssistantStopped(prev));
        }
      } else {
        outcome = "failed";
        if (gen === sessionGenRef.current) {
          setError(err instanceof Error ? err.message : "发送失败");
        }
      }
    } finally {
      settleAfterStream(gen, opts?.queueLocalId, outcome);
    }
  }

  /**
   * 停止当前 SSE；半截回复保留并由 settle 出队续发。
   */
  function onStop() {
    if (streamPhaseRef.current === "idle") return;
    streamPhaseRef.current = "stopping";
    setStreamPhase("stopping");
    abortRef.current?.abort();
    focusComposer();
  }

  async function onSubmit(e?: FormEvent, overrideText?: string) {
    e?.preventDefault();
    const text = (overrideText ?? input).trim();
    if (!text || loading) return;

    const phase = streamPhaseRef.current;
    const queuedCount = sendQueueRef.current.filter(
      (i) => i.status === "queued",
    ).length;
    if (queuedCount >= CHAT_SEND_QUEUE_MAX && phase !== "idle") {
      setError("最多排队 5 条，请等待或停止后发送");
      return;
    }

    setInput("");
    focusComposer();

    const pc = pendingCardRef.current;
    if (pc) {
      skipLocalPendingCard(pc.card_id);
    }

    const canDirect =
      phase === "idle" &&
      !sendQueueRef.current.some((i) => i.status === "sending");

    if (canDirect) {
      void sendText(text);
      return;
    }

    const r = enqueue(sendQueueRef.current, text);
    if (!r.ok) {
      setError("最多排队 5 条，请等待或停止后发送");
      setInput(text);
      return;
    }
    syncQueue(r.items);
    const last = r.items[r.items.length - 1];
    setItems((prev) => [
      ...prev,
      {
        kind: "user",
        text,
        queueLocalId: last.localId,
        queueStatus: "queued",
      },
    ]);
  }

  function onTextareaKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void onSubmit();
    }
  }

  async function onCardSubmit() {
    if (!pendingCard || !conversationId || streamPhaseRef.current !== "idle") {
      return;
    }
    const gen = sessionGenRef.current;
    const cardId = pendingCard.card_id;
    streamPhaseRef.current = "streaming";
    setStreamPhase("streaming");
    setError("");
    setItems((prev) => ensurePendingAssistantProcess(stripOldProcess(prev)));
    let assistant = "";
    const ac = new AbortController();
    abortRef.current = ac;
    let outcome: "ok" | "failed" | "aborted" = "ok";
    try {
      await postSse(
        "/api/v1/messages/card-action",
        {
          conversation_id: conversationId,
          card_id: cardId,
          payload: { selected_option_ids: selected },
        },
        (event, data) => {
          if (gen !== sessionGenRef.current) return;
          if (event === "stage" || event === "thought_delta") {
            flushSync(() => {
              setItems((prev) =>
                upsertAssistantProcess(prev, (p) =>
                  applyProcessEvent(
                    dropPendingStage(p),
                    event,
                    data as Record<string, unknown>,
                  ),
                ),
              );
            });
            return;
          }
          if (event === "content_delta") {
            assistant += String(data.delta ?? "");
            const snapshot = assistant;
            flushSync(() => {
              setItems((prev) => {
                const withText = patchPendingAssistantText(prev, snapshot);
                return upsertAssistantProcess(withText, (p) => dropPendingStage(p));
              });
            });
            return;
          }
          if (event === "message_end" && data.message_id) {
            const mid = String(data.message_id);
            setItems((prev) => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i -= 1) {
                const it = next[i];
                if (it.kind === "assistant" && !it.messageId) {
                  next[i] = {
                    ...it,
                    messageId: mid,
                    process: hasVisibleProcess(it.process)
                      ? collapseProcess(it.process!)
                      : it.process,
                  };
                  break;
                }
              }
              return next;
            });
          }
        },
        { signal: ac.signal },
      );
      if (gen === sessionGenRef.current) {
        setPendingCard(null);
        pendingCardRef.current = null;
        setSelected([]);
      }
    } catch (err) {
      if (isAbortError(err)) {
        outcome = "aborted";
        if (gen === sessionGenRef.current) {
          setItems((prev) => markLastAssistantStopped(prev));
        }
      } else {
        outcome = "failed";
        if (gen === sessionGenRef.current) {
          setError(err instanceof Error ? err.message : "提交卡片失败");
        }
      }
    } finally {
      settleAfterStream(gen, undefined, outcome);
    }
  }

  async function submitFeedback(
    messageId: string,
    rating: "up" | "down",
    comment?: string,
  ) {
    setError("");
    try {
      const body = await apiJson<{ rating: string }>(
        `/api/v1/messages/${messageId}/feedback`,
        {
          method: "POST",
          body: JSON.stringify({ rating, comment: comment || null }),
        },
      );
      if (body.code !== 0) throw new Error(body.message);
      setItems((prev) =>
        prev.map((it) =>
          it.kind === "assistant" && it.messageId === messageId
            ? { ...it, rating }
            : it,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "反馈失败");
    }
  }

  async function retryMessage(messageId: string) {
    if (streamPhaseRef.current !== "idle" || pendingCardRef.current) return;
    const gen = sessionGenRef.current;
    setError("");
    streamPhaseRef.current = "streaming";
    setStreamPhase("streaming");
    setItems((prev) => ensurePendingAssistantProcess(stripOldProcess(prev)));
    let assistant = "";
    const ac = new AbortController();
    abortRef.current = ac;
    let outcome: "ok" | "failed" | "aborted" = "ok";
    try {
      await postSse(
        `/api/v1/messages/${messageId}/retry`,
        {},
        (event, data) => {
          if (gen !== sessionGenRef.current) return;
          if (event === "stage" || event === "thought_delta") {
            flushSync(() => {
              setItems((prev) =>
                upsertAssistantProcess(prev, (p) =>
                  applyProcessEvent(
                    dropPendingStage(p),
                    event,
                    data as Record<string, unknown>,
                  ),
                ),
              );
            });
            return;
          }
          if (event === "content_delta") {
            assistant += String(data.delta ?? "");
            const snapshot = assistant;
            flushSync(() => {
              setItems((prev) => {
                const withText = patchPendingAssistantText(prev, snapshot);
                return upsertAssistantProcess(withText, (p) => dropPendingStage(p));
              });
            });
            return;
          }
          if (event === "card") {
            const card = data as unknown as CardPayload;
            setPendingCard(card);
            pendingCardRef.current = card;
            setSelected([]);
            setItems((prev) => [...prev, { kind: "card", card }]);
            return;
          }
          if (event === "message_end" && data.message_id) {
            const mid = String(data.message_id);
            setItems((prev) => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i -= 1) {
                const it = next[i];
                if (it.kind === "assistant" && !it.messageId) {
                  next[i] = {
                    ...it,
                    messageId: mid,
                    process: hasVisibleProcess(it.process)
                      ? collapseProcess(it.process!)
                      : it.process,
                  };
                  break;
                }
              }
              return next;
            });
          }
        },
        { signal: ac.signal },
      );
    } catch (err) {
      if (isAbortError(err)) {
        outcome = "aborted";
        if (gen === sessionGenRef.current) {
          setItems((prev) => markLastAssistantStopped(prev));
        }
      } else {
        outcome = "failed";
        if (gen === sessionGenRef.current) {
          setError(err instanceof Error ? err.message : "重试失败");
        }
      }
    } finally {
      settleAfterStream(gen, undefined, outcome);
    }
  }

  const groups = useMemo(() => {
    const today: ConvListItem[] = [];
    const yesterday: ConvListItem[] = [];
    const earlier: ConvListItem[] = [];
    for (const c of convList) {
      const title = c.title?.trim() || c.preview?.slice(0, 24) || "新会话";
      const item: ConvListItem = { ...c, title };
      earlier.push(item); // 简化：后端未返回时间，统统归入"更早"
      void today;
      void yesterday;
    }
    return { today, yesterday, earlier };
  }, [convList]);

  return (
    <div className="chat-shell">
      <AppNav />

      <div className="chat-body">
        {/* ====== 左侧：会话侧边栏（豆包风） ====== */}
        <aside className={`chat-sidebar ${sidebarOpen ? "is-open" : "is-collapsed"}`}>
          <div className="sidebar-inner">
            <button
              type="button"
              className="btn-new-chat"
              onClick={startNewChat}
            >
              <span className="ico-plus" aria-hidden>＋</span>
              <span>新建对话</span>
            </button>

            <div className="sidebar-section">
              <div className="sidebar-title">历史会话</div>
              {convList.length === 0 ? (
                <div className="sidebar-empty">暂无历史会话</div>
              ) : (
                <ul className="conv-list">
                  {convList.map((c) => (
                    <li
                      key={c.id}
                      className={`conv-item ${conversationId === c.id ? "is-active" : ""}`}
                      onClick={() => void selectConversation(c.id)}
                    >
                      <div className="conv-item-main">
                        <div className="conv-item-title">
                          {c.title?.trim() || c.preview?.slice(0, 24) || "新会话"}
                        </div>
                        <div className="conv-item-preview">
                          {c.preview?.slice(0, 38) || "—"}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="conv-item-delete"
                        title="删除会话"
                        aria-label="删除会话"
                        onClick={(ev) => void deleteConversation(c.id, ev)}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="sidebar-footer">
              <div className="sidebar-tip">
                <div className="sidebar-tip-title">试试这样问</div>
                <ul>
                  <li>「我要请假」→ 触发提问卡</li>
                  <li>「帮我看看唐亮是谁」→ 意图漏斗 → RAG</li>
                  <li>「查询知识库，找下唐亮」→ RAG + citation</li>
                  <li>「查知识库：差旅报销」→ RAG + citation</li>
                  <li>「查知识库：差旅报销（无引用）」→ 验证 D14 拒展</li>
                </ul>
              </div>
            </div>
          </div>
        </aside>

        {/* ====== 右侧：主对话区 ====== */}
        <main className="chat-main">
          {/* 顶栏 */}
          <header className="chat-header">
            <button
              type="button"
              className="icon-btn"
              onClick={() => setSidebarOpen((v) => !v)}
              aria-label={sidebarOpen ? "收起侧栏" : "展开侧栏"}
              title={sidebarOpen ? "收起侧栏" : "展开侧栏"}
            >
              {sidebarOpen ? "«" : "»"}
            </button>

            <div className="chat-header-title">
              {conversationId ? "系统对话" : "新的对话"}
            </div>

            <div className="chat-header-right">
              {!conversationId ? (
                <label className="agent-picker">
                  <span className="agent-picker-label">Agent</span>
                  <select
                    value={agentId}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) =>
                      setAgentId(e.target.value)
                    }
                    disabled={busy}
                  >
                    <option value="">系统对话（默认）</option>
                    {agents.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <span className="usage-tag" title="本轮 / 累计 / 上下文 tokens">
                  {lastUsage
                    ? `本轮 ${fmtTokens(lastUsage.total_tokens || 0)}${
                        lastUsage.source === "estimated" ? "·估" : ""
                      }`
                    : ""}
                  {sessionUsage ? ` · 累计 ${fmtTokens(sessionUsage.total_tokens || 0)}` : ""}
                  {contextInfo
                    ? ` · 上下文 ${fmtTokens(contextInfo.tokens)}/${fmtTokens(
                        contextInfo.window_tokens,
                      )}`
                    : ""}
                </span>
              )}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={startNewChat}
              >
                新对话
              </button>
            </div>
          </header>

          {/* 中部：消息流 */}
          <section ref={streamRef} className="chat-stream">
            {loading ? (
              <div className="chat-hint">正在恢复会话…</div>
            ) : null}

            {!loading && items.length === 0 ? (
              <div className="chat-empty">
                <div className="chat-empty-logo">
                  <BrandMark size={64} priority />
                </div>
                <h2 className="chat-empty-title">你好，我是 ZeroAgent</h2>
                <p className="chat-empty-sub">
                  试试：「我要请假」「帮我看看唐亮是谁」「查知识库：差旅报销」
                </p>
                <div className="chat-empty-cards">
                  {[
                    { tag: "请假", text: "我要请假 1 天，从下周三开始" },
                    { tag: "查人", text: "帮我看看唐亮是谁" },
                    { tag: "查知识库", text: "查询知识库，找下唐亮这个人的资料" },
                    { tag: "查知识库", text: "查知识库：差旅报销" },
                    { tag: "拒展示", text: "查知识库：差旅报销（无引用）" },
                    { tag: "Agent", text: "让 Agent「财务助理」帮忙处理报销" },
                  ].map((s) => (
                    <button
                      key={s.tag}
                      type="button"
                      className="suggest-card"
                      onClick={() => {
                        if (loading) return;
                        void onSubmit(undefined, s.text);
                      }}
                    >
                      <span className="suggest-tag">{s.tag}</span>
                      <span className="suggest-text">{s.text}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {items.map((item, idx) => {
              if (item.kind === "user") {
                return (
                  <div key={idx} className="msg-row msg-user">
                    <div className="msg-bubble">
                      {item.text}
                      {item.queueStatus === "queued" ? (
                        <>
                          <span className="chat-queue-tag">排队中</span>
                          {item.queueLocalId ? (
                            <button
                              type="button"
                              className="chat-queue-action"
                              aria-label="取消排队"
                              onClick={() => onRemoveQueued(item.queueLocalId!)}
                            >
                              取消
                            </button>
                          ) : null}
                        </>
                      ) : null}
                      {item.queueStatus === "sending" ? (
                        <span className="chat-queue-tag is-sending">发送中</span>
                      ) : null}
                      {item.queueStatus === "failed" ? (
                        <>
                          <span className="chat-queue-tag is-failed">发送失败</span>
                          {item.queueLocalId ? (
                            <button
                              type="button"
                              className="chat-queue-action is-retry"
                              aria-label="重试发送"
                              onClick={() => onRetryFailedQueue(item.queueLocalId!)}
                            >
                              重试
                            </button>
                          ) : null}
                        </>
                      ) : null}
                    </div>
                    <div className="msg-avatar msg-avatar-user" aria-hidden>
                      我
                    </div>
                  </div>
                );
              }
              if (item.kind === "assistant") {
                const id = item.messageId || `pending-${idx}`;
                return (
                  <div
                    key={idx}
                    className="msg-row msg-assistant"
                    onMouseEnter={() => setHoverMsgId(id)}
                    onMouseLeave={() => setHoverMsgId(null)}
                  >
                    <div className="msg-avatar msg-avatar-bot" aria-hidden>
                      Z
                    </div>
                    <div className="msg-body">
                      {hasVisibleProcess(item.process) ? (
                        <ProcessPanel
                          process={item.process!}
                          onToggle={() => {
                            setItems((prev) => {
                              const next = [...prev];
                              const cur = next[idx];
                              if (cur?.kind !== "assistant" || !cur.process) {
                                return prev;
                              }
                              next[idx] = {
                                ...cur,
                                process: {
                                  ...cur.process,
                                  collapsed: !cur.process.collapsed,
                                },
                              };
                              return next;
                            });
                          }}
                        />
                      ) : null}
                      <MarkdownBody className="msg-content" text={item.text} />
                      {item.stopped ? (
                        <div className="chat-stopped-hint">已停止</div>
                      ) : null}
                      {item.citations?.length ? (
                        <ul className="msg-citations">
                          {item.citations.map((c, i) => (
                            <li key={i}>
                              <span className="cite-title">{c.title}</span>
                              <span className="cite-snippet">{c.snippet}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {item.messageId ? (
                        <div
                          className={`msg-actions ${hoverMsgId === id ? "is-show" : ""}`}
                        >
                          <button
                            type="button"
                            className={`icon-btn ${item.rating === "up" ? "is-active" : ""}`}
                            disabled={busy}
                            onClick={() => submitFeedback(item.messageId!, "up")}
                            title="有用"
                          >
                            👍
                          </button>
                          <button
                            type="button"
                            className={`icon-btn ${item.rating === "down" ? "is-active" : ""}`}
                            disabled={busy}
                            onClick={() => {
                              const comment =
                                window.prompt("可选：补充不满意的原因", "") ?? undefined;
                              void submitFeedback(
                                item.messageId!,
                                "down",
                                comment?.trim() || undefined,
                              );
                            }}
                            title="无用"
                          >
                            👎
                          </button>
                          <button
                            type="button"
                            className="icon-btn"
                            disabled={busy || !!pendingCard}
                            onClick={() => void retryMessage(item.messageId!)}
                            title="重试"
                          >
                            ↻
                          </button>
                          <button
                            type="button"
                            className="icon-btn"
                            onClick={() => {
                              try {
                                void navigator.clipboard?.writeText(item.text);
                              } catch {
                                /* ignore */
                              }
                            }}
                            title="复制"
                          >
                            ⎘
                          </button>
                          {item.rating ? (
                            <span className="msg-feedback-tip">
                              已反馈：{item.rating === "up" ? "有用" : "无用"}
                            </span>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              }
              if (item.kind === "system") {
                return (
                  <div key={idx} className="msg-system">
                    <span>·</span>
                    <span>{item.text}</span>
                    <span>·</span>
                  </div>
                );
              }
              return (
                <div
                  key={idx}
                  className={`card-block${item.skipped ? " chat-card-skipped" : ""}`}
                >
                  <div className="card-block-title">📩 {item.card.title}</div>
                  {item.card.body_md ? (
                    <MarkdownBody className="card-block-desc" text={item.card.body_md} />
                  ) : null}
                  {item.skipped ? (
                    <p className="card-block-tip">已跳过</p>
                  ) : pendingCard?.card_id === item.card.card_id ? (
                    <>
                      <div className="card-options">
                        {(item.card.options || []).map((opt) => {
                          const on = selected.includes(opt.id);
                          return (
                            <button
                              key={opt.id}
                              type="button"
                              className={`chip ${on ? "is-on" : ""}`}
                              onClick={() => setSelected([opt.id])}
                              disabled={busy}
                            >
                              {opt.label}
                            </button>
                          );
                        })}
                      </div>
                      <button
                        type="button"
                        className="btn btn-sm"
                        style={{ marginTop: 12 }}
                        disabled={busy || selected.length === 0}
                        onClick={onCardSubmit}
                      >
                        提交并续跑
                      </button>
                    </>
                  ) : (
                    <p className="card-block-tip">卡片已处理或待答</p>
                  )}
                </div>
              );
            })}
            {busy && items[items.length - 1]?.kind === "user" ? (
              <div className="msg-row msg-assistant">
                <div className="msg-avatar msg-avatar-bot">Z</div>
                <div className="msg-body">
                  <div className="msg-typing">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>
              </div>
            ) : null}
            <div ref={bottomRef} />
          </section>

          {/* 底部：输入区（豆包式悬浮卡片） */}
          <div className="chat-composer-wrap">
            {error ? <div className="chat-error">{error}</div> : null}
            <form className="chat-composer" onSubmit={onSubmit}>
              <textarea
                ref={textareaRef}
                className="chat-textarea"
                placeholder={
                  pendingCard
                    ? "发消息将跳过当前卡片…"
                    : busy
                      ? "输入后 Enter 加入排队…"
                      : "发消息或输入 / 选择技能"
                }
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onTextareaKeyDown}
                rows={1}
                disabled={loading}
              />

              <div className="chat-tools">
                <label className="model-picker" title="本会话使用的模型">
                  <span className="model-picker-label">模型</span>
                  <select
                    value={selectedModel}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) =>
                      void onSelectModel(e.target.value)
                    }
                    disabled={busy || modelOptions.length === 0}
                  >
                    <option value="">默认</option>
                    {modelOptions.map((m) => (
                      <option key={m.model_name} value={m.model_name}>
                        {m.display_name || m.model_name}
                        {m.max_input_tokens
                          ? ` · ${fmtTokens(Number(m.max_input_tokens))}`
                          : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className={`tool-btn ${deepThink ? "is-on" : ""}`}
                  onClick={() => setDeepThink((v) => !v)}
                  title="占位开关（与上方「处理过程」面板无关）"
                >
                  <span className="tool-ico">🧠</span>
                  <span>深度思考</span>
                </button>
                <button
                  type="button"
                  className={`tool-btn ${webSearch ? "is-on" : ""}`}
                  onClick={() => setWebSearch((v) => !v)}
                  title="占位开关（未接入联网）"
                >
                  <span className="tool-ico">🌐</span>
                  <span>联网搜索</span>
                </button>
                <span className="tool-spacer" />
                <span className="tool-hint">
                  {busy
                    ? `Enter 排队${
                        sendQueue.filter((i) => i.status === "queued").length
                          ? `（${sendQueue.filter((i) => i.status === "queued").length}）`
                          : ""
                      } · 点击停止`
                    : "Enter 发送 · Shift+Enter 换行"}
                </span>
                {busy ? (
                  <button
                    type="button"
                    className="send-btn send-btn-stop"
                    onClick={onStop}
                    aria-label="停止"
                    title="停止生成"
                  >
                    ■
                  </button>
                ) : (
                  <button
                    type="submit"
                    className="send-btn"
                    disabled={loading || !input.trim()}
                    aria-label="发送"
                    title="发送"
                  >
                    ↑
                  </button>
                )}
              </div>
            </form>
          </div>
        </main>
      </div>
    </div>
  );
}
