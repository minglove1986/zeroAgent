# 知识库文档详情 UX 重构设计

> 状态：已实现  
> 日期：2026-11-23 10:09:08  
> @author 赵振明

## 背景

管理端文档详情把「切块 / 问答 / 命中 / 发布 / 版本」堆在一页，按钮平铺，业务专家难懂主流程；命中明细与发布闸门缺少清单化表达。单条问答无法独立试测，只能整表重测。

## 目标

1. 按文档生命周期分步：**切块审阅 → 质量评测 → 发布**，版本独立 Tab。  
2. 顶部固定 **发布闸门清单**（切块已确认 / QA≥5 / 召回≥80%）。  
3. 支持 **单条命中测试**（允许未保存编辑直接测，不落库、不改写整文档 `hit_rate`）。  
4. 文案偏业务；Top 召回等技术明细可展开。

## 非目标

- 不改发布闸门阈值（仍 QA≥5 且 hit_rate≥0.8）。  
- 不改切块台内部交互（仅迁入 Tab）。  
- 不做批量文档向导页 / 强制线性不可回退。  
- 不新增 `hit_test_details` 库表字段（继续 Redis/`last_hit_test`）。

## 信息架构

```
[返回知识库]  文档标题/ID/状态摘要
发布闸门清单：☑切块已确认  ☑问答≥5  ☐召回≥80%（x/y）
Steps 指示：切块审阅 → 质量评测 → 发布

Tabs:
  1. 切块审阅   → ChunkWorkbench
  2. 质量评测   → 问答表 + 命中列 + 操作
  3. 发布       → 闸门复述 + 发布按钮
  4. 版本       → 版本表 + 回滚
```

默认进入 Tab：`pending_review`→切块；`ready` 且召回未达标→质量评测；闸门全过→发布。

## 质量评测 Tab

| 操作 | 行为 |
|---|---|
| 一键生成并测评 | 现有 `POST .../generate-qa?run_hit_test=1`；刷新表与闸门 |
| 保存问答 | `PUT .../qa-pairs`；清空 hit_rate；提示需重测 |
| 重测全部 | `POST .../hit-test`；写回 hit_rate + last_hit_test |
| 测本条 | `POST .../hit-test/one`；用**当前行输入**（可未保存）；只更新该行命中态 |
| 加一行 | 本地追加空行 |

表列：命中状态｜问题｜期望原文句｜操作（测本条）｜可展开 Top 召回。

## API

### `POST /api/v1/documents/{id}/hit-test/one`

请求：

```json
{ "question": "...", "expected_chunk_hint": "..." }
```

约束：`question` 非空；hint 可空（空则召回非空即命中，与整测一致）。  
鉴权：同文档读权限。  
逻辑：复用现有评测语料（子块正文 + 父块摘要）与 `_hint_hit`；**不** `commit` `documents.hit_rate`；**不**覆盖整表 `last_hit_test`（可选写入行级缓存，非必须）。

响应：

```json
{
  "question": "...",
  "expected_chunk_hint": "...",
  "hit": true,
  "reason": "hit|hint_not_in_doc|not_in_top_k",
  "hint_in_document": true,
  "top_contents": ["..."]
}
```

## 发布 Tab

- 复述三项闸门；未达标项红字说明下一步去哪个 Tab。  
- 「发布」仅三项全过可点；已 `published` 显示只读。

## 验收

1. 四 Tab 可切换；闸门清单随 status/qa/hit_rate 更新。  
2. 测本条：改 hint 不保存即可测，整文档 hit_rate 不变。  
3. 重测全部后 hit_rate 与清单刷新；达标可发布。  
4. 版本回滚仍可用。  
5. 单测覆盖 `hit-test/one`；回归 `test_kb_qa_hit.py`。

## 风险

| 风险 | 应对 |
|---|---|
| 未保存测通过、保存后总测失败 | 发布前强制看总召回；保存后清单提示「需重测全部」 |
| Tab 默认选错 | 按文档状态推断默认 Tab |
| 单条与整测算法漂移 | 共用同一套 rank/_hint_hit |
