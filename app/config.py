from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    secret_key: str = Field(default="change_me", alias="SECRET_KEY")
    admin_email: str = Field(default="admin@example.com", alias="ADMIN_EMAIL")
    admin_password: str = Field(default="changeme123", alias="ADMIN_PASSWORD")
    database_url: str = Field(default="postgresql+asyncpg://postgres:postgres@db:5432/survey_db", alias="DATABASE_URL")
    sync_database_url: str = Field(default="postgresql+psycopg2://postgres:postgres@db:5432/survey_db", alias="SYNC_DATABASE_URL")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    environment: str = Field(default="development", alias="ENVIRONMENT")

    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=1025, alias="SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=False, alias="SMTP_USE_TLS")
    smtp_from_email: str = Field(default="survey@example.com", alias="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field(default="Survey Bot", alias="SMTP_FROM_NAME")

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
