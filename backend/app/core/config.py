from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://grocery:grocery_dev@db:5432/grocery_receipt"
    secret_key: str = "change-me-in-production"
    debug: bool = False

    model_config = {"env_file": ".env"}


settings = Settings()
