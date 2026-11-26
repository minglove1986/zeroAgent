/**
 * 管理端全局系统通知：统一样式 + 提示音；业务侧只调 notify()。
 *
 * @author 赵振明
 * @date 2026-11-20 17:14:26
 */
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type SystemNotifyType = "success" | "info" | "warning" | "error";

export type SystemNotifyItem = {
  id: string;
  type: SystemNotifyType;
  title: string;
  description?: string;
  durationMs: number;
  createdAt: number;
};

export type SystemNotifyOptions = {
  type?: SystemNotifyType;
  title: string;
  description?: string;
  /** 默认 true */
  playSound?: boolean;
  /** 展示时长 ms，默认 5200；0 不自动关 */
  durationMs?: number;
};

type Ctx = {
  notify: (opts: SystemNotifyOptions) => string;
  dismiss: (id: string) => void;
};

const SystemNotifyContext = createContext<Ctx | null>(null);

const ACCENT: Record<SystemNotifyType, string> = {
  success: "#0f9f6e",
  info: "#2563eb",
  warning: "#d97706",
  error: "#dc2626",
};

/**
 * 用 Web Audio 合成短提示音（无静态资源依赖）。
 */
function playNotifyTone(type: SystemNotifyType) {
  try {
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    if (!AC) return;
    const ctx = new AC();
    const now = ctx.currentTime;
    const master = ctx.createGain();
    master.gain.value = 0.0001;
    master.connect(ctx.destination);

    const freqs =
      type === "success"
        ? [523.25, 659.25, 783.99]
        : type === "error"
          ? [220, 180]
          : type === "warning"
            ? [440, 392]
            : [493.88, 587.33];

    freqs.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const t0 = now + i * 0.09;
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(0.12, t0 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.22);
      osc.connect(g);
      g.connect(master);
      osc.start(t0);
      osc.stop(t0 + 0.24);
    });
    master.gain.exponentialRampToValueAtTime(0.18, now + 0.02);
    master.gain.exponentialRampToValueAtTime(0.0001, now + 0.55);
    window.setTimeout(() => {
      void ctx.close();
    }, 800);
  } catch {
    /* 浏览器策略或无 Audio 时静默 */
  }
}

/**
 * 全局系统通知 Provider。
 */
export function SystemNotifyProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<SystemNotifyItem[]>([]);
  const timers = useRef<Map<string, number>>(new Map());

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((x) => x.id !== id));
    const t = timers.current.get(id);
    if (t) {
      window.clearTimeout(t);
      timers.current.delete(id);
    }
  }, []);

  const notify = useCallback(
    (opts: SystemNotifyOptions) => {
      const id = `sn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
      const type = opts.type || "info";
      const durationMs =
        typeof opts.durationMs === "number" ? opts.durationMs : 5200;
      const item: SystemNotifyItem = {
        id,
        type,
        title: opts.title,
        description: opts.description,
        durationMs,
        createdAt: Date.now(),
      };
      setItems((prev) => [item, ...prev].slice(0, 5));
      if (opts.playSound !== false) playNotifyTone(type);
      if (durationMs > 0) {
        const t = window.setTimeout(() => dismiss(id), durationMs);
        timers.current.set(id, t);
      }
      return id;
    },
    [dismiss],
  );

  const value = useMemo(() => ({ notify, dismiss }), [notify, dismiss]);

  return (
    <SystemNotifyContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        style={{
          position: "fixed",
          top: 20,
          right: 20,
          zIndex: 11000,
          display: "flex",
          flexDirection: "column",
          gap: 10,
          width: 360,
          maxWidth: "calc(100vw - 32px)",
          pointerEvents: "none",
        }}
      >
        {items.map((it) => (
          <div
            key={it.id}
            role="status"
            onClick={() => dismiss(it.id)}
            style={{
              pointerEvents: "auto",
              cursor: "pointer",
              borderRadius: 12,
              overflow: "hidden",
              background: "rgba(15, 23, 42, 0.92)",
              color: "#f8fafc",
              boxShadow: "0 12px 40px rgba(15, 23, 42, 0.28)",
              border: "1px solid rgba(148, 163, 184, 0.25)",
              backdropFilter: "blur(10px)",
              display: "grid",
              gridTemplateColumns: "4px 1fr",
              animation: "za-sn-in 220ms ease-out",
            }}
          >
            <div style={{ background: ACCENT[it.type] }} />
            <div style={{ padding: "12px 14px 12px 12px" }}>
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  letterSpacing: "0.01em",
                  marginBottom: it.description ? 4 : 0,
                }}
              >
                {it.title}
              </div>
              {it.description ? (
                <div
                  style={{
                    fontSize: 12,
                    lineHeight: 1.5,
                    color: "rgba(226, 232, 240, 0.82)",
                  }}
                >
                  {it.description}
                </div>
              ) : null}
            </div>
          </div>
        ))}
      </div>
      <style>{`
        @keyframes za-sn-in {
          from {
            opacity: 0;
            transform: translateY(-8px) translateX(8px);
          }
          to {
            opacity: 1;
            transform: translateY(0) translateX(0);
          }
        }
      `}</style>
    </SystemNotifyContext.Provider>
  );
}

/**
 * 读取系统通知 API；未包裹 Provider 时安全降级为 no-op。
 */
export function useSystemNotify(): Ctx {
  const ctx = useContext(SystemNotifyContext);
  if (ctx) return ctx;
  return {
    notify: () => "",
    dismiss: () => undefined,
  };
}
