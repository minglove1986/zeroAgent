/**
 * 系统对话页：豆包式布局 — 侧栏历史会话 + 主区消息流 + 悬浮输入卡片。
 * @author 赵振明
 * @date 2026-07-23 15:35:48
 */
"use client";

import {
  ChangeEvent,
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import { AppNav } from "@/components/AppNav";
import { MarkdownBody } from "@/components/MarkdownBody";
import { apiJson } from "@/lib/api";
import { postSse } from "@/lib/sse";

const STORAGE_KEY = "za_active_conversation_id";

type CardPayload = {
  card_id: string;
  type: string;
  title: string;
  body_md?: string;
  required?: boolean;
  options?: { id: string; label: string }[];
};

type ChatItem =
  | { kind: "user"; text: string }
  | {
      kind: "assistant";
      text: string;
      messageId?: string;
      rating?: "up" | "down";
      citations?: { title?: string; snippet?: string }[];
    }
  | { kind: "system"; text: string }
  | { kind: "card"; card: CardPayload };

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
  messages: { id: string; role: string; content: string | null; content_type?: string }[];
  pending_cards: CardPayload[];
  feedbacks?: Record<string, { rating: string; comment?: string | null }>;
  usage_summary?: UsageInfo;
  context?: ContextInfo;
};

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
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
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pendingCard, setPendingCard] = useState<CardPayload | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [agents, setAgents] = useState<{ id: string; name: string; memory_access?: string }[]>(
    [],
  );
  const [agentId, setAgentId] = useState("");
  const [lastUsage, setLastUsage] = useState<UsageInfo | null>(null);
  const [sessionUsage, setSessionUsage] = useState<UsageInfo | null>(null);
  const [contextInfo, setContextInfo] = useState<ContextInfo | null>(null);
  const [convList, setConvList] = useState<ConvListItem[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [deepThink, setDeepThink] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [hoverMsgId, setHoverMsgId] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<HTMLSectionElement>(null);
  const restoredRef = useRef(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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
      persistConversationId(body.data.id);
    },
    [persistConversationId],
  );

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

  const ensureConversation = useCallback(async () => {
    if (conversationId) return conversationId;
    const body = await apiJson<{ id: string }>("/api/v1/conversations", {
      method: "POST",
      body: JSON.stringify({
        title: "系统对话",
        agent_id: agentId || null,
      }),
    });
    if (body.code !== 0) throw new Error(body.message);
    persistConversationId(body.data.id);
    void refreshConvList();
    return body.data.id;
  }, [conversationId, persistConversationId, agentId, refreshConvList]);

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
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    setConversationId(null);
    setItems([]);
    setPendingCard(null);
    setSelected([]);
    setError("");
    setInput("");
    setLastUsage(null);
    setSessionUsage(null);
    setContextInfo(null);
  }

  async function selectConversation(id: string) {
    if (busy) return;
    try {
      setLoading(true);
      setError("");
      await loadConversation(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换会话失败");
    } finally {
      setLoading(false);
    }
  }

  async function sendText(text: string) {
    setError("");
    setBusy(true);
    setItems((prev) => [...prev, { kind: "user", text }]);
    let assistant = "";
    const citations: { title?: string; snippet?: string }[] = [];

    try {
      const cid = await ensureConversation();
      await postSse(
        "/api/v1/messages/send",
        {
          conversation_id: cid,
          content: text,
        },
        (event, data) => {
          if (event === "content_delta") {
            assistant += String(data.delta ?? "");
            const snapshot = assistant;
            const cites = [...citations];
            flushSync(() => {
              setItems((prev) => {
                const next = [...prev];
                const last = next[next.length - 1];
                if (last?.kind === "assistant") {
                  next[next.length - 1] = {
                    kind: "assistant",
                    text: snapshot,
                    citations: cites,
                  };
                } else {
                  next.push({ kind: "assistant", text: snapshot, citations: cites });
                }
                return next;
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
                  if (it.kind === "assistant") {
                    next[i] = { ...it, messageId: mid };
                    break;
                  }
                }
                return next;
              });
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
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败");
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(e?: FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || busy || pendingCard || loading) return;
    setInput("");
    await sendText(text);
  }

  function onTextareaKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void onSubmit();
    }
  }

  async function onCardSubmit() {
    if (!pendingCard || !conversationId || busy) return;
    setBusy(true);
    setError("");
    let assistant = "";
    let started = false;
    try {
      await postSse(
        "/api/v1/messages/card-action",
        {
          conversation_id: conversationId,
          card_id: pendingCard.card_id,
          payload: { selected_option_ids: selected },
        },
        (event, data) => {
          if (event === "content_delta") {
            assistant += String(data.delta ?? "");
            const snapshot = assistant;
            flushSync(() => {
              setItems((prev) => {
                const next = [...prev];
                if (!started) {
                  started = true;
                  next.push({ kind: "assistant", text: snapshot });
                  return next;
                }
                for (let i = next.length - 1; i >= 0; i -= 1) {
                  if (next[i].kind === "assistant") {
                    next[i] = { kind: "assistant", text: snapshot };
                    break;
                  }
                }
                return next;
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
                if (it.kind === "assistant") {
                  next[i] = { ...it, messageId: mid };
                  break;
                }
              }
              return next;
            });
          }
        },
      );
      setPendingCard(null);
      setSelected([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交卡片失败");
    } finally {
      setBusy(false);
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
    if (busy || pendingCard) return;
    setError("");
    setBusy(true);
    let assistant = "";
    let started = false;
    try {
      await postSse(`/api/v1/messages/${messageId}/retry`, {}, (event, data) => {
        if (event === "content_delta") {
          assistant += String(data.delta ?? "");
          const snapshot = assistant;
          flushSync(() => {
            setItems((prev) => {
              const next = [...prev];
              if (!started) {
                started = true;
                next.push({ kind: "assistant", text: snapshot });
                return next;
              }
              for (let i = next.length - 1; i >= 0; i -= 1) {
                const it = next[i];
                if (it.kind === "assistant" && !it.messageId) {
                  next[i] = { ...it, text: snapshot };
                  break;
                }
              }
              return next;
            });
          });
          return;
        }
        if (event === "card") {
          const card = data as unknown as CardPayload;
          setPendingCard(card);
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
                next[i] = { ...it, messageId: mid };
                break;
              }
            }
            return next;
          });
        }
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "重试失败");
    } finally {
      setBusy(false);
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
              disabled={busy}
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
                      <div className="conv-item-title">
                        {c.title?.trim() || c.preview?.slice(0, 24) || "新会话"}
                      </div>
                      <div className="conv-item-preview">
                        {c.preview?.slice(0, 38) || "—"}
                      </div>
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
                disabled={busy}
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
                <div className="chat-empty-logo">ZA</div>
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
                        if (busy || pendingCard) return;
                        setInput(s.text);
                        setTimeout(() => void onSubmit(), 0);
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
                    <div className="msg-bubble">{item.text}</div>
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
                      <MarkdownBody className="msg-content" text={item.text} />
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
                <div key={idx} className="card-block">
                  <div className="card-block-title">📩 {item.card.title}</div>
                  {item.card.body_md ? (
                    <MarkdownBody className="card-block-desc" text={item.card.body_md} />
                  ) : null}
                  {pendingCard?.card_id === item.card.card_id ? (
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
                    ? "请先完成上方卡片…"
                    : "发消息或输入 / 选择技能"
                }
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onTextareaKeyDown}
                rows={1}
                disabled={busy || loading || !!pendingCard}
              />

              <div className="chat-tools">
                <button
                  type="button"
                  className={`tool-btn ${deepThink ? "is-on" : ""}`}
                  onClick={() => setDeepThink((v) => !v)}
                  disabled={busy || !!pendingCard}
                  title="深度思考（占位 UI，等后端联调）"
                >
                  <span className="tool-ico">🧠</span>
                  <span>深度思考</span>
                </button>
                <button
                  type="button"
                  className={`tool-btn ${webSearch ? "is-on" : ""}`}
                  onClick={() => setWebSearch((v) => !v)}
                  disabled={busy || !!pendingCard}
                  title="联网搜索（占位 UI，等后端联调）"
                >
                  <span className="tool-ico">🌐</span>
                  <span>联网搜索</span>
                </button>
                <span className="tool-spacer" />
                <span className="tool-hint">
                  Enter 发送 · Shift+Enter 换行
                </span>
                <button
                  type="submit"
                  className="send-btn"
                  disabled={
                    busy || loading || !!pendingCard || !input.trim()
                  }
                  aria-label="发送"
                  title="发送"
                >
                  ↑
                </button>
              </div>
            </form>
          </div>
        </main>
      </div>
    </div>
  );
}
