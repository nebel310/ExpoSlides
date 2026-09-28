from app import errors


def test_hierarchy():
    """Проверяет наследование ошибок"""
    assert issubclass(errors.SessionNotFoundError, errors.GatewayError)
    assert issubclass(errors.TaskNotFoundError, errors.GatewayError)
    assert issubclass(errors.FileServiceError, errors.GatewayError)
    assert issubclass(errors.KafkaPublishError, errors.GatewayError)
    assert issubclass(errors.GatewayError, RuntimeError)


def test_instantiation():
    """Проверяет что ошибки конструируются с сообщением"""
    error = errors.TaskNotFoundError("task x not found")
    assert "task x not found" in str(error)