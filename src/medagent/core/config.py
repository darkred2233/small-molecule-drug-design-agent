from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "小分子药物设计 Agent"
    database_url: str = "sqlite:///./.local/medagent.db"

    storage_endpoint: str = "localhost:9000"
    storage_access_key: str = "medagent"
    storage_secret_key: str = "medagent-secret"
    storage_bucket: str = "medagent-files"

    qwen_reasoning_model: str = "qwen3.7-max"
    qwen_task_model: str = "qwen3.7-plus"
    deepseek_refutation_model: str = "deepseek-v4-pro"
    embedding_model: str = "text-embedding-v4"
    rerank_model: str = "qwen3-rerank"

    model_config = SettingsConfigDict(
        env_prefix="MEDAGENT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
