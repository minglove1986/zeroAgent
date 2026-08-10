/**
 * 过程面板：模型思考（独立样式）+ 合成叙述 + 阶段胶囊。
 * @author 赵振明
 * @date 2026-08-03 16:17:37
 */
"use client";

import type { LiveProcess } from "@/lib/chatProcess";

type Props = {
  process: LiveProcess;
  onToggle: () => void;
};

export function ProcessPanel({ process, onToggle }: Props) {
  const narration = (process.thought || "").trim();
  const modelThought = (process.modelThought || "").trim();
  const hasThought = Boolean(narration || modelThought);
  if (!process.stages.length && !hasThought) return null;

  const running = process.stages.some((s) => s.status === "running");
  const previewSource = modelThought || narration;
  const thoughtPreview =
    previewSource.split("\n").filter(Boolean)[0]?.slice(0, 80) || "";

  return (
    <div
      className={`process-panel${running ? " is-live" : ""}`}
      data-testid="process-panel"
    >
      <div className="process-panel-title">
        {running ? "处理中…" : "处理过程"}
      </div>
      {hasThought ? (
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
            <div className="process-thought-body">
              {modelThought ? (
                <div className="process-thought is-model" aria-label="模型思考">
                  {modelThought}
                </div>
              ) : null}
              {narration ? (
                <div className="process-thought is-narration" aria-label="过程叙述">
                  {narration}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
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
    </div>
  );
}
