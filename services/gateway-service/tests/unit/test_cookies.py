from fastapi import Response
from starlette.requests import Request

from app.config import settings
from app.utils.cookies import get_sid_from_request, new_sid, set_sid_cookie


def _make_request(cookie_value: str | None) -> Request:
    """Создаёт фиктивный Request с заданной cookie"""
    headers = []
    if cookie_value is not None:
        headers.append((b"cookie", f"{settings.cookie_name}={cookie_value}".encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
    }
    return Request(scope)


def test_get_sid_from_request_present():
    """Проверяет чтение sid из cookie"""
    request = _make_request("abc-123")
    assert get_sid_from_request(request) == "abc-123"


def test_get_sid_from_request_missing():
    """Проверяет отсутствие cookie"""
    request = _make_request(None)
    assert get_sid_from_request(request) is None


def test_set_sid_cookie_flags():
    """Проверяет флаги установки cookie"""
    response = Response()
    set_sid_cookie(response, "abc-123")
    header = response.headers["set-cookie"]
    assert "exposlides_sid=abc-123" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert f"Max-Age={settings.cookie_max_age}" in header
    assert "Path=/" in header


def test_new_sid_unique():
    """Проверяет уникальность sid"""
    a = new_sid()
    b = new_sid()
    assert a != b
    assert len(a) == 36
    assert len(b) == 36