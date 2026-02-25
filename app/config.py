from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str = ""
    rsshub_base_url: str = "https://rsshub.app"
    database_path: str = "data/twit-muncher.db"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
