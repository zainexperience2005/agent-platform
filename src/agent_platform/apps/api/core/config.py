from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Agent Platform"
    app_version: str = "0.1.0"
    environment: str = "development"

    database_url: str = "postgresql://platform:platform@localhost:5432/agent_platform"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-secret-change-me-32-chars-long!"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30

    openai_api_key: str = ""

    session_secret: str = "dev-session-secret-change-me"
    google_client_id: str = ""
    google_client_secret: str = ""



settings = Settings()
