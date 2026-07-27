# embed-rerank 独立服务

默认 **真模型**：`EMBED_BACKEND=st` + `BAAI/bge-small-zh-v1.5`（512 维，CPU）。

## Compose（推荐）

```powershell
# 1）预下载模型到数据卷（国内可用 ModelScope）
# 目标：D:/dockers/zeroagent/embed-models/bge-small-zh-v1.5

# 2）启动
cd deploy
docker compose --env-file .env --profile embed up -d --build embed-rerank
```

主仓 `.env`：

```
EMBED_SERVICE_URL=http://127.0.0.1:8088
RERANK_SERVICE_URL=http://127.0.0.1:8088
EMBED_BACKEND=st
EMBED_MODEL=/models/bge-small-zh-v1.5
EMBED_DIM=512
```

## 契约

- `GET /health`
- `POST /v1/embeddings` `{"input":["..."]}`
- `POST /v1/rerank` `{"query":"...","documents":["..."],"top_n":5}`

联调/CI 可设 `EMBED_BACKEND=mock`（无权重伪向量）。
更换更好模型：只改本服务镜像/环境变量或挂载目录，主应用零改代码。
