"""
运行时配置（环境变量 / .env）。

硬约束：单租户、LLM 只经 LiteLLM、OpenIM 外置。

@author 赵振明
@date 2026-07-21 15:31:36
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。禁止在此硬编码密钥明文默认值用于生产。"""

    model_config = SettingsConfigDict(
        env_file=("deploy/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "DEBUG"
    app_secret_key: str = "change-me"
    mock_external: bool = True

    database_url: str = "mysql+aiomysql://zeroagent:zeropass@127.0.0.1:3306/zeroagent"
    redis_url: str = "redis://:redispass@127.0.0.1:6379/0"
    rabbitmq_url: str = "amqp://zeroagent:rabbitpass@127.0.0.1:5672//"

    litellm_proxy_url: str = "http://127.0.0.1:4000"
    litellm_master_key: str = "sk-litellm-dev"
    litellm_model: str = "MiniMax-M3"
    litellm_embed_model: str = "text-embedding-3-small"

    milvus_uri: str = ""  # 空则跳过真实 Milvus
    # 独立 Embedding/Rerank 服务（空则跳过，走 LiteLLM/Mock）
    embed_service_url: str = ""  # 例 http://127.0.0.1:8088
    rerank_service_url: str = ""
    embed_dim: int = 512  # 与 bge-small-zh-v1.5 对齐；Mock 仍用 16
    kb_milvus_collection: str = "za_kb_chunks_v2"
    hybrid_rrf_k: int = 60
    hybrid_candidate_n: int = 50
    kb_chunk_size: int = 800
    kb_chunk_overlap: int = 100
    memory_summary_char_threshold: int = 12000
    memory_dedupe_threshold: float = 0.9
    memory_extract_idle_seconds: int = 180
    memory_extract_window_turns: int = 12

    openim_api_url: str = ""
    openim_secret: str = ""
    # 本阶段不使用 OpenIM；保留字段仅为兼容旧 .env，业务勿调用

    storage_backend: str = "oss"
    # mock | oss | minio；单测/开发可配合 MOCK_EXTERNAL

    user_daily_quota: int = 500

    # 审批待办默认超时（分钟，PRD D9）
    approval_timeout_minutes: int = 30
    approval_expire_interval_minutes: int = 5

    # 技能层 Function Calling 最大轮次
    skill_fc_max_rounds: int = 5

    # Agent 运行时：langgraph（Plan-Execute）| legacy（扁平 FC）
    agent_runtime: str = "langgraph"

    # Plan-Execute 主图最大计划步数
    agent_plan_max_steps: int = 5

    # 上下文窗口展示上限（tokens，对齐 PRD 滑动窗口；目录缺窗时回落）
    context_window_tokens: int = 8000

    # 上下文摘要压缩（相对模型窗口 + 回合后异步）
    context_compress_trigger_ratio: float = 0.75
    context_compress_target_ratio: float = 0.15
    context_compress_target_max: int = 2000
    context_compress_keep_recent_turns: int = 4
    context_compress_model: str = ""
    context_compress_dedup_seconds: int = 60

    # 文档理解子图 token 预算（DocAnalyze LangGraph）
    doc_analyze_context_tokens: int = 8000
    doc_analyze_output_reserve: int = 2048
    doc_analyze_map_chunk_tokens: int = 6000
    doc_analyze_max_output_chars: int = 20000

    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key: str = ""
    oss_secret_key: str = ""
    # 公网访问基址，例如 https://static.example.com（勿硬编码密钥）
    oss_public_base_url: str = ""

    langfuse_host: str = "http://127.0.0.1:3100"


@lru_cache
def get_settings() -> Settings:
    """单例配置（进程内缓存）。"""
    return Settings()
