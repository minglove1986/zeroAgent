/**
 * 过程面板：阶段胶囊 + 可折叠合成思考。
 * @author 赵振明
 * @date 2026-07-27 14:45:31
 */
"use client";

import type { LiveProcess } from "@/lib/chatProcess";

type Props = {
  process: LiveProcess;
  onToggle: () => void;
};

export function ProcessPanel({ process, onToggle }: Props) {
  if (!process.stages.length && !process.thought) return null;

  const running = process.stages.some((s) => s.status === "running");
  const thoughtPreview = process.thought.trim().split("\n").filter(Boolean).slice(-1)[0] || "";

  return (
    <div
      className={`process-panel${running ? " is-live" : ""}`}
      data-testid="process-panel"
    >
      <div className="process-panel-title">
        {running ? "处理中…" : "处理过程"}
      </div>
      {process.stages.length ? (
        <div className="process-stages" aria-label="对话阶段">
          {process.stages.map((s) => (
            <span
              key={s.id}
              className={`process-stage is-${s.status}`}
              title={s.status}
            >
              {s.label}
              {s.status === "running" ? "…" : s.status === "done" ? " ✓" : ""}
            </span>
          ))}
        </div>
      ) : null}
      {process.thought ? (
        <div className="process-thought-wrap">
          <button
            type="button"
            className="process-thought-toggle"
            onClick={onToggle}
            aria-expanded={!process.collapsed}
          >
            {process.collapsed ? "展开思考过程" : "收起思考过程"}
          </button>
          {process.collapsed && thoughtPreview ? (
            <div className="process-thought-preview" title="点击上方展开全文">
              {thoughtPreview}
            </div>
          ) : null}
          {!process.collapsed ? (
            <div className="process-thought">{process.thought}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
