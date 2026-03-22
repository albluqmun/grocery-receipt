from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://grocery:grocery_dev@db:5432/grocery_receipt"
    secret_key: str
    debug: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-lite"

    model_config = {"env_file": ".env"}


settings = Settings()
