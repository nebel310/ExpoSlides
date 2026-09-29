
import pytest
from app.network import ALLOWED_FORMATS, _normalize_formats

pytestmark = pytest.mark.unit


def test_normalize_formats_none():
    """None превращается в pptx"""
    assert _normalize_formats(None) == {"pptx"}


def test_normalize_formats_empty():
    """Пустой список превращается в pptx"""
    assert _normalize_formats([]) == {"pptx"}


def test_normalize_formats_adds_pptx():
    """pptx всегда добавляется"""
    assert _normalize_formats(["pdf"]) == {"pptx", "pdf"}
    assert _normalize_formats(["html"]) == {"pptx", "html"}


def test_normalize_formats_lowercases():
    """Регистр не важен"""
    assert _normalize_formats(["PDF", "Html"]) == {"pptx", "pdf", "html"}


def test_normalize_formats_ignores_unknown():
    """Неизвестные форматы отбрасываются"""
    assert _normalize_formats(["docx", "pptx"]) == {"pptx"}
    assert _normalize_formats(["exe"]) == {"pptx"}


def test_normalize_formats_ignores_non_string():
    """Не-строки игнорируются"""
    assert _normalize_formats(["pdf", 123, None, "html"]) == {"pptx", "pdf", "html"}


def test_allowed_formats_contains_expected():
    """ALLOWED_FORMATS содержит только известные форматы"""
    assert ALLOWED_FORMATS == {"pptx", "pdf", "html"}