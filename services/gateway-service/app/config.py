from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки gateway-service"""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://redis:6379/0"
    redis_session_ttl: int = 2592000

    kafka_bootstrap_servers: str = "kafka:9092"
    gateway_kafka_group_id: str = Field(default="gateway-service", alias="GATEWAY_KAFKA_GROUP_ID")
    kafka_topic_task_created: str = "task.created"
    kafka_topic_task_parsed: str = "task.parsed"
    kafka_topic_task_content_ready: str = "task.content_ready"
    kafka_topic_task_built: str = "task.built"
    kafka_topic_task_failed: str = "task.failed"

    file_service_grpc_host: str = "file-service"
    file_service_grpc_port: int = 50051
    file_service_timeout: float = Field(default=30, gt=0)

    max_upload_size: int = 52428800
    gateway_port: int = 1000

    cookie_name: str = "exposlides_sid"
    cookie_max_age: int = 2592000
    cookie_secure: bool = False
    allowed_origins: list[str] = Field(default_factory=list)

    log_level: str = "INFO"


settings = Settings()
