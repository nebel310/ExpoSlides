import pytest
from app.config import Settings
from pydantic import ValidationError


def test_settings_valid_defaults(_env_file=None):
    """Проверить валидные дефолтные настройки"""
    local = Settings(_env_file=None)
    assert local.kafka_bootstrap_servers == "kafka:9092"
    assert local.kafka_group_id == "content-service"
    assert local.kafka_topic_task_parsed == "task.parsed"
    assert local.kafka_topic_task_content_ready == "task.content_ready"
    assert local.kafka_topic_task_content_retry == "task.content_retry"
    assert local.kafka_topic_task_failed == "task.failed"
    assert local.file_service_grpc_host == "file-service"
    assert local.file_service_grpc_port == 50051
    assert local.content_service_port == 50053
    assert local.content_validation_retries == 2


def test_settings_override_valid_values(monkeypatch):
    """Проверить валидное переопределение через переменные окружения"""
    monkeypatch.setenv("KAFKA_GROUP_ID", "content-service-test")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka-test:9092")
    monkeypatch.setenv("CONTENT_SERVICE_PORT", "60000")
    monkeypatch.setenv("FILE_SERVICE_GRPC_PORT", "60001")
    monkeypatch.setenv("CONTENT_VALIDATION_RETRIES", "4")
    local = Settings(_env_file=None)
    assert local.kafka_group_id == "content-service-test"
    assert local.kafka_bootstrap_servers == "kafka-test:9092"
    assert local.content_service_port == 60000
    assert local.file_service_grpc_port == 60001
    assert local.content_validation_retries == 4


@pytest.mark.parametrize(
    "env_name, env_value",
    [
        ("CONTENT_SERVICE_PORT", "0"),
        ("CONTENT_SERVICE_PORT", "65536"),
        ("CONTENT_SERVICE_PORT", "-1"),
        ("CONTENT_SERVICE_PORT", "not-a-number"),
        ("FILE_SERVICE_GRPC_PORT", "0"),
        ("FILE_SERVICE_GRPC_PORT", "70000"),
        ("FILE_SERVICE_GRPC_PORT", "abc"),
        ("CONTENT_VALIDATION_RETRIES", "-1"),
        ("CONTENT_VALIDATION_RETRIES", "6"),
        ("CONTENT_VALIDATION_RETRIES", "many"),
        ("LLM_API_TIMEOUT", "0"),
        ("LLM_MAX_TOKENS", "0"),
        ("LLM_RESPONSE_RETRIES", "-1"),
        ("LLM_RESPONSE_RETRIES", "10"),
    ],
)
def test_settings_invalid_values(monkeypatch, env_name, env_value):
    """Проверить отклонение невалидных значений настроек"""
    monkeypatch.setenv(env_name, env_value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_ignores_unknown_env(monkeypatch):
    """Проверить игнорирование неизвестных переменных окружения"""
    monkeypatch.setenv("SOME_UNRELATED_SERVICE_VAR", "value")
    local = Settings(_env_file=None)
    assert local.kafka_group_id == "content-service"