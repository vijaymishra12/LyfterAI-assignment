"""All configuration comes from environment variables."""
import os


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:
    def __init__(self) -> None:
        self.api_keys: list[str] = _split(os.getenv("LLM_API_KEYS", ""))
        self.model: str = os.getenv("LLM_MODEL", "gemini/gemini-2.5-flash-lite")
        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:////data/app.db")
        self.allowed_origins: list[str] = _split(
            os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
        )
        self.enable_failure_simulation: bool = (
            os.getenv("ENABLE_FAILURE_SIMULATION", "false").strip().lower() == "true"
        )
        self.default_system_prompt: str = os.getenv(
            "DEFAULT_SYSTEM_PROMPT", "You are a helpful assistant. Keep answers clear and concise."
        )
        self.llm_timeout: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))


settings = Settings()
