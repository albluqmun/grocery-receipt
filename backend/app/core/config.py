from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://grocery:grocery_dev@db:5432/grocery_receipt"
    database_url_test: str = ""

    @model_validator(mode="after")
    def _derive_test_url(self) -> "Settings":
        if not self.database_url_test:
            base = self.database_url.rstrip("/")
            self.database_url_test = base.rsplit("/", 1)[0] + "/grocery_receipt_test"
        return self

    secret_key: str
    debug: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-lite"
    google_drive_credentials_path: str = ""
    google_drive_folder_id: str = ""
    gemini_batch_limit: int = 0
    api_key: str = ""
    cors_origins: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
