from app import errors


def test_hierarchy():
    """Все ошибки наследуются от BuilderError"""
    assert issubclass(errors.BuilderInputError, errors.BuilderError)
    assert issubclass(errors.BuilderOutputError, errors.BuilderError)
    assert issubclass(errors.SlideReuseNotSupportedError, errors.BuilderError)
    assert issubclass(errors.BuilderError, RuntimeError)


def test_message_propagates():
    """Сообщение сохраняется в str(error)"""
    error = errors.BuilderInputError("не согласовано")
    assert "не согласовано" in str(error)