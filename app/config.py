from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_region: str = "us-east-1"
    bedrock_llm_model_id: str = "us.amazon.nova-micro-v1:0"
    bedrock_embed_model_id: str = "amazon.titan-embed-text-v2:0"
    embed_dim: int = 1024

    database_url: str = "postgresql://postgres:postgres@localhost:5432/policyrag"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    max_retries: int = 2
    top_k: int = 4
    log_level: str = "INFO"


settings = Settings()
