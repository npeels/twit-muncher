from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openrouter_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "OPENROUTER_API"),
    )
    rsshub_base_url: str = "https://rsshub.app"
    database_path: str = "data/twit-muncher.db"
    session_secret: str = "change-me-to-a-random-string"
    allowed_emails: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
