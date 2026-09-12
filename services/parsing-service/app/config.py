from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки parser-service из переменных окружения"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_group_id: str = "parser-service"
    kafka_topic_task_created: str = "task.created"
    kafka_topic_task_parsed: str = "task.parsed"
    kafka_topic_task_failed: str = "task.failed"

    file_service_grpc_host: str = "file-service"
    file_service_grpc_port: int = 50051

    parser_service_port: int = 50052


settings = Settings()