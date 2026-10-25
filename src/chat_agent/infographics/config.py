"""Branding and configuration engine for lesson infographics.

Decouples product-specific strings, headings, disclaimers, and icons into
InfographicBranding objects for 100% multi-product reusability.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union


@dataclass
class InfographicBranding:
    """Product-specific branding and copy for educational infographics."""

    product_name: str = "Aryhant"
    brand_title: str = "Aryhant INFOGRAPHICS"
    header_subtitle: str = "Interactive AI Study Sheet • Visual Learning"
    hero_label: str = "Aryhant STUDY BRAIN"
    icon_names: list[str] = field(default_factory=lambda: ["vedantu.jpg", "icon.ico"])
    running_header: str = "Aryhant INFOGRAPHICS • Interactive AI Study Sheet"
    disclaimer: str = "Disclaimer: AI generated, check before applying in real life"
    footer_format: str = "{product_name} • Lesson Study Infographic • Saved automatically to {save_path} • All rights reserved"
    takeaways_header: str = "Key Takeaways:"
    checkpoint_prefix: str = "? Checkpoint:"
    milestone_prefix: str = "Milestone #"
    step_prefix: str = "STEP"
    output_dir_name: str = "infographics"
    filename_prefix: str = "infographic"
    icon_path: Optional[str] = None

    def __post_init__(self):
        if self.icon_path is None and self.icon_names:
            self.icon_path = find_icon(self.icon_names)

    @classmethod
    def from_dict(cls, data: dict) -> InfographicBranding:
        """Create an InfographicBranding instance from a dictionary."""
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> InfographicBranding:
        """Load an InfographicBranding instance from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    def format_footer(self, save_path: str) -> str:
        """Format the poster footer string."""
        return self.footer_format.format(
            product_name=self.product_name,
            save_path=save_path,
        )


def get_current_date_str() -> str:
    """Returns the current date formatted for document headers."""
    return datetime.now().strftime("%B %d, %Y")


def get_infographics_dir() -> Path:
    """Return local temporary directory for infographic study sheets."""
    target = Path(tempfile.gettempdir()) / "aryhant_infographics"
    target.mkdir(parents=True, exist_ok=True)
    return target


def find_icon(icon_names: list[str] | None = None) -> Optional[str]:
    """Locate a brand icon by searching bundle, package, and project directories."""
    if icon_names is None:
        icon_names = ["vedantu.jpg", "icon.ico"]
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(pkg_dir, "..", "..", ".."))

    candidates = [
        getattr(sys, "_MEIPASS", ""),
        os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else "",
        project_root,
        os.path.join(project_root, "assets"),
        os.path.abspath(os.path.join(pkg_dir, "..", "..")),
        pkg_dir,
        os.getcwd(),
        tempfile.gettempdir(),
    ]
    for base in candidates:
        if not base:
            continue
        for name in icon_names:
            p = os.path.normpath(os.path.join(base, name))
            if os.path.exists(p) and os.path.isfile(p):
                return os.path.abspath(p)
    return None


def find_truetype_font(font_names: list[str]) -> Optional[str]:
    """Locate an existing TrueType font across Cloud Run (Linux), Windows, and macOS paths."""
    search_dirs = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/truetype/liberation",
        "/usr/share/fonts/truetype",
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        "C:/Windows/Fonts",
        os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
        os.path.expanduser("~/.fonts"),
        os.path.expanduser("~/.local/share/fonts"),
        "/Library/Fonts",
        "/System/Library/Fonts",
    ]
    for name in font_names:
        for d in search_dirs:
            if not d or not os.path.isdir(d):
                continue
            full = os.path.normpath(os.path.join(d, name))
            if os.path.isfile(full):
                return full
    return None


_DEVA_REGEX: re.Pattern[str] = re.compile(
    r"([\u0900-\u097F]+(?:[\s\u200c\u200d\u0964\u0965]+[\u0900-\u097F]+)*)"
)
_BENG_REGEX: re.Pattern[str] = re.compile(
    r"([\u0980-\u09FF]+(?:[\s\u200c\u200d\u0964\u0965]+[\u0980-\u09FF]+)*)"
)
_OTHER_INDIC_REGEX: re.Pattern[str] = re.compile(
    r"([\u0A00-\u0DFF]+(?:[\s\u200c\u200d\u0964\u0965]+[\u0A00-\u0DFF]+)*)"
)
_INDIC_REGEX: re.Pattern[str] = re.compile(
    r"([\u0900-\u0DFF]+(?:[\s\u200c\u200d\u0964\u0965]+[\u0900-\u0DFF]+)*)"
)

