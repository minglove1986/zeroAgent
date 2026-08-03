/**
 * 对话过程可见：阶段 / 思考态归并（仅本轮内存）。
 * @author 赵振明
 * @date 2026-07-27 14:45:31
 */

export type StageStatus = "running" | "done" | "error";

export type ProcessStage = {
  id: string;
  label: string;
  status: StageStatus;
};

export type LiveProcess = {
  stages: ProcessStage[];
  thought: string;
  collapsed: boolean;
};

export function emptyProcess(): LiveProcess {
  return { stages: [], thought: "", collapsed: false };
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
    const thought =
      prev.thought && !prev.thought.endsWith("\n")
        ? `${prev.thought}\n${delta}`
        : `${prev.thought}${delta}`;
    return { ...prev, thought, collapsed: false };
  }
  return prev;
}

export function collapseProcess(prev: LiveProcess): LiveProcess {
  return { ...prev, collapsed: true };
}

/** 是否仍有可展示的过程区（阶段或思考任一即可）。 */
export function hasVisibleProcess(process: LiveProcess | undefined): boolean {
  if (!process) return false;
  return process.stages.length > 0 || Boolean(process.thought.trim());
}
