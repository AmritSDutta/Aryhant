"""Automated lesson infographic PDF generator.

Modular, white-labelable educational poster engine supporting custom
branding profiles, two-pass pagination, clean vector illustrations,
and ReportLab Platypus document composition.
"""
from .builder import generate_lesson_infographic
from .canvas import InfographicCanvas, create_canvas_maker
from .config import InfographicBranding, find_icon, get_default_branding, resolve_branding
from .diagrams import render_step_diagram
try:
    from .notes_builder import HandwrittenNotesCanvas, generate_handwritten_notes_pdf
except ImportError:  # pragma: no cover
    HandwrittenNotesCanvas = None  # type: ignore[misc,assignment]
    generate_handwritten_notes_pdf = None  # type: ignore[misc,assignment]

__all__ = [
    "generate_lesson_infographic",
    "generate_handwritten_notes_pdf",
    "render_step_diagram",
    "InfographicCanvas",
    "HandwrittenNotesCanvas",
    "create_canvas_maker",
    "InfographicBranding",
    "get_default_branding",
    "resolve_branding",
    "find_icon",
]