_FONTS_REGISTERED: bool = False
_PRIMARY_FONT: str = "Helvetica"
_PRIMARY_BOLD: str = "Helvetica-Bold"
_PRIMARY_ITALIC: str = "Helvetica-Oblique"
_INDIC_FONT: Optional[str] = None
_DEVA_FONT: Optional[str] = None
_BENG_FONT: Optional[str] = None

_FONT_SEARCH_DIRS: list[str] = [
    "C:/Windows/Fonts",
    os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/opentype/noto",
    "/usr/share/fonts/truetype/lohit-devanagari",
    "/usr/share/fonts/truetype/lohit-bengali",
    "/usr/share/fonts/truetype/freefont",
    "/usr/share/fonts/truetype/mukti",
    "/usr/share/fonts/truetype/kalpurush",
    "/usr/share/fonts/truetype/gargi",
    "/usr/share/fonts/truetype/samyak",
    "/usr/share/fonts/truetype",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
    os.path.expanduser("~/.local/share/fonts"),
    "/Library/Fonts",
    "/System/Library/Fonts",
]


def find_font_for_script(script: str = "deva") -> Optional[tuple[str, int]]:
    """Locate an existing TrueType/TTC font file for a specific script across Windows, Linux, and macOS."""
    if script == "beng":
        candidates = [
            ("Nirmala.ttc", 0),
            ("NotoSansBengali-Regular.ttf", 0),
            ("Lohit-Bengali.ttf", 0),
            ("vrinda.ttf", 0),
            ("shonar.ttf", 0),
            ("MuktiNarrow.ttf", 0),
            ("Kalpurush.ttf", 0),
            ("FreeSans.ttf", 0),
        ]
    elif script == "deva":
        candidates = [
            ("Nirmala.ttc", 0),
            ("NotoSansDevanagari-Regular.ttf", 0),
            ("Lohit-Devanagari.ttf", 0),
            ("mangal.ttf", 0),
            ("gargi.ttf", 0),
            ("Samyak-Devanagari.ttf", 0),
            ("FreeSans.ttf", 0),
        ]
    else:
        candidates = [
            ("Nirmala.ttc", 0),
            ("NotoSans-Regular.ttf", 0),
            ("FreeSans.ttf", 0),
        ]

    for d in _FONT_SEARCH_DIRS:
        if not d or not os.path.isdir(d):
            continue
        for name, sub_idx in candidates:
            full = os.path.normpath(os.path.join(d, name))
            if os.path.isfile(full):
                return full, sub_idx
    return None


def find_indic_font() -> Optional[tuple[str, int]]:
    """Locate an existing Indic font file (Devanagari or universal fallback)."""
    return find_font_for_script("deva") or find_font_for_script("beng") or find_font_for_script("indic")


