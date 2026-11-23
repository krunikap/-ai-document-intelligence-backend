from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):

    # Application settings
    APP_NAME: str = "AI Document Intelligence API"
    APP_ENV: str = "development"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Database configuration
    DATABASE_URL: str

    # Authentication configuration
    JWT_SECRET_KEY: str | None = None
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Background processing
    REDIS_URL: str = "redis://localhost:6379/0"

    # File storage
    UPLOAD_DIR: Path = BASE_DIR / "uploads"

    # AI configuration
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-3.8-flash"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Environment file configuration
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


settings = Settings()
