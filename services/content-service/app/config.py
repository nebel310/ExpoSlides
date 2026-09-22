import logging

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки content-service"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_api_key: str = ""
    llm_api_timeout: int = Field(default=180, gt=0)
    llm_model: str = "GigaChat-2-Max"
    llm_fast_model: str = Field(default="GigaChat-2-Pro", min_length=1)
    llm_fast_repair_model: str = Field(default="GigaChat-2-Pro", min_length=1)
    llm_fast_api_timeout: int = Field(default=120, gt=0)
    fast_generation_timeout: int = Field(default=240, ge=30, le=270)
    llm_base_url: str = "https://api.giga.chat/v1"
    llm_scope: str = "GIGACHAT_API_PERS"
    llm_temperature: float = 0.2
    llm_max_tokens: int = Field(default=8192, gt=0)
    llm_response_retries: int = Field(default=2, ge=0, le=5)
    content_validation_retries: int = Field(default=2, ge=0, le=5)

    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_group_id: str = "content-service"
    kafka_topic_task_parsed: str = "task.parsed"
    kafka_topic_task_content_ready: str = "task.content_ready"
    kafka_topic_task_content_retry: str = "task.content_retry"
    kafka_topic_task_failed: str = "task.failed"

    file_service_grpc_host: str = "file-service"
    file_service_grpc_port: int = Field(default=50051, gt=0, le=65535)

    content_service_port: int = Field(default=50053, gt=0, le=65535)

    log_file: str = "content_service.log"
    log_level: str = "INFO"


settings = Settings()


def setup_logging() -> None:
    """Настроить логирование в файл и консоль"""
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
