# Embedding / Rerank 独立服务（CPU；真模型默认 st）
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EMBED_BACKEND=st \
    EMBED_MODEL=BAAI/bge-small-zh-v1.5 \
    EMBED_DIM=512 \
    DEVICE=cpu \
    HF_HOME=/models/hf \
    TRANSFORMERS_CACHE=/models/hf

COPY requirements.txt .
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

COPY app.py .

EXPOSE 8088
VOLUME ["/models"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8088"]
