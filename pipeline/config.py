"""
config.py — Application settings loaded from .env / environment variables.

All pipeline code imports settings from here. Nothing reads os.environ directly.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    _pipeline_env = Path(__file__).resolve().parent / ".env"
    _root_env = Path(__file__).resolve().parent.parent / ".env"

    model_config = SettingsConfigDict(
        env_file=[str(_pipeline_env), str(_root_env)],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    groq_api_key: str   = Field(default="", alias="GROQ_API_KEY")

    # Vision OCR → Gemini Flash (only provider with vision free tier)
    ocr_model: str       = Field(default="gemini-2.0-flash",          alias="OCR_MODEL")
    # Text grading → Groq (generous free limits, extremely fast)
    grading_model: str   = Field(default="llama3-70b-8192",           alias="GRADING_MODEL")
    grading_provider: str = Field(default="groq",                     alias="GRADING_PROVIDER")
    # Embeddings → Gemini (generous free limits for text-embedding)
    embedding_model: str = Field(default="models/text-embedding-004", alias="EMBEDDING_MODEL")

    # ── Thresholds ────────────────────────────────────────────
    ocr_confidence_threshold: float = Field(default=0.80, alias="OCR_CONFIDENCE_THRESHOLD")
    plagiarism_threshold: float     = Field(default=0.95, alias="PLAGIARISM_THRESHOLD")
    auto_approve_hours: int         = Field(default=48,   alias="AUTO_APPROVE_HOURS")

    # ── Storage ───────────────────────────────────────────────
    storage_backend: str   = Field(default="local",    alias="STORAGE_BACKEND")
    local_storage_path: str = Field(default="./scratch", alias="LOCAL_STORAGE_PATH")
    s3_bucket: str         = Field(default="",         alias="S3_BUCKET")
    gcs_bucket: str        = Field(default="",         alias="GCS_BUCKET")

    # ── MongoDB ───────────────────────────────────────────────
    mongo_uri: str = Field(default="mongodb://localhost:27017", alias="MONGO_URI")
    db_name: str   = Field(default="gradeops_db",               alias="DB_NAME")

    # ── Auth ──────────────────────────────────────────────────
    jwt_secret_key: str = Field(default="super-secret-key-change-me", alias="JWT_SECRET_KEY")
    jwt_algorithm: str  = Field(default="HS256",                      alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=1440,            alias="ACCESS_TOKEN_EXPIRE_MINUTES") # 24 hours

    # ── Concurrency & Resilience ─────────────────────────────
    # Max simultaneous LLM calls per agent (prevents rate-limit spikes)
    llm_concurrency: int = Field(default=4, alias="LLM_CONCURRENCY")
    # Max retry attempts on transient API errors (429, 503)
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")

    # ── Server ────────────────────────────────────────────────
    server_host: str  = Field(default="0.0.0.0",              alias="SERVER_HOST")
    server_port: int  = Field(default=8000,                    alias="SERVER_PORT")
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]


# Singleton — import this everywhere
settings = Settings()
