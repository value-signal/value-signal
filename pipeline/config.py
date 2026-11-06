from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    dart_api_key: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_fallback_model: str = ""
    qa_daily_limit: int = 15
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_from: str = ""
    db_path: Path = ROOT_DIR / "db" / "value_signal.sqlite"


settings = Settings()
