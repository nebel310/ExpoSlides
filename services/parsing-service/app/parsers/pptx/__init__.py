"""PPTX parser package."""

from app.parsers.pptx.assets import AssetBlob
from app.parsers.pptx.parser import ParseResult, PPTXParser

__all__ = ["PPTXParser", "ParseResult", "AssetBlob"]