# 联网搜索（web_search）设计

> 日期：2026-09-07  
> 状态：待实现（§1–§3 已确认）  
> @author 赵振明

## 1. 目标

为系统 Agent 提供可开关的联网搜索能力：运行时经统一工具 `web_search` 调用；管理端配置实现方式与上游参数。首期仅实现 **SearXNG**；预留其它 API Provider，技能与工具 ID 不变。

## 2. 范围

### 做

- MySQL 单行表 `web_search_settings`（总开关、provider、base_url、api_key、超时、条数）
- Provider 适配器解耦：`WebSearchFacade` + `SearchProvider` + `SearxngProvider`
- 内置工具 `web_search` + 种子技能 `skill_web_search` → `agent_system`
- 管理端 `/system/web-search`：配置、总开关、测试连接；密钥脱敏
- 配置变更写审计（脱敏）

### 不做（首期）

- Serper / Bing 真实调用（枚举占位）
- SearXNG 并入本仓 docker-compose
- Base URL 种子默认值（客户自填）
- 天气、全文抓取、结果缓存、搜索配额

## 3. 架构（解耦）

```text
Admin API / 对话 FC
        │
        ▼
 WebSearchFacade.run(query)
        │ 门禁：enabled / 配置完整 / provider 已实现
        ▼
 ProviderRegistry.get(provider)
        │
        ├── SearxngProvider   （已实现）
        ├── SerperProvider*   （占位）
        └── BingProvider*     （占位）
```

| 模块 | 职责 | 不做什么 |
|---|---|---|
| `WebSearchFacade` | 统一入口、门禁、规范化结果 | HTTP 细节 |
| `SearchProvider` | `search(...)` 协议 | 读库、开关 |
| `SearxngProvider` | SearXNG JSON API | 技能 / FC |
| `SettingsRepo` | MySQL 读写、脱敏视图 | 发 HTTP |
| 工具 `web_search` | schema + executor → Facade | 绑死 SearXNG |
| Admin 页 / API | 配置与测试（复用 Facade/Provider） | 第二套 HTTP |

扩 Provider：新增适配器 + 注册 + 管理端字段；**不改** `web_search` / `skill_web_search`。

### 统一结果

成功：

```json
{
  "ok": true,
  "provider": "searxng",
  "query": "...",
  "items": [
    { "title": "...", "url": "...", "snippet": "..." }
  ]
}
```

失败：`ok=false`，`error` 取下表之一，可带 `hint`。

## 4. 数据模型

表 `web_search_settings`，单行 `id='default'`：

| 字段 | 说明 |
|---|---|
| `enabled` | 总开关，默认 0 |
| `provider` | 默认 `searxng`；预留 `serper`/`bing` |
| `base_url` | 客户填写，默认可空 |
| `api_key` | 可空；仅服务端明文；GET 掩码 |
| `timeout_seconds` | 默认 10 |
| `result_count` | 默认 5，上限 10 |
| `updated_at` / `updated_by` | 变更辅助 |

## 5. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/admin/web-search-settings` | 读配置（无密钥明文） |
| PUT | `/api/v1/admin/web-search-settings` | 更新；空 api_key=不改；审计 |
| POST | `/api/v1/admin/web-search-settings/test` | 测试连接 |

权限：平台管理员。

## 6. SearXNG

- `GET {base_url}/search?q={query}&format=json`
- 映射 `results[]` → `title` / `url` / `content`→`snippet`
- 截断 `result_count`；超时用配置

## 7. 工具与技能

- 工具：`web_search`，参数 `query`（必填）
- 技能：`skill_web_search`（origin=system）绑定工具并挂 `agent_system`
- 双重门禁：技能停用 **或** 总开关关闭 → 不可用

## 8. 管理端

- 路径：`admin-web/src/app/(admin)/system/web-search/page.tsx`
- 菜单：系统组「联网搜索」，path=`/system/web-search`（D48）
- 控件：总开关、Provider（仅 searxng 可选）、Base URL、API Key、超时、条数、测试连接、保存

## 9. 错误码

| error | 含义 |
|---|---|
| `web_search_disabled` | 总开关关闭 |
| `not_configured` | 缺 Base URL 等 |
| `provider_unimplemented` | Provider 未实现 |
| `invalid_query` | query 空 |
| `upstream_error` | HTTP/解析失败 |
| `upstream_unreachable` | 连接失败 |

## 10. 测试与风险

- 单测：Facade 门禁；SearxngProvider Mock httpx；结果规范化
- API：脱敏 GET/PUT；test 成功/失败
- 手验：客户 URL → 测试连接 → 对话搜索

风险：Docker 访问宿主机不通（靠测试连接）；密钥进日志（审计脱敏）；滥用刷量（条数/超时上限，配额后补）。

## 11. 落点文件

- `src/app/modules/web_search/`：facade、providers、settings_repo、registry
- `src/app/modules/tool/registry.py` / `executor.py`
- Admin API + admin-web 页 + 迁移（表、菜单、技能）

## 12. 用户授权与确认卡（Policy 解耦，LangGraph 接入）

对话主路径：**Turn Graph → Plan-Execute → Skill ReAct**（均为 LangGraph）。

| 组件 | 职责 |
|---|---|
| `WebSearchPolicy` | `ALLOW/BLOCK/CONFIRM`；过滤技能目录 |
| `SkillExecutionGate`（`_execute_skill_step`） | 调度 `skill_web_search` 前问 Policy；CONFIRM 出结构化卡 |
| `build_web_search_confirm_card` | 固定 ask_choice，不经模型生成 |
| `MessageSend.web_search` | 用户本轮授权 |
| `/api/v1/web-search/availability` | 管理端可用才显示对话按钮 |

未勾选但 Planner 选中联网技能 → CONFIRM 卡；选「是」须 **Interrupt/Resume**（恢复挂起的 `skill_web_search`，**禁止**整轮重规划）；选「否」续跑并 `exclude_web_search_skill` 防死循环。技能 prompt **不含**门禁话术。详见 `2026-09-08-web-search-confirm-resume-design.md`。

## 13. SearXNG JSON API 与后台页差异（已踩坑）

后台 HTML 搜索带 Cookie/偏好（如 zh-CN + bing/sogou/360search），JSON API **无 Cookie**，仅用服务端默认引擎时常见只打 brave/duckduckgo/startpage → CAPTCHA → `results: []`。

`SearxngProvider` 须显式传 `language=zh-CN` 与可用 `engines`（默认 `bing,sogou,360search,wikipedia,wiby`），与后台可用引擎对齐。

> **演进**：引擎列表改为管理端「同步 + 启停」目录，见 `docs/superpowers/specs/2026-09-08-web-search-engines-sync-design.md`（通用表，不绑死 SearXNG）。管理端支持一键全开/全关；每页条数用顶部独立下拉（20/50/100/200/500）。
