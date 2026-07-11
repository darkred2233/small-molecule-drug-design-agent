from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "小分子药物设计 Agent"
    database_url: str = "sqlite:///./.local/medagent.db"

    storage_endpoint: str = "localhost:9000"
    storage_access_key: str = "medagent"
    storage_secret_key: str = "medagent-secret"
    storage_bucket: str = "medagent-files"
    storage_local_root: str = "./.local/uploads"

    qwen_reasoning_model: str = "qwen3.7-max"
    qwen_task_model: str = "qwen3.7-plus"
    deepseek_refutation_model: str = "deepseek-v4-pro"
    embedding_model: str = "text-embedding-v4"
    rerank_model: str = "qwen3-rerank"
    rag_embedding_dimension: int = 2048
    rag_chunk_size: int = 1800
    rag_chunk_overlap: int = 180
    rag_vector_top_k: int = 80
    rag_keyword_top_k: int = 80
    rag_default_top_k: int = 10
    rag_use_remote_embeddings: bool = True
    rag_use_remote_rerank: bool = True
    dashscope_api_key: str | None = None
    dashscope_compatible_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_rerank_url: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="MEDAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
