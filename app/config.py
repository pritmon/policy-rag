"""
config.py — Central settings file for the entire app.

All configuration (AWS region, model names, database URL, etc.) is read
from environment variables or the .env file. No hardcoded secrets anywhere.

How it works:
- pydantic-settings reads the .env file automatically
- Every setting has a safe default value
- Import `settings` anywhere in the app to access config
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Tell pydantic to read from .env file; ignore unknown keys
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Provider Switch ---
    # Which AI provider to use for the LLM: "bedrock" (AWS) or "gemini" (Google, free tier).
    # Lets us swap the brain without touching the rest of the app.
    llm_provider: str = "bedrock"
    # Which provider for embeddings: "bedrock" (Titan) or "gemini" (Google, free tier).
    embed_provider: str = "bedrock"

    # --- Google Gemini (used when provider=gemini) ---
    # Free API key from https://aistudio.google.com
    gemini_api_key: str = ""
    # Gemini 2.5 Flash Lite — fast, free tier, stronger than Nova Micro
    gemini_model: str = "gemini-2.5-flash-lite"
    # Google's embedding model — we request 768 dimensions (matches EMBED_DIM)
    gemini_embed_model: str = "gemini-embedding-001"

    # --- AWS ---
    # Which AWS region to use for Bedrock calls
    aws_region: str = "us-east-1"

    # --- Bedrock Models ---
    # The LLM used for critiquing and synthesizing answers (Amazon Nova Micro)
    bedrock_llm_model_id: str = "us.amazon.nova-micro-v1:0"
    # The embedding model used to convert text into vectors (Amazon Titan Embed v2)
    bedrock_embed_model_id: str = "amazon.titan-embed-text-v2:0"
    # Number of dimensions in each embedding vector (Titan v2 = 1024)
    embed_dim: int = 1024

    # --- Database ---
    # Connection string for the pgvector Postgres database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/policyrag"

    # --- Langfuse Tracing (optional) ---
    # Leave blank to disable tracing — the app works fine without it
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # --- App Behaviour ---
    # How many times the self-correction loop can retry before giving up
    max_retries: int = 2
    # How many similar chunks to retrieve from pgvector per search
    top_k: int = 4
    # Logging level — INFO shows normal logs, DEBUG shows everything
    log_level: str = "INFO"


# Single shared instance — import this everywhere
settings = Settings()
