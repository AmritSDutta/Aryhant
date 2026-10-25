"""Color palettes and styling themes for lesson infographics."""
from __future__ import annotations

from reportlab.lib import colors

_SUBJECT_PALETTES: dict[str, tuple[colors.Color, colors.Color, colors.Color]] = {
    "math": (colors.HexColor("#0284C7"), colors.HexColor("#E0F2FE"), colors.HexColor("#0369A1")),
    "physics": (colors.HexColor("#D97706"), colors.HexColor("#FEF3C7"), colors.HexColor("#92400E")),
    "cs": (colors.HexColor("#4F46E5"), colors.HexColor("#EEF2FF"), colors.HexColor("#3730A3")),
    "chemistry": (colors.HexColor("#059669"), colors.HexColor("#D1FAE5"), colors.HexColor("#065F46")),
    "biology": (colors.HexColor("#10B981"), colors.HexColor("#ECFDF5"), colors.HexColor("#047857")),
    "chess": (colors.HexColor("#7C3AED"), colors.HexColor("#EDE9FE"), colors.HexColor("#5B21B6")),
    "general": (colors.HexColor("#0F766E"), colors.HexColor("#CCFBF1"), colors.HexColor("#115E59")),
}

_STEP_ACCENTS: list[colors.Color] = [
    colors.HexColor("#2563EB"),
    colors.HexColor("#059669"),
    colors.HexColor("#D97706"),
    colors.HexColor("#7C3AED"),
    colors.HexColor("#E11D48"),
    colors.HexColor("#0D9488"),
]


def _get_subject_palette(subject: str) -> tuple[colors.Color, colors.Color, colors.Color]:
    """Retrieve color tuple (accent, badge_bg, badge_txt) for a given academic subject."""
    sub = (subject or "").lower()
    for key, palette in _SUBJECT_PALETTES.items():
        if key in sub:
            return palette
    return _SUBJECT_PALETTES["general"]

