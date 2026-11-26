# 百度搜索 Provider（千帆 web_search）设计

> 日期：2026-09-08  
> 状态：待实现（§1–§3 已确认）  
> 关联：`docs/superpowers/specs/2026-09-07-web-search-design.md`、`docs/superpowers/specs/2026-09-08-web-search-engines-sync-design.md`  
> 上游文档：https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5  
> @author 赵振明  
> @date 2026-09-08 10:56:20

## 1. 目标

在现有联网搜索解耦架构上，新增 **百度千帆「百度搜索」** 作为可选 Provider：管理端二选一切换（与 SearXNG 互斥）；密钥 Web 管理、脱敏展示；工具 / 技能 ID 不变。

## 2. 已确认裁定

| 项 | 裁定 |
|---|---|
| 与 SearXNG 关系 | **A：二选一**（`web_search_settings.provider` 切换） |
| API 能力范围 | **A：最小可用** — 仅网页、`edition=standard`、仅 `web` 模态 |
| 管理端 UI | **A：字段自适应** — 百度时 Key 必填、Base URL 只读、隐藏引擎目录区 |
| 实现路径 | **方案 1** — 扩展 Facade + Provider，不新建配置表 |
| 解耦 | Facade 门禁；Provider 只 HTTP；Repo 只持久化；Admin 不直连上游 |
| 密钥 | 管理端入库；**禁止**写入仓库 / CHECKPOINT / 本 spec 明文 |

## 3. 架构与数据流

```text
Admin / 对话 FC
      │
      ▼
WebSearchFacade.run(query)
      │ 门禁：enabled / 配置完整 / provider 已实现
      ▼
ProviderRegistry
      ├── searxng   （已有；读引擎目录）
      ├── baidu     （新增）
      ├── serper*   （占位）
      └── bing*     （占位）
```

**百度路径：**

1. Facade 读 `web_search_settings`：`provider=baidu`、`api_key`、超时、`result_count`
2. **不**读 `web_search_engines`
3. `BaiduProvider.search` → `POST {base}/v2/ai_search/web_search`
4. Header：优先 `Authorization: Bearer {api_key}`；若联调确认需 AppBuilder 头，在 Provider 内兼容 `X-Appbuilder-Authorization`（不渗入 Facade）
5. Body 固定最小集：
   - `messages: [{ role: "user", content: query }]`
   - `search_source: "baidu_search_v2"`
   - `resource_type_filter: [{ type: "web", top_k: limit }]`
   - `edition: "standard"`
6. `references[]` → `SearchHit(title, url, snippet)`；snippet 优先 `snippet`，否则 `content`
7. Query 超长：按百度规则截断至 **72 字符**（汉字计 2），避免上游拒识

**配置完整性（`baidu`）：** 非空 `api_key` 即可。

## 4. 数据模型

沿用单行表 `web_search_settings`，**不新建表**。

| 变更 | 说明 |
|---|---|
| `provider` 枚举 | 增加 `baidu` |
| `api_key` | 百度必填；GET 脱敏；空串 PUT = 不改；`clear_api_key` 清空 |
| `base_url` | 选 `baidu` 时后端强制官方常量 `https://qianfan.baidubce.com`；路径由 Provider 拼接 |
| `timeout_seconds` / `result_count` | 不变；`result_count` → `top_k`（现有上限 10） |

`web_search_engines`：百度不使用；同步器 `supports_engine_catalog=False`。

可选：无 schema 变更时可不加迁移（仅枚举/代码）；若 DB 有 provider CHECK 约束则补迁移放行 `baidu`。

## 5. API

路径不变，扩展校验：

| 行为 | 规则 |
|---|---|
| `PUT /api/v1/admin/web-search-settings` | `provider=baidu`：无存量 Key 且未提交新 Key → 422；忽略客户端乱改的 Base URL，写回官方地址 |
| `POST .../test` | 走 Facade → BaiduProvider（与生产同路径） |
| `POST .../web-search-engines/sync` | `baidu` → 成功、`upserted=0`、`supports_engine_catalog=false`，文案「本实现方式无需引擎目录」 |

对话侧 `web_search` / availability：**不改契约**。

## 6. 管理端 UI

挂在现有 `/system/web-search`（D48）：

- Provider 下拉增加「百度搜索」
- 选百度：API Key 必填提示；Base URL **只读**；**隐藏**「同步引擎」与引擎表
- 超时 / 条数 / 总开关 / 测试连接共用
- 切回 SearXNG 恢复引擎区

## 7. 解耦边界（硬约束）

| 模块 | 做 | 不做 |
|---|---|---|
| `BaiduProvider` | HTTP、截断、映射 `references` | 读库、开关、审计 |
| `WebSearchFacade` | enabled / Key 齐全 / 路由 Provider | 拼百度 Body 细节 |
| `settings_repo` | 枚举校验、脱敏、写官方 URL | 发 HTTP |
| Admin 页 / API | 字段显隐、调用 Facade/Repo | 第二套上游调用 |
| `web_search` 工具 | 调 Facade | 感知百度 |

## 8. 错误处理

统一 `pack_err`，**禁止**回显密钥。

| 场景 | `error` |
|---|---|
| 总开关关 | 现有 disabled 码 |
| `baidu` 无 Key | `not_configured`（hint：管理端填写 API Key） |
| 未注册 | `provider_unimplemented` |
| 超时 / 网络 | `timeout` / `upstream_unreachable` |
| HTTP/鉴权/解析失败 | `upstream_error`（可带上游 code/message 摘要） |
| 空结果 | `ok=true, items=[]`（非错误） |

## 9. 测试要点

Mock HTTP，不依赖真实密钥入库到仓库：

- Provider：72 字符截断；`references` 映射；鉴权失败 / 超时
- Facade：`baidu` + Key → 调百度且不查引擎表；无 Key → `not_configured`
- Settings：切 `baidu` 强制官方 `base_url`；缺 Key 422
- 引擎 sync：`supports_engine_catalog=false`、计数 0
- 手验：管理页填 Key → 测试连接 → 对话联网搜索

## 10. 非目标（本期）

- turbo / 视频 / 图片 / 阿拉丁 / 站点过滤 / 时效 / 安全搜索 / 干预策略
- 主备降级、双源合并
- 独立百度配置表；用环境变量替代 Web 密钥管理
- 修改 `web_search` / `skill_web_search` 契约
- 将百度服务并入 docker-compose

## 11. 落点文件（预期）

- `src/app/modules/web_search/providers/baidu.py`（新增）
- `registry` / `facade` / `settings_repo`（枚举与门禁）
- 引擎 sync 占位注册 `baidu`
- `admin-web/.../system/web-search/page.tsx`（字段自适应）
- `tests/test_web_search*.py` 增补

## 12. 风险与应对

| 风险 | 应对 |
|---|---|
| 文档 Header 不一致（`Authorization` vs `X-Appbuilder-Authorization`） | Provider 内可切换/双试策略；单测覆盖 |
| Query 72 字符限制导致截断丢信息 | Provider 截断；后续可提示 hint（非本期必做） |
| 密钥泄露（聊天/日志） | 禁止进仓；审计脱敏；建议轮换已暴露的联调 Key |
| 免费额度耗尽 | 管理端测试连接可见失败；配额产品化非本期 |
