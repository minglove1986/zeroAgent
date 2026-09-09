/**
 * 对话过程可见：阶段 / 合成叙述 / 模型思考归并（仅本轮内存）。
 * 完成后默认展开，折叠仅由用户手动触发。
 * @author 赵振明
 * @date 2026-09-07 13:16:34
 */

export type StageStatus = "running" | "done" | "error";

export type ProcessStage = {
  id: string;
  label: string;
  status: StageStatus;
};

export type LiveProcess = {
  stages: ProcessStage[];
  /** 阶段合成叙述（正在理解…等） */
  thought: string;
  /** 模型原生深度思考 */
  modelThought: string;
  collapsed: boolean;
};

export function emptyProcess(): LiveProcess {
  return { stages: [], thought: "", modelThought: "", collapsed: false };
}

function appendThoughtLine(prev: string, delta: string): string {
  if (!delta) return prev;
  if (!prev) return delta;
  return prev.endsWith("\n") ? `${prev}${delta}` : `${prev}\n${delta}`;
}

export function applyProcessEvent(
  prev: LiveProcess,
  event: string,
  data: Record<string, unknown>,
): LiveProcess {
  if (event === "stage") {
    const id = String(data.id ?? "");
    if (!id) return prev;
    const label = String(data.label ?? id);
    const status = (data.status as StageStatus) || "running";
    const stages = [...prev.stages];
    const idx = stages.findIndex((s) => s.id === id);
    if (idx >= 0) stages[idx] = { id, label, status };
    else stages.push({ id, label, status });
    return { ...prev, stages, collapsed: false };
  }
  if (event === "thought_delta") {
    const delta = String(data.delta ?? "");
    if (!delta) return prev;
    const source = String(data.source ?? "narration");
    if (source === "model") {
      // 模型思考按 token 连续拼接，不加强制换行
      return {
        ...prev,
        modelThought: `${prev.modelThought || ""}${delta}`,
        collapsed: false,
      };
    }
    return {
      ...prev,
      thought: appendThoughtLine(prev.thought, delta),
      collapsed: false,
    };
  }
  return prev;
}

/**
 * 本轮 SSE 结束后保留过程区，并强制默认展开（不自动折叠）。
 * 无可见内容时原样返回，避免空面板。
 */
export function retainProcessAfterDone(
  process: LiveProcess | undefined,
): LiveProcess | undefined {
  if (!process || !hasVisibleProcess(process)) return process;
  return { ...process, collapsed: false };
}

/** 是否仍有可展示的过程区（阶段或任一思考即可）。 */
export function hasVisibleProcess(process: LiveProcess | undefined): boolean {
  if (!process) return false;
  return (
    process.stages.length > 0 ||
    Boolean(process.thought.trim()) ||
    Boolean(process.modelThought?.trim())
  );
}
