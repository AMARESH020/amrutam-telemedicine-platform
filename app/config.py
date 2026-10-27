import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./amrutam.db"
    jwt_secret: str = "CHANGE_THIS_DEVELOPMENT_SECRET_BEFORE_DEPLOYMENT"
    jwt_exp_minutes: int = 60
    mfa_encryption_key: str = ""
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    app_env: str = "development"

settings = Settings()
