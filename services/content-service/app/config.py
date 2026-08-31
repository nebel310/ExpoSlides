import logging

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_api_key: str = ""
    llm_model: str = "GigaChat-2-Max"
    llm_base_url: str = "https://api.giga.chat/v1"
    llm_scope: str = "GIGACHAT_API_PERS"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    llm_response_retries: int = Field(default=2, ge=0, le=5)
    content_validation_retries: int = Field(default=2, ge=0, le=5)
    log_file: str = "content_service.log"
    log_level: str = "DEBUG"

settings = Settings()


def setup_logging():
    file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.DEBUG),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[file_handler, console_handler],
        force=True,
    )
