# 联网搜索引擎目录同步（通用 Provider）设计

> 日期：2026-09-08  
> 状态：已实现（待部署迁移 + 管理端同步引擎）  
> 关联：`docs/superpowers/specs/2026-09-07-web-search-design.md`  
> @author 赵振明  
> @date 2026-09-08 09:11:01

## 1. 目标

管理端按 **当前联网搜索 Provider** 拉取上游「可搜索引擎/通道」目录，入库后手动启停；运行时只使用本库已启用项。交互对齐 LiteLLM「同步模型目录 → 列表启停」。

表与 API **不绑死 SearXNG**：`provider` 维度通用；首期仅实现 SearXNG 的同步器，后续 Serper/Bing 等挂同一套。

## 2. 已确认裁定

| 项 | 裁定 |
|---|---|
| 方案 | A：同步入库 + 本库启停（仿 LiteLLM） |
| 表设计 | 通用 `web_search_engines`，含 `provider`，禁止 searxng 专用表名/字段语义 |
| 首次同步 `enabled` | 跟远端目录项的 `enabled=true` 对齐 |
| 再次同步 | **不覆盖**本库启停；只更新元数据 / `source_status` |
| 远端消失 | `source_status=missing` 且强制 `enabled=0` |
| 无引擎目录的 Provider | 同步成功但 `upserted=0`，提示「本实现方式无需引擎目录」 |
| 运行时无启用引擎 | 明确错误，禁止静默回退到硬编码默认引擎 |
| UI | 联网搜索页增加「同步引擎」按钮；每个 Provider 同一套操作 |

## 3. 数据模型

表：`web_search_engines`

| 列 | 类型/约束 | 说明 |
|---|---|---|
| `id` | PK string | 稳定 id：`wse_` + sha256(`provider`+`\0`+`engine_key`)[:28] |
| `provider` | string(32) | 与 `web_search_settings.provider` 枚举一致 |
| `engine_key` | string(128) | 上游引擎/通道 id（如 `bing`） |
| `display_name` | string(200) | 默认 = engine_key |
| `enabled` | int 0/1 | **本产品**是否参与搜索 |
| `source_status` | string(32) | `active` \| `missing` |
| `categories_json` | text nullable | 分类 JSON 数组字符串 |
| `meta_json` | text nullable | 远端快照（禁密钥明文） |
| `revision` | int | 乐观锁 |
| `updated_by` | string nullable | |
| `updated_at` | datetime | |

唯一约束：`(provider, engine_key)`。索引：`(provider, enabled)`。

**不做**：按引擎绑 Agent；不在本表存 Base URL/API Key（仍在 `web_search_settings`）。

## 4. 同步插件

```text
EngineCatalogSync(Protocol)
  provider_id: str
  supports_engine_catalog: bool
  async fetch_catalog(settings) -> list[EngineCatalogItem]
```

- `EngineCatalogItem`：`engine_key`, `display_name`, `remote_enabled`, `categories`, `meta`
- 注册表按 `provider` 取同步器；未注册 → 502/422 明确文案
- **SearXNG**：`GET {base_url}/config` → `engines[]`；映射 `name`→`engine_key`，`enabled`→`remote_enabled`，`categories`→`categories_json`
- **Serper/Bing（占位）**：`supports_engine_catalog=False`；sync API 返回计数全 0 + message

同步算法（对齐 LiteLLM）：

1. 读当前 `web_search_settings`（须已配可达的 base_url，searxng）
2. `fetch_catalog`
3. upsert：新行 `enabled = remote_enabled`；已有行保留 `enabled`，刷新 meta/categories，`source_status=active`
4. 本库该 provider 下未出现在远端的行 → `missing` + `enabled=0`
5. 写审计（无密钥）

## 5. API

均需平台管理员。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/admin/web-search-engines/sync` | 按当前 settings.provider 同步 |
| GET | `/api/v1/admin/web-search-engines?provider=` | 列表；`provider` 默认当前 settings |
| PATCH | `/api/v1/admin/web-search-engines/{id}` | `enabled` + 可选 `expected_revision`；`missing` 不可启用 |

Sync 响应示例：`{ upserted, disabled_missing, skipped, provider, supports_engine_catalog }`。

## 6. 管理端 UI

挂在现有 `/system/web-search`（D48 壳内页）：

- 「同步引擎」按钮（文案可带当前 Provider 名）
- 表格：engine_key、display_name、categories、本库开关、source_status
- 首期过滤：关键字即可；分类筛可选
- `missing` 行开关禁用开、可关

## 7. 运行时

- `SearxngProvider.search`：从 DB（或 Facade 注入）读取当前 provider 下 `enabled=1 AND source_status!='missing'` 的 `engine_key`，拼 `engines=`；保留 `language=zh-CN`（可后续再配置化）
- **零启用引擎**：`pack_err("no_engines_enabled", hint="同步并启用至少一个引擎")`
- 删除代码内硬编码 `_DEFAULT_ENGINES` 作为生产回退；仅单测可注入 engines 列表
- 无目录类 Provider：忽略本表

## 8. 迁移与兼容

- 新迁移建 `web_search_engines`；不改坏 `web_search_settings`
- 已部署环境：升级后须点一次「同步引擎」，否则 searxng 搜索因无启用引擎而失败（预期行为，管理端提示）

## 9. 测试要点

- sync：新行跟远端 enabled；二次 sync 不覆盖本库开关；远端删除 → missing
- PATCH：missing 不能 enable；revision 冲突 409
- Provider 搜索：仅传本库 enabled keys；零启用 → error
- 占位 Provider sync：supports=false、计数 0

## 10. 非目标（本期）

- 把引擎目录并入 docker-compose / 改 SearXNG 服务端 settings.yml
- 引擎级配额、健康探测自动启停
- 多租户
