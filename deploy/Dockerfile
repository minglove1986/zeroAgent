# zeroAgent API / Worker 镜像（业务进程；依赖由 Compose 提供）
# @author 赵振明
# @date 2026-09-08 14:14:21
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    LOG_LEVEL=info

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations

RUN pip install --no-cache-dir -e .

EXPOSE 8000

# LOG_LEVEL 来自 compose env_file（deploy/.env）；需 rebuild 后生效
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level $(echo ${LOG_LEVEL:-info} | tr '[:upper:]' '[:lower:]')"]
