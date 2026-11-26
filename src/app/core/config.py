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
    # 浏览器可打开的 LiteLLM 控制台基址；空则回退 litellm_proxy_url
    # Docker 内 proxy 常为 http://litellm:4000，须单独设本机 http://127.0.0.1:4000
    litellm_ui_base_url: str = ""
    litellm_master_key: str = "sk-litellm-dev"
    # 仅作环境占位/健康检查展示；业务补全禁止静默回落本字段，须走模型治理系统默认
    litellm_model: str = "MiniMax-M3"
    litellm_embed_model: str = "text-embedding-3-small"

    milvus_uri: str = ""  # 空则跳过真实 Milvus
    # 独立 Embedding/Rerank 服务（空则跳过，走 LiteLLM/Mock）
    embed_service_url: str = ""  # 例 http://127.0.0.1:8088
    rerank_service_url: str = ""
    embed_dim: int = 512  # 与 bge-small-zh-v1.5 对齐；Mock 仍用 16
    kb_milvus_collection: str = "za_kb_chunks_v3"
    # 向量不可用时的降级：MySQL 候选切块上限（避免全库加载）
    kb_search_fallback_chunk_cap: int = 2000
    hybrid_rrf_k: int = 60
    hybrid_candidate_n: int = 50
    # 检索低分丢弃：相对 top1 比例下限（0=关闭）；兼容 RRF / Rerank
    kb_hit_score_relative_min: float = 0.55
    # 绝对分下限（0=关闭）；Rerank 0~1 时可设 0.15~0.3，纯 RRF 建议保持 0
    kb_hit_score_absolute_min: float = 0.0
    kb_chunk_size: int = 800
    kb_chunk_overlap: int = 100
    # llamaindex | native；父子分块默认开源 HierarchicalNodeParser
    kb_chunker_backend: str = "llamaindex"
    # 默认偏粗，减轻子块过碎对检索的稀释；上传可按文档覆盖
    kb_chunk_parent_size: int = 1500
    kb_chunk_child_size: int = 500
    kb_chunk_child_overlap: int = 80
    # 确认切块时为父块生成摘要并参与检索（子块∪父摘要）
    kb_parent_summary_enabled: bool = True
    kb_parent_summary_max_chars: int = 150
    # 确认后由 Celery 异步 LLM 生成父块摘要（禁止抽取式兜底）
    # 文档 Metadata：规则优先，空字段经 LiteLLM 补全（失败不阻断入库）
    kb_metadata_llm_enabled: bool = True
    kb_metadata_llm_max_chars: int = 6000

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

    # 对话回合总编排：langgraph（Turn Main Graph）| legacy（runtime 命令式）
    turn_runtime: str = "langgraph"

    # 系统 Agent：plan_execute（空技能共用 Planner，默认）| respond_only（单次 LC 特化回滚）
    system_agent_mode: str = "plan_execute"

    # Turn Graph checkpointer：redis（za:lg:）| memory（单测/显式降级）
    turn_checkpointer: str = "redis"

    # 记忆抽取短防抖空闲（秒）；Turn Graph 调度优先用此值
    memory_extract_debounce_seconds: int = 30
    # 系统配置：是否启用记忆抽取（可被 Redis 覆盖）
    memory_extract_enabled: bool = True

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
