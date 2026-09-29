import pytest
from app.errors import SlideReuseNotSupportedError
from app.utils.clone import clone_slide


def test_clone_slide_always_raises():
    """clone_slide всегда отклоняет клонирование"""
    with pytest.raises(SlideReuseNotSupportedError):
        clone_slide(object(), object(), object())