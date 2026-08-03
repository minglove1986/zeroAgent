# Task 2 审查：postSse AbortSignal 支持

**审查类型：** 只读（Spec + Quality）  
**审查时间：** 2026-07-30 14:50:00（东八区）  
**依据：** `chat-queue-task-2-brief.md`、`chat-queue-task-2-report.md`、`chat-queue-task-2-review-pkg.md`、`docs/superpowers/specs/2026-07-30-chat-send-queue-design.md` §6  
**审查者：** Code Review Agent  

---

## 裁决

| 维度 | 结论 |
|---|---|
| **Spec** | ✅ 通过 |
| **Quality** | **Approved**（有 Important 范围说明项，非阻塞 Task 2 验收） |

**一句话：** Task 2 核心目标已达成——`postSse` 新增可选第 4 参数 `{ signal?: AbortSignal }`，传入 `fetch`，无 try/catch 包裹，`AbortError` 可向上透传；三处现有调用仍为 3 参形式，ChatPage 未接入 signal（符合本期范围）。同文件附带 `formatApiErrorText` 等 brief 外改动，需在报告中如实标注，但不影响 AbortSignal 契约。

---

## Spec Compliance

| Brief / 设计 §6 要求 | 状态 | 证据 |
|---|---|---|
| 修改 `web/src/lib/sse.ts` | ✅ | 唯一 Task 2 目标文件 |
| 签名 `postSse(path, body, onEvent, options?: { signal?: AbortSignal })` | ✅ | `sse.ts` L45–50 |
| `signal: options?.signal` 写入 `fetch` RequestInit | ✅ | `sse.ts` L51–61 |
| 读流循环逻辑不变 | ✅ | `while (true) { await reader.read() }` 未改（L86–102） |
| abort 时抛出 `DOMException`/`Error`，`name === "AbortError"` | ✅ | 无 catch；依赖 fetch / ReadableStream 原生行为 |
| 第 4 参数可选，现有 `postSse(a,b,c)` 无需修改 | ✅ | `page.tsx` L566、L679、L770 仍为 3 参 |
| 本 Task 不改 ChatPage | ✅ | 三处调用未传 `signal`；AbortController 留 Task 3 |
| 测试可选手工 / 无框架则联调 | ✅ | web 无 vitest/jest；报告声明跳过单测，符合 brief |
| Commit 仅用户要求时 | ✅ | 报告声明未 commit；审查不强制 commit |
| 全局：AbortError 必须 propagate | ✅ | 全函数无外层 try/catch |
| 全局：不 require commit | ✅ | 已遵守 |

**设计文档 §6 对齐：** `fetch` 传入 signal ✅；ChatPage `abortRef` 与停止按钮属 Task 3+，本 Task 不判缺失。

---

## Strengths

1. **实现与 brief 代码片段一致**：签名、fetch 传参、读流循环保留，改动面极小，Task 3 可直接 `{ signal: ac.signal }` 接入。
2. **AbortError 传播路径清晰**：报告准确描述「连接前 fetch 抛错 / 读流中 reader.read 抛错」两阶段；代码无吞错逻辑，满足 `error.name === "AbortError"` 区分取消与真实失败的前置条件。
3. **向后兼容**：`options?.signal` 缺省为 `undefined`，未传第 4 参时行为与改前一致（除下文 Minor 所述 HTTP 错误文案差异）。
4. **方法注释到位**：`postSse` 注释明确 abort 语义与向上透传（L42–44），便于 Task 3 维护者理解契约。
5. **类型与静态检查**：审查者复跑 `npx tsc --noEmit`（web/）通过；`sse.ts` 无 ESLint 新增告警。
6. **调用方盘点完整**：报告列出 send / card-action / retry 三处行号，与全仓 `postSse(` 检索结果一致。

---

## Issues

### Critical

*无。* AbortSignal 契约、调用兼容、ChatPage 范围均符合 brief 与全局硬约束。

### Important

1. **同文件附带 brief 外改动，报告未披露**  
   diff 除 AbortSignal 外还包含：
   - 新增 `formatApiErrorText`（~40 行，含 40031 / model disabled 等文案）
   - 移除请求头 `"Cache-Control": "no-cache"`（仍保留 `cache: "no-store"`）
   - HTTP 错误从 `throw new Error(text \|\| \`HTTP ${status}\`)` 改为 `formatApiErrorText(...)`  
   上述均**不在** Task 2 brief / plan Step 1 范围内，功能上不阻塞 AbortSignal，但造成 task-scoped 验收与 cherry-pick 隔离困难（与 Task 1 审查 Important #1 同类）。  
   **建议：** 报告「变更摘要」补列并行改动边界；若后续 commit，考虑与 AbortSignal 拆分为独立 changeset。

2. **无 AbortSignal 自动化测试**  
   brief 允许无框架时跳过；但 Task 3 将依赖 abort 语义，建议在 Task 3 联调清单中显式覆盖「流式中 abort / 连接前 abort」两路径，或 Task 3 引入最小 mock-fetch 断言（非本 Task 阻塞项）。

### Minor

1. **`formatApiErrorText` 方法注释无独立 `@author`/时间** — 文件头已有 `@author 赵振明`；若严格按注释规范，新方法可补一行说明（非功能问题）。
2. **移除 `Cache-Control: no-cache` 请求头** — brief 样例本未含该头；`cache: "no-store"` 仍生效，SSE 缓存语义影响可忽略，属 incidental diff。
3. **工作树中 `page.tsx` 有大量并行改动** — `git diff` 显示 ChatPage +449 行，但 Task 2 未改 `postSse` 调用签名；审查确认 Task 2 交付边界正确，并行 diff 不应计入 Task 2 Fail。
4. **已收部分 SSE 再 abort** — 报告已说明 `onEvent` 不回滚；与 design §6「客户端 Abort 后服务端可能仍短暂生成」一致，Task 3 需在 catch 中忽略 `AbortError` 并处理半完成 UI。

---

## Assessment

**Task quality: Approved**

Task 2 按 brief 与 design §6 完成 `postSse` AbortSignal 支持：可选第 4 参数、signal 传入 fetch、AbortError 向上透传、现有三处调用兼容、ChatPage 未提前接入。TypeScript 编译通过，无 linter 回归。

**附带条件（非阻塞本 Task 验收）：** `sse.ts` 内 `formatApiErrorText` 及 HTTP 错误处理变更为 brief 外增量，应在报告与后续 commit 中拆分或文档化，避免与 AbortSignal 混为一次「Task 2 交付」。

**Spec ✅ | Quality Approved**

---

## 审查者验证

```powershell
# web/ 目录
npx tsc --noEmit   # exit 0

# 调用点（仍为 3 参，无 signal）
web/src/app/chat/page.tsx:566  messages/send
web/src/app/chat/page.tsx:679  card-action
web/src/app/chat/page.tsx:770  retry
```
