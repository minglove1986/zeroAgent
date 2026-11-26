# 管理端 LiteLLM 用量成本（按模型汇总）

> 状态：已实现（`modules/litellm` + BFF + 用量页；测 5 passed）  
> 日期：2026-08-12 09:19:38（东八区）  
> 作者：赵振明  
> 裁定：方案 1；`modules/litellm/` 专用包；一期仅按模型汇总表；**不做**趋势/下钻/配额改造/迁同步代码  
> 依据：LLM 只经 LiteLLM；菜单 `operations.usage`；与系统内 `modules.usage` 严格分离
> 计划：`docs/superpowers/plans/2026-08-12-admin-litellm-spend-by-model.md`

## 1. 目标与非目标

### 1.1 目标

1. 新建 **`src/app/modules/litellm/`**，专门对接 LiteLLM Proxy 的 HTTP（本期仅 spend 汇总）。
2. 管理端「用量成本」页：按平台模型目录列出模型，展示请求数 / tokens / spend；数据来自 LiteLLM。
3. 页内明确标注：**详细以 LiteLLM 系统为准**；提供 LiteLLM UI 外链。
4. API 前缀独立：`/api/v1/admin/litellm/...`，不进入 `/api/v1/usage`。

### 1.2 非目标（明确不做）

- 趋势图、单模型请求日志下钻、导出。
- 改系统内 `modules/usage`（配额）或 `/api/v1/usage/*`。
- 迁移 `modules/llm/litellm_sync.py` / 对话 client 到新包。
- 前端直连 LiteLLM；写入 LiteLLM 预算/重置 spend。
- 员工端页面。

## 2. 目录与边界

```
src/app/modules/litellm/
  __init__.py       # 说明：仅 LiteLLM Proxy；禁止依赖 modules.usage
  http_client.py    # GET + Bearer LITELLM_MASTER_KEY
  spend.py          # 拉 spend 并按 model 聚合
  schemas.py        # 出参结构（可与 API schema 共用或薄包装）

src/app/api/v1/admin_litellm.py   # 路由注册，命名带 litellm
```

| 区域 | 本期 |
|---|---|
| `modules/litellm/` | **新建**，spend only |
| `modules/llm/` | **不动** |
| `modules/usage/` | **不动** |
| `admin-web/.../operations/usage/page.tsx` | 占位 → 汇总页 |

## 3. API

`GET /api/v1/admin/litellm/spend/by-model`

- Query：`start_date`、`end_date`（`YYYY-MM-DD`）；默认近 7 天（含当天）；`start > end` → 422。
- 鉴权：`platform_admin` / `super_admin`（与模型治理一致）。
- 成功体：

```json
{
  "start_date": "2026-08-01",
  "end_date": "2026-08-12",
  "source": "litellm",
  "litellm_ui_url": "http://127.0.0.1:4000/ui",
  "disclaimer": "详细用量与计费以 LiteLLM 系统为准；本页仅为汇总展示。",
  "totals": {
    "spend": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "api_requests": 0
  },
  "items": [
    {
      "model_name": "MiniMax-M3",
      "display_name": "MiniMax-M3",
      "enabled": true,
      "matched": true,
      "spend": 0.01,
      "prompt_tokens": 100,
      "completion_tokens": 200,
      "total_tokens": 300,
      "api_requests": 5
    }
  ],
  "unmatched": []
}
```

- `items`：以平台 `llm_models`（或热缓存）为行骨架；用 `model_name` 对齐 LiteLLM 聚合结果。
- `unmatched`：LiteLLM 有用量、目录无对应 `model_name` 的行。
- LiteLLM 不可达 / 无 DB：HTTP 503 + 明确中文 `message`（不返回假成功全 0）。

`litellm_ui_url`：由配置推导（`LITELLM_PROXY_URL` 去尾 + `/ui`），可选用环境覆盖，禁止硬编码密钥。

## 4. LiteLLM 调用策略

`spend.py` 内封装，对 Proxy 使用 **master key**：

1. **优先**：`GET {proxy}/spend/logs?start_date=&end_date=&summarize=true` → 本仓按 `model` 字段聚合 spend / tokens / requests。  
2. **降级**：`GET {proxy}/global/spend/report?start_date=&end_date=` → 从报告 metadata 抽 model 再汇总。  
3. 两者皆失败 → 向上抛出，API 转 503。

实现时以本机实际 LiteLLM 版本探测；字段名容错（`model` / `model_id` 等），在测试中用 fixture 钉死一种成功路径。

超时：建议 10～15s；禁止把 master key 回传前端。

## 5. 管理端 UI

路径：`admin-web/src/app/(admin)/operations/usage/page.tsx`（D48 壳内）。

- 顶栏 `Alert`：固定 disclaimer + 链接「打开 LiteLLM 控制台」。
- `DatePicker.RangePicker` → 调 BFF。
- `Table` 列：显示名、`model_name`、请求数、prompt / completion / total tokens、spend（USD）、启用态（可选）。
- 可折叠区：目录外 `unmatched`。
- Loading / 错误 message；**无**导出、同步、配额按钮。

## 6. 测试要点

1. spend 聚合：fixture 模拟 LiteLLM JSON → 按 model 合计正确。  
2. 目录对齐：`items` 含目录模型；孤儿进 `unmatched`。  
3. 日期非法 → 422；LiteLLM 失败 → 503。  
4. 非管理员 → 403。  
5. 回归：现有 `/api/v1/usage/*` 测不受影响。

## 7. 风险

| 风险 | 应对 |
|---|---|
| LiteLLM 未配 Postgres | 503 + 提示检查 litellm-db |
| 模型名不一致 | unmatched + 页内说明 |
| spend API 版本差 | 优先/降级双路径 + 测钉死 |
| 与系统 usage 混淆 | 独立包/路由/文案；代码评审检查 import |

## 8. 验收清单

- [ ] 存在 `modules/litellm/`，且不 import `modules.usage`
- [ ] `GET /api/v1/admin/litellm/spend/by-model` 可用
- [ ] 用量成本页有表 + disclaimer + UI 外链
- [ ] `modules/usage`、`llm/litellm_sync` 无业务改动
- [ ] CHECKPOINT 已更新
