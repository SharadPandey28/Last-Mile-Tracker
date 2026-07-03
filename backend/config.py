from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "last_mile_tracker"

    # JWT
    jwt_secret: str = "dev_secret_change_in_production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Email (Resend)
    email_provider: str = "resend"
    resend_api_key: str = ""
    email_sender: str = ""

    # App
    app_env: str = "development"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
