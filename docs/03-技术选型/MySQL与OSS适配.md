# MySQL 与阿里云 OSS 适配说明

> 版本 v0.3 | 2026-07-21  
> **现行**：对齐 PRD v0.7.3 / 技术选型 v0.4。冲突时以 PRD 第十六章为准。

---

## 文档版本

| 版本 | 日期 | 主要变更 |
|---|---|---|
| v0.3 | 2026-07-21 | **废止** OpenIM 直传 / OSS 事件入库；改为 Web 上传 → OSS → Celery |
| v0.2 | 2026-07-20 | 完全移除 MinIO，IM 文件直传 OSS（**已废止，勿实现**） |
| v0.1 | 2026-07-20 | 初版：PostgreSQL→MySQL、MinIO→OSS |

---

## 一、变更背景

| 调整 | 原方案 | 现行方案 | 原因 |
|---|---|---|---|
| 关系库 | PostgreSQL | **MySQL 8.0+** | 业务团队熟悉、运维成本低 |
| 对象存储 | MinIO + OSS | **线上 OSS 为主**；MinIO 仅无外网可选兜底 | 开发可走线上 |
| 文件入库 | OpenIM 直传 + OSS 事件（v0.2） | **Web/API 上传 → 服务端写 OSS → Celery**（D25） | 不接 OpenIM（D27） |

---

## 二、关系库：MySQL 8.0+

### 2.1 影响分析

| 影响点 | 现行方案 |
|---|---|
| **向量检索** | Milvus（稠密 + 稀疏 Hybrid） |
| **全文 / BM25** | **Milvus Hybrid 为主**；MySQL FULLTEXT **不作**主检索 |
| **JSON** | MySQL 8.0 JSON + 函数索引 |
| **CTE / 窗口** | MySQL 8.0+ |
| **事务** | InnoDB |

### 2.2 MySQL 必须配置（8.0+）

```ini
[mysqld]
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
innodb_buffer_pool_size = 12G
max_connections = 1000
slow_query_log = ON
long_query_time = 1
log_bin = mysql-bin
binlog_format = ROW
```

> 完整表结构见 `docs/01-产品需求/数据库表结构.md`。**禁止** `tenant_id`；**禁止**建 `im_user_maps`。

---

## 三、对象存储：线上 OSS（现行）

### 3.1 环境策略

| 环境 | 存储 |
|---|---|
| 开发（推荐） | 线上 OSS `zeroagent-dev` |
| 开发（无外网） | `STORAGE_BACKEND=minio` + Compose profile |
| 生产 | 线上 OSS `zeroagent-prod` |

### 3.2 配置要点

| 配置项 | 建议 |
|---|---|
| Bucket | 按环境分 |
| 访问控制 | 私有 + STS 临时上传凭证 |
| CORS | 允许 Web 控制台上传 |
| 生命周期 | 可按成本配置低频/归档 |
| **事件通知** | **不做入库主路径**（D25） |

### 3.3 STS 上传（Web）

前端经 `POST /documents/upload` 取 STS 或直传服务端；上传完成后 `confirm-upload` → Celery。

### 3.4 签名 URL（下载）

私有对象用限时签名 URL；权限校验在业务 API 层完成后再签发。

---

## 四、文件入库流程（现行 · D25）

```
用户在 Web（KB 页或系统对话附件）选择文件
   ↓
zeroAgent API：鉴权 → 写 OSS（或 STS 直传后 confirm）
   ↓
落库 documents（草稿）→ 投递 Celery
   ↓
解析 → Chunk → Embedding → Milvus
   ↓
命中测试通过后方可 publish
```

| 设计点 | 现行 |
|---|---|
| 入口 | Web / OpenAPI |
| 主路径 | 服务端（或 STS+confirm）写 OSS → Celery |
| **禁止** | OpenIM 文件回调、`/im/*`、以 OSS 桶事件作为**唯一**入库驱动 |
| Mock | `MOCK_EXTERNAL=true` 时可写本地 `.data/oss` |

### 废止（勿实现）

以下为 v0.2 史料，**AI Agent 不得实现**：

- OpenIM 文件直传 zeroAgent Bucket  
- 监听 OSS 事件 `/api/v1/oss/event` 作为入库主路径  
- `im_user_maps` / OpenIM STS 专用角色  

---

## 五、本地开发

| 项 | 说明 |
|---|---|
| 网络 | 能访问阿里云 OSS，或改用 MinIO profile |
| 凭证 | 仅用 dev Bucket / 测试 AK，写入 `deploy/.env` |
| 隔离 | 严禁指向 prod Bucket |

详见 `docs/05-开发指南/环境与密钥.md`。

---

## 六、版本

| 版本 | 说明 |
|---|---|
| v0.3 | 对齐 Web 上传与 D25/D27；废止 OpenIM/OSS 事件主路径 |
| v0.2 | 史料：OpenIM 直传（废止） |
