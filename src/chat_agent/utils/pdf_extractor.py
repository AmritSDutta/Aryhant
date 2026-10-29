"""PDF text and structure extractor utility using LiteParse."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def extract_pdf_markdown(pdf_source: bytes | str) -> str:
    """Extract Markdown text from PDF bytes or filepath using LiteParse without OCR."""
    if not pdf_source:
        return ""
    try:
        from liteparse import LiteParse

        parser = LiteParse(
            output_format="markdown",
            ocr_enabled=False,
            quiet=True,
        )
        result = parser.parse(pdf_source)
        return (getattr(result, "text", "") or "").strip()
    except Exception as e:
        logger.warning("LiteParse PDF extraction failed: %s", e)
        return ""
