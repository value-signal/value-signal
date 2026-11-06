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
    smtp_tls: bool = True
    alert_from: str = ""
    alert_daily_limit: int = 100
    cron_secret: str = ""
    site_url: str = ""
    vercel_project_production_url: str = ""
    database_url: str = ""


settings = Settings()


def public_site_url() -> str:
    if settings.site_url:
        return settings.site_url.rstrip("/")
    return f"https://{settings.vercel_project_production_url}"