def register_pdf_fonts() -> tuple[str, str, str, Optional[str]]:
    """Register primary, Devanagari, and Bengali TrueType fonts for ReportLab."""
    global _FONTS_REGISTERED, _PRIMARY_FONT, _PRIMARY_BOLD, _PRIMARY_ITALIC, _INDIC_FONT, _DEVA_FONT, _BENG_FONT
    if _FONTS_REGISTERED:
        return _PRIMARY_FONT, _PRIMARY_BOLD, _PRIMARY_ITALIC, _INDIC_FONT

    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        registered: set[str] = set(pdfmetrics.getRegisteredFontNames())

        # 1. Primary Sans-Serif font
        segoe_regular = find_truetype_font(["segoeui.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
        segoe_bold = find_truetype_font(["segoeuib.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"])
        segoe_italic = find_truetype_font(["segoeuii.ttf", "DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf"])
        segoe_bold_italic = find_truetype_font(["segoeuiz.ttf", "DejaVuSans-BoldOblique.ttf", "LiberationSans-BoldItalic.ttf"])

        if segoe_regular and os.path.isfile(segoe_regular):
            try:
                if "SegoeUI" not in registered:
                    pdfmetrics.registerFont(TTFont("SegoeUI", segoe_regular))
                    b_font = "SegoeUI"
                    if segoe_bold and os.path.isfile(segoe_bold):
                        pdfmetrics.registerFont(TTFont("SegoeUI-Bold", segoe_bold))
                        b_font = "SegoeUI-Bold"
                    i_font = "SegoeUI"
                    if segoe_italic and os.path.isfile(segoe_italic):
                        pdfmetrics.registerFont(TTFont("SegoeUI-Italic", segoe_italic))
                        i_font = "SegoeUI-Italic"
                    bi_font = b_font
                    if segoe_bold_italic and os.path.isfile(segoe_bold_italic):
                        pdfmetrics.registerFont(TTFont("SegoeUI-BoldItalic", segoe_bold_italic))
                        bi_font = "SegoeUI-BoldItalic"
                    pdfmetrics.registerFontFamily(
                        "SegoeUI",
                        normal="SegoeUI",
                        bold=b_font,
                        italic=i_font,
                        boldItalic=bi_font,
                    )
                _PRIMARY_FONT = "SegoeUI"
                _PRIMARY_BOLD = "SegoeUI-Bold" if "SegoeUI-Bold" in pdfmetrics.getRegisteredFontNames() else "SegoeUI"
                _PRIMARY_ITALIC = "SegoeUI-Italic" if "SegoeUI-Italic" in pdfmetrics.getRegisteredFontNames() else "SegoeUI"
            except Exception:
                _PRIMARY_FONT = "Helvetica"
                _PRIMARY_BOLD = "Helvetica-Bold"
                _PRIMARY_ITALIC = "Helvetica-Oblique"

        # 2. Devanagari (Hindi) font
        deva_res = find_font_for_script("deva")
        if deva_res:
            deva_path, deva_idx = deva_res
            font_name = "NirmalaUI" if "nirmala" in deva_path.lower() else "DevanagariFont"
            if font_name not in registered:
                try:
                    pdfmetrics.registerFont(TTFont(font_name, deva_path, subfontIndex=deva_idx))
                    b_deva = font_name
                    if "nirmala" in deva_path.lower():
                        try:
                            pdfmetrics.registerFont(TTFont(f"{font_name}-Bold", deva_path, subfontIndex=1))
                            b_deva = f"{font_name}-Bold"
                        except Exception:
                            pass
                    else:
                        deva_bold_file = find_truetype_font(["NotoSansDevanagari-Bold.ttf"])
                        if deva_bold_file:
                            pdfmetrics.registerFont(TTFont(f"{font_name}-Bold", deva_bold_file))
                            b_deva = f"{font_name}-Bold"
                    pdfmetrics.registerFontFamily(
                        font_name,
                        normal=font_name,
                        bold=b_deva,
                        italic=font_name,
                        boldItalic=b_deva,
                    )
                    _DEVA_FONT = font_name
                except Exception:
                    _DEVA_FONT = None
            else:
                _DEVA_FONT = font_name

        # 3. Bengali font
        beng_res = find_font_for_script("beng")
        if beng_res:
            beng_path, beng_idx = beng_res
            # If Nirmala UI was already registered for Devanagari, it covers Bengali as well
            if "nirmala" in beng_path.lower() and _DEVA_FONT == "NirmalaUI":
                _BENG_FONT = "NirmalaUI"
            else:
                font_name = "BengaliFont"
                if font_name not in registered:
                    try:
                        pdfmetrics.registerFont(TTFont(font_name, beng_path, subfontIndex=beng_idx))
                        b_beng = font_name
                        beng_bold_file = find_truetype_font(["NotoSansBengali-Bold.ttf"])
                        if beng_bold_file:
                            pdfmetrics.registerFont(TTFont(f"{font_name}-Bold", beng_bold_file))
                            b_beng = f"{font_name}-Bold"
                        pdfmetrics.registerFontFamily(
                            font_name,
                            normal=font_name,
                            bold=b_beng,
                            italic=font_name,
                            boldItalic=b_beng,
                        )
                        _BENG_FONT = font_name
                    except Exception:
                        _BENG_FONT = None
                else:
                    _BENG_FONT = font_name

        _INDIC_FONT = _DEVA_FONT or _BENG_FONT
    except Exception:
        pass

    _FONTS_REGISTERED = True
    return _PRIMARY_FONT, _PRIMARY_BOLD, _PRIMARY_ITALIC, _INDIC_FONT


def escape_and_wrap_indic(text: str, indic_font: Optional[str] = None) -> str:
    """HTML-escape text and wrap Devanagari and Bengali script runs in their respective font tags."""
    if not text:
        return ""
    escaped: str = html.escape(str(text))
    deva_target = _DEVA_FONT or indic_font or _INDIC_FONT
    beng_target = _BENG_FONT or indic_font or _INDIC_FONT

    if deva_target and _DEVA_REGEX.search(escaped):
        escaped = _DEVA_REGEX.sub(rf'<font face="{deva_target}">\1</font>', escaped)

    if beng_target and _BENG_REGEX.search(escaped):
        escaped = _BENG_REGEX.sub(rf'<font face="{beng_target}">\1</font>', escaped)

    other_target = indic_font or _INDIC_FONT
    if other_target and _OTHER_INDIC_REGEX.search(escaped):
        escaped = _OTHER_INDIC_REGEX.sub(rf'<font face="{other_target}">\1</font>', escaped)

    return escaped


def get_pillow_font(size: int = 12, bold: bool = False, for_text: str = "") -> Any:
    """Load a TrueType font, selecting script-specific font when Bengali or Devanagari is present."""
    from PIL import ImageFont

    if for_text:
        if _BENG_REGEX.search(for_text):
            beng_res = find_font_for_script("beng")
            if beng_res:
                beng_path, sub_idx = beng_res
                active_idx = 1 if (bold and "nirmala" in beng_path.lower()) else sub_idx
                try:
                    return ImageFont.truetype(beng_path, size, index=active_idx)
                except Exception:
                    try:
                        return ImageFont.truetype(beng_path, size, index=sub_idx)
                    except Exception:
                        pass
        elif _DEVA_REGEX.search(for_text) or _INDIC_REGEX.search(for_text):
            deva_res = find_font_for_script("deva")
            if deva_res:
                deva_path, sub_idx = deva_res
                active_idx = 1 if (bold and "nirmala" in deva_path.lower()) else sub_idx
                try:
                    return ImageFont.truetype(deva_path, size, index=active_idx)
                except Exception:
                    try:
                        return ImageFont.truetype(deva_path, size, index=sub_idx)
                    except Exception:
                        pass

    candidates: list[str] = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
        "calibrib.ttf" if bold else "calibri.ttf",
    ]
    resolved = find_truetype_font(candidates)
    if resolved:
        try:
            return ImageFont.truetype(resolved, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


_DEFAULT_BRANDING_FILE = os.path.join(os.path.dirname(__file__), "branding.json")
_CACHED_DEFAULT: Optional[InfographicBranding] = None


def get_default_branding() -> InfographicBranding:
    """Return the default product branding from branding.json."""
    global _CACHED_DEFAULT
    if _CACHED_DEFAULT is None:
        if os.path.exists(_DEFAULT_BRANDING_FILE):
            try:
                _CACHED_DEFAULT = InfographicBranding.from_json(_DEFAULT_BRANDING_FILE)
            except Exception:
                _CACHED_DEFAULT = InfographicBranding()
        else:
            _CACHED_DEFAULT = InfographicBranding()
    return _CACHED_DEFAULT


def resolve_branding(
    branding: Optional[Union[InfographicBranding, dict, str, Path]] = None
) -> InfographicBranding:
    """Resolve an incoming branding argument into a valid InfographicBranding object."""
    if branding is None:
        return get_default_branding()
    if isinstance(branding, InfographicBranding):
        return branding
    if isinstance(branding, dict):
        base = get_default_branding()
        data = {k: getattr(base, k) for k in base.__dataclass_fields__}
        data.update(branding)
        return InfographicBranding.from_dict(data)
    if isinstance(branding, (str, Path)):
        return InfographicBranding.from_json(branding)
    return get_default_branding()
