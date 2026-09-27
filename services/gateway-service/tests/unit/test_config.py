
from app.config import Settings


def _clean_env(monkeypatch):
    """Убирает переменные gateway из окружения"""
    for key in (
        "REDIS_URL", "REDIS_SESSION_TTL",
        "KAFKA_BOOTSTRAP_SERVERS", "GATEWAY_KAFKA_GROUP_ID",
        "KAFKA_TOPIC_TASK_CREATED", "KAFKA_TOPIC_TASK_PARSED",
        "KAFKA_TOPIC_TASK_CONTENT_READY", "KAFKA_TOPIC_TASK_BUILT",
        "KAFKA_TOPIC_TASK_FAILED",
        "FILE_SERVICE_GRPC_HOST", "FILE_SERVICE_GRPC_PORT",
        "MAX_UPLOAD_SIZE", "GATEWAY_PORT",
        "COOKIE_NAME", "COOKIE_MAX_AGE", "LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_settings_defaults(monkeypatch):
    """Проверяет значения по умолчанию"""
    _clean_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.redis_url == "redis://redis:6379/0"
    assert settings.redis_session_ttl == 2592000
    assert settings.kafka_bootstrap_servers == "kafka:9092"
    assert settings.gateway_kafka_group_id == "gateway-service"
    assert settings.kafka_topic_task_created == "task.created"
    assert settings.kafka_topic_task_parsed == "task.parsed"
    assert settings.kafka_topic_task_content_ready == "task.content_ready"
    assert settings.kafka_topic_task_built == "task.built"
    assert settings.kafka_topic_task_failed == "task.failed"
    assert settings.file_service_grpc_host == "file-service"
    assert settings.file_service_grpc_port == 50051
    assert settings.max_upload_size == 52428800
    assert settings.gateway_port == 1000
    assert settings.cookie_name == "exposlides_sid"
    assert settings.cookie_max_age == 2592000
    assert settings.log_level == "INFO"


def test_settings_env_override(monkeypatch):
    """Проверяет переопределение через переменные окружения"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("REDIS_URL", "redis://custom:6380/2")
    monkeypatch.setenv("GATEWAY_KAFKA_GROUP_ID", "custom-group")
    monkeypatch.setenv("MAX_UPLOAD_SIZE", "1024")
    settings = Settings(_env_file=None)
    assert settings.redis_url == "redis://custom:6380/2"
    assert settings.gateway_kafka_group_id == "custom-group"
    assert settings.max_upload_size == 1024


def test_settings_alias_gateway_group(monkeypatch):
    """Проверяет что GATEWAY_KAFKA_GROUP_ID попадает в gateway_kafka_group_id"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("GATEWAY_KAFKA_GROUP_ID", "gateway-test")
    settings = Settings(_env_file=None)
    assert settings.gateway_kafka_group_id == "gateway-test"


def test_settings_ignores_extra(monkeypatch):
    """Проверяет что лишние env не ломают Settings"""
    _clean_env(monkeypatch)
    monkeypatch.setenv("SOMETHING_ELSE", "value")
    settings = Settings(_env_file=None)
    assert settings.gateway_port == 1000