/**
 * chatProcess 纯函数单测：完成后过程默认展开。
 * @author 赵振明
 * @date 2026-09-07 13:16:34
 */
// @ts-nocheck — Node --test 需 .ts 扩展名导入，与 bundler tsconfig 不兼容

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  applyProcessEvent,
  emptyProcess,
  hasVisibleProcess,
  retainProcessAfterDone,
} from "./chatProcess.ts";

describe("chatProcess 默认展开", () => {
  it("emptyProcess 默认 collapsed=false", () => {
    assert.equal(emptyProcess().collapsed, false);
  });

  it("applyProcessEvent 过程中保持展开", () => {
    let p = emptyProcess();
    p = applyProcessEvent(p, "stage", {
      id: "plan",
      label: "规划",
      status: "running",
    });
    assert.equal(p.collapsed, false);
    p = applyProcessEvent(p, "thought_delta", {
      delta: "正在分析…",
      source: "narration",
    });
    assert.equal(p.collapsed, false);
    p = applyProcessEvent(p, "thought_delta", {
      delta: "深度思考片段",
      source: "model",
    });
    assert.equal(p.collapsed, false);
  });

  it("retainProcessAfterDone 保留可见过程且强制展开", () => {
    const withThought = {
      stages: [{ id: "plan", label: "规划", status: "done" as const }],
      thought: "已完成规划",
      modelThought: "",
      collapsed: true,
    };
    const kept = retainProcessAfterDone(withThought);
    assert.ok(kept);
    assert.equal(kept.collapsed, false);
    assert.equal(kept.thought, "已完成规划");
    assert.equal(hasVisibleProcess(kept), true);
  });

  it("retainProcessAfterDone 对空过程返回原值", () => {
    assert.equal(retainProcessAfterDone(undefined), undefined);
    const empty = emptyProcess();
    assert.equal(retainProcessAfterDone(empty), empty);
  });
});
