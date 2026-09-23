"""Сообщения существующего контракта ``proto/file_service.proto``.

Обновление из корня проекта::

    uv run python -m grpc_tools.protoc -Iproto --python_out=exposlides/_proto \
        proto/file_service.proto

После генерации сохраните ``ruff: noqa`` в generated-файле: импорты зависимости
Empty нужны для регистрации дескриптора, хотя не используются напрямую.
"""
