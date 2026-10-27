from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="Enterprise Financial Verification Platform API", alias="APP_NAME")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    database_url: str = Field(
        default="sqlite:///./data/duolarity.db",
        alias="DATABASE_URL",
    )
    secret_key: str = Field(default="development-only-change-me", alias="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")
    password_reset_token_expire_minutes: int = Field(default=30, alias="PASSWORD_RESET_TOKEN_EXPIRE_MINUTES")
    frontend_url: str = Field(default="http://localhost:8000", alias="FRONTEND_URL")
    cors_origins: str = Field(default="http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000", alias="CORS_ORIGINS")
    document_storage_path: str = Field(default="./data/documents", alias="DOCUMENT_STORAGE_PATH")
    seed_super_admin_email: str = Field(default="admin@example.com", alias="SEED_SUPER_ADMIN_EMAIL")
    seed_super_admin_password: str = Field(default="ChangeMe123!@#", alias="SEED_SUPER_ADMIN_PASSWORD")

    allow_registration: bool = Field(default=True, alias="ALLOW_REGISTRATION")

    # --- Open-source AI (Ollama) ---
    ai_provider: str = Field(default="ollama", alias="AI_PROVIDER")  # ollama | none
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen2.5:7b-instruct", alias="OLLAMA_MODEL")
    ollama_timeout_seconds: int = Field(default=300, alias="OLLAMA_TIMEOUT_SECONDS")
    ollama_num_ctx: int = Field(default=8192, alias="OLLAMA_NUM_CTX")
    ai_chunk_chars: int = Field(default=7000, alias="AI_CHUNK_CHARS")
    ai_categorize_with_llm: bool = Field(default=True, alias="AI_CATEGORIZE_WITH_LLM")
    ai_force_llm_extraction: bool = Field(default=False, alias="AI_FORCE_LLM_EXTRACTION")

    # --- Statement ingestion ---
    max_upload_mb: int = Field(default=200, alias="MAX_UPLOAD_MB")
    ocr_enabled: bool = Field(default=True, alias="OCR_ENABLED")
    ocr_dpi: int = Field(default=200, alias="OCR_DPI")
    frontend_dir: str = Field(default="", alias="FRONTEND_DIR")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
