from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    rsshub_base_url: str = "https://rsshub.app"
    database_path: str = "data/twit-muncher.db"
    session_secret: str = "change-me-to-a-random-string"
    allowed_emails: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
