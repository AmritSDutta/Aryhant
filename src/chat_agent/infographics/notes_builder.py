"""Platypus PDF document builder for handwritten notebook-style study notes."""
from __future__ import annotations

import html
import io
import logging
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from chat_agent.utils.math_formatter import clean_math_text
from .config import (
    _INDIC_REGEX,
    InfographicBranding,
    escape_and_wrap_indic,
    get_current_date_str,
    get_infographics_dir,
    get_pillow_font,
    register_pdf_fonts,
    resolve_branding,
)


def get_notes_dir() -> Path:
    """Return local temporary directory for study notes."""
    target = Path(tempfile.gettempdir()) / "aryhant_notes"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_diagrams_dir() -> Path:
    """Return local temporary directory for diagrams."""
    target = Path(tempfile.gettempdir()) / "aryhant_diagrams"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_reports_dir() -> Path:
    """Return local temporary directory for reports."""
    target = Path(tempfile.gettempdir()) / "aryhant_reports"
    target.mkdir(parents=True, exist_ok=True)
    return target


_RULE_SPACING: float = 26.0
_MARGIN_LINE_X: float = 78.0

_SUB_CHARS: str = "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎"
_SUP_CHARS: str = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ"
_SUB_MAP = str.maketrans(_SUB_CHARS, "0123456789+-=()")
_SUP_MAP = str.maketrans(_SUP_CHARS, "0123456789+-=()n")
logger = logging.getLogger(__name__)


def _register_notebook_fonts() -> tuple[str, str, str, Optional[str]]:
    """Register Segoe UI and Nirmala UI / Noto Sans fonts for crisp formulas and Indic scripts."""
    return register_pdf_fonts()


def _normalize_sub_super_scripts(text: str) -> str:
    """Normalize Unicode sub/superscripts to <sub> and <sup> tags outside code fences and inline code."""
    lines = text.splitlines()
    in_fence = False
    processed: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            processed.append(line)
            continue
        if in_fence:
            processed.append(line)
            continue
        parts = line.split("`")
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(
                f"([{_SUB_CHARS}]+)",
                lambda m: f"<sub>{m.group(1).translate(_SUB_MAP)}</sub>",
                parts[i],
            )
            parts[i] = re.sub(
                f"([{_SUP_CHARS}]+)",
                lambda m: f"<sup>{m.group(1).translate(_SUP_MAP)}</sup>",
                parts[i],
            )
        processed.append("`".join(parts))
    return "\n".join(processed)


def _escape_and_wrap_indic(text: str, indic_font: Optional[str] = None) -> str:
    """HTML-escape text and wrap Indic script runs in <font face=...> tags."""
    return escape_and_wrap_indic(text, indic_font)


class HandwrittenNotesCanvas(canvas.Canvas):
    """Two-pass ReportLab canvas for total page count and notebook footers."""

    branding: InfographicBranding = InfographicBranding()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count: int) -> None:
        self.saveState()

        # Top-left Choh Brand Icon Box (rendered on every page)
        if self.branding.icon_path and os.path.isfile(self.branding.icon_path):
            box_x, box_y, box_size = 20, 736, 38
            self.setFillColor(colors.HexColor("#FFFFFF"))
            self.setStrokeColor(colors.HexColor("#EBDCCB"))
            self.setLineWidth(1)
            self.roundRect(box_x, box_y, box_size, box_size, 6, fill=1, stroke=1)
            pad = 3
            self.drawImage(
                self.branding.icon_path,
                box_x + pad,
                box_y + pad,
                width=box_size - (pad * 2),
                height=box_size - (pad * 2),
                preserveAspectRatio=True,
                mask="auto",
            )

        primary_font, _, _, indic_font = _register_notebook_fonts()
        header_text = f"{self.branding.product_name} Study Notes"
        header_font = indic_font if (
                    indic_font and _INDIC_REGEX.search(header_text if self._pageNumber > 1 else "")) else primary_font
        self.setFont(header_font, 7.5)
        self.setFillColor(colors.HexColor("#8C7E68"))

        # Running header on multi-page notes (pages 2+)
        if self._pageNumber > 1:
            self.drawString(96, 792 - 24, header_text)
            self.setStrokeColor(colors.HexColor("#C9BDA8"))
            self.setLineWidth(0.5)
            self.line(96, 792 - 28, 612 - 36, 792 - 28)

        # Bottom-left: brand disclaimer
        disclaimer_text = self.branding.disclaimer or f"{self.branding.product_name} Interactive AI Tutor \u2022 Study Notes"
        disc_font = indic_font if (indic_font and _INDIC_REGEX.search(disclaimer_text)) else primary_font
        self.setFont(disc_font, 7.5)
        self.drawString(96, 18, disclaimer_text)

        # Bottom-right: page count
        self.setFont(primary_font, 7.5)
        self.drawRightString(612 - 36, 18, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def _create_notes_canvas_maker(branding: InfographicBranding):
    """Factory creating a HandwrittenNotesCanvas subclass bound to specific branding."""

    class BoundNotesCanvas(HandwrittenNotesCanvas):
        pass

    BoundNotesCanvas.branding = branding
    return BoundNotesCanvas


class _TagPills(Flowable):
    """Row of dashed notebook tag pills carrying the notes metadata (canvas.html header style)."""

    def __init__(self, items: list[str]) -> None:
        super().__init__()
        self._items = [str(i).upper() for i in items if str(i).strip()]
        self._font_size = 7.5
        self._pad_x = 7.0
        self._pad_y = 3.5
        self._gap = 6.0
        self._row_gap = 4.0
        self.spaceAfter = 10
        self._rows: list[list[tuple[float, str]]] = []

    def _font_for(self, text: str) -> str:
        _, primary_bold, _, indic_font = _register_notebook_fonts()
        if indic_font and _INDIC_REGEX.search(text):
            return indic_font
        return primary_bold

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        self._rows = []
        row: list[tuple[float, str]] = []
        row_w = 0.0
        pill_h = self._font_size + 2 * self._pad_y
        for text in self._items:
            font = self._font_for(text)
            pill_w = pdfmetrics.stringWidth(text, font, self._font_size) + 2 * self._pad_x
            extra = self._gap if row else 0.0
            if row and row_w + extra + pill_w > availWidth:
                self._rows.append(row)
                row, row_w = [], 0.0
                extra = 0.0
            row.append((pill_w, text))
            row_w += extra + pill_w
        if row:
            self._rows.append(row)
        self.width = availWidth
        self.height = len(self._rows) * pill_h + max(0, len(self._rows) - 1) * self._row_gap
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        pill_h = self._font_size + 2 * self._pad_y
        y = self.height - pill_h
        c.saveState()
        for row in self._rows:
            x = 0.0
            for pill_w, text in row:
                c.setFillColor(colors.HexColor("#FDF3D7"))
                c.setStrokeColor(colors.HexColor("#D5B882"))
                c.setLineWidth(0.9)
                c.setDash(2, 2)
                c.roundRect(x, y, pill_w, pill_h, 4, fill=1, stroke=1)
                c.setDash()
                c.setFillColor(colors.HexColor("#9C6819"))
                font = self._font_for(text)
                c.setFont(font, self._font_size)
                c.drawCentredString(x + pill_w / 2.0, y + self._pad_y, text)
                x += pill_w + self._gap
            y -= pill_h + self._row_gap
        c.restoreState()


class _WavyUnderline(Flowable):
    """Short green wavy underline beneath the notes title (canvas.html accent)."""

    def __init__(self, width_pt: float = 150.0) -> None:
        super().__init__()
        self._width_pt = width_pt
        self.spaceAfter = 8

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        self.width = min(self._width_pt, availWidth)
        self.height = 8
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.setStrokeColor(colors.HexColor("#15803D"))
        c.setLineWidth(2)
        c.setLineCap(1)
        path = c.beginPath()
        steps = 26
        for i in range(steps + 1):
            x = self.width * i / steps
            y = 4 + 3 * math.sin(i * math.pi / 3)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        c.drawPath(path, stroke=1, fill=0)
        c.restoreState()


class _CardHeading(Flowable):
    """White card heading with a 2px ink border and hard offset shadow (canvas.html card style)."""

    def __init__(self, text: str, style: ParagraphStyle) -> None:
        super().__init__()
        self._para = Paragraph(text, style)
        self._pad_x = 10.0
        self._pad_y = 7.0
        self._shadow = 3.0
        self._gap_after = 8.0
        self.spaceBefore = 10
        self._box_w = 0.0
        self._box_h = 0.0

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        text_w = max(availWidth - 2 * self._pad_x - self._shadow - 4, 40)
        _, text_h = self._para.wrap(text_w, availHeight)
        self._box_w = max(availWidth - self._shadow, 60)
        self._box_h = text_h + 2 * self._pad_y
        self.width = availWidth
        self.height = self._box_h + self._shadow + self._gap_after
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        face_y = self.height - self._box_h
        c.saveState()
        # Hard offset shadow (bottom-right)
        c.setFillColor(colors.HexColor("#161616"))
        c.roundRect(self._shadow, face_y - self._shadow, self._box_w - self._shadow, self._box_h, 8, fill=1, stroke=0)
        # White card face with 2px ink border
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#161616"))
        c.setLineWidth(1.6)
        c.roundRect(0, face_y, self._box_w - self._shadow, self._box_h, 8, fill=1, stroke=1)
        self._para.drawOn(c, self._pad_x, face_y + self._pad_y)
        c.restoreState()


def _draw_notebook_background(
        c: canvas.Canvas,
        doc: SimpleDocTemplate,
        margin_tip: str = "",
        draw_ruled_lines: bool = False,
) -> None:
    """Paint cream paper fill, red margin, optional rotated margin tip, and optional ruled lines."""
    c.saveState()

    # 1. Cream notebook background
    c.setFillColor(colors.HexColor("#FBF7EE"))
    c.rect(0, 0, 612, 792, stroke=0, fill=1)

    # 2. Optional horizontal ruled lines (disabled by default)
    if draw_ruled_lines:
        c.setStrokeColor(colors.HexColor("#EBDCCB"))
        c.setLineWidth(0.75)
        y = _RULE_SPACING
        while y < 768:
            c.line(0, y, 612, y)
            y += _RULE_SPACING

    # 3. Vertical coral margin rule at x=78
    c.setStrokeColor(colors.HexColor("#F2A69D"))
    c.setLineWidth(1.5)
    c.line(_MARGIN_LINE_X, 0, _MARGIN_LINE_X, 792)

    # 4. Optional rotated margin tip on page 1 (positioned below top-left icon box)
    if margin_tip and c._pageNumber == 1:
        c.saveState()
        c.setFillColor(colors.HexColor("#D63031"))
        c.translate(14, 698)
        c.rotate(-6)
        sanitized_tip = margin_tip.replace("★", "*").replace("☆", "*")
        _, primary_bold, _, indic_font = _register_notebook_fonts()
        has_indic = bool(indic_font and _INDIC_REGEX.search(sanitized_tip))
        tip_font = (
            f"{indic_font}-Bold"
            if (has_indic and f"{indic_font}-Bold" in pdfmetrics.getRegisteredFontNames())
            else (indic_font if has_indic else primary_bold)
        )
        c.setFont(tip_font, 10)
        c.drawString(0, 0, sanitized_tip[:36])
        c.restoreState()

    c.restoreState()


def inner_xml_to_reportlab(elem: ET.Element, indic_font: Optional[str] = None) -> str:
    """Recursively convert inner XML elements to ReportLab Paragraph markup."""
    chunks: list[str] = []
    if elem.text:
        chunks.append(_escape_and_wrap_indic(elem.text, indic_font))
    for child in elem:
        tag = child.tag.lower()
        child_content = inner_xml_to_reportlab(child, indic_font)
        if tag == "strong":
            chunks.append(f"<b>{child_content}</b>")
        elif tag == "em":
            chunks.append(f"<i>{child_content}</i>")
        elif tag == "sub":
            chunks.append(f"<sub>{child_content}</sub>")
        elif tag == "sup":
            chunks.append(f"<sup>{child_content}</sup>")
        elif tag == "code":
            chunks.append(f'<font face="Courier" color="#161616"><b>{child_content}</b></font>')
        elif tag == "mark" or (tag == "span" and "highlight" in child.attrib.get("class", "")):
            chunks.append(f'<font backColor="#FFEAA7">{child_content}</font>')
        elif tag == "a":
            href = child.attrib.get("href", "")
            if href.startswith(("http://", "https://", "mailto:")):
                escaped_href = html.escape(href, quote=True)
                chunks.append(f'<a href="{escaped_href}" color="#15803D"><u>{child_content}</u></a>')
            else:
                chunks.append(f'<font color="#161616">{child_content}</font>')
        elif tag == "br":
            chunks.append("<br/>")
        else:
            chunks.append(child_content)
        if child.tail:
            chunks.append(_escape_and_wrap_indic(child.tail, indic_font))
    return "".join(chunks)


def _preprocess_highlights(content: str) -> str:
    """Transform ==highlight== to <mark>highlight</mark> strictly outside code fences and inline code."""
    lines = content.splitlines()
    in_fence = False
    processed_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            processed_lines.append(line)
            continue
        if in_fence:
            processed_lines.append(line)
            continue

        parts = line.split("`")
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r"==(?!\s)([^=\r\n]+?)(?<!\s)==", r"<mark>\1</mark>", parts[i])
        processed_lines.append("`".join(parts))
    return "\n".join(processed_lines)


def _resolve_image_path(path_str: Optional[str]) -> Optional[str]:
    """Resolve an image path from absolute, snaps, notes, or brain directories."""
    if not path_str or not isinstance(path_str, str):
        return None
    p = path_str.strip()
    if not p:
        return None
    if os.path.isfile(p):
        return os.path.abspath(p)
    candidates = [
        str(get_diagrams_dir() / os.path.basename(p)),
        str(get_reports_dir() / os.path.basename(p)),
        str(get_infographics_dir() / os.path.basename(p)),
        os.path.join("image", os.path.basename(p)),
    ]
    for cand in candidates:
        if os.path.isfile(cand):
            return os.path.abspath(cand)
    return None


def _create_image_flowable(
        img_path: str,
        caption: str,
        styles: dict[str, ParagraphStyle],
        max_w: float = 220.0,
        max_h: float = 130.0,
) -> Optional[Table]:
    """Create a scaled ReportLab image Table with an italic caption."""
    try:
        with Image.open(img_path) as pil_im:
            iw, ih = pil_im.size
        if iw <= 0 or ih <= 0:
            return None
        scale = min(max_w / max(iw, 1), max_h / max(ih, 1), 1.0)
        target_w, target_h = iw * scale, ih * scale
        rl_img = RLImage(img_path, width=target_w, height=target_h)
        caption_p = Paragraph(f"<i>Fig \u2014 {html.escape(caption)}</i>", styles["caption"])
        return Table(
            [[rl_img], [caption_p]],
            colWidths=[max(target_w, 224)],
            style=[
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ],
        )
    except Exception:
        return None


def _convert_markdown_to_flowables(
        content: str,
        styles: dict[str, ParagraphStyle],
        avail_w: float = 480.0,
        indic_font: Optional[str] = None,
) -> list:
    """Parse Markdown content into structured ReportLab flowables."""
    cleaned_math = clean_math_text(content)
    normalized_content = _normalize_sub_super_scripts(cleaned_math)
    processed_md = _preprocess_highlights(normalized_content)

    try:
        import markdown
        html_text = markdown.markdown(processed_md, extensions=["tables", "fenced_code"])
        root = ET.fromstring(f"<root>{html_text}</root>")
    except Exception:
        # Fallback to structured plain paragraphs if markdown or XML parsing fails
        plain_flowables = []
        for line in normalized_content.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("![") and "](" in line_str and line_str.endswith(")"):
                alt_txt, src_txt = line_str[2:-1].split("](", 1)
                resolved = _resolve_image_path(src_txt.strip())
                if resolved:
                    tbl = _create_image_flowable(resolved, alt_txt.strip() or "Diagram", styles,
                                                 max_w=min(avail_w, 360.0), max_h=180.0)
                    if tbl is not None:
                        plain_flowables.append(tbl)
                        continue
            if line_str.startswith("# "):
                plain_flowables.append(
                    Paragraph(_escape_and_wrap_indic(line_str[2:].strip(), indic_font), styles["h1"]))
            elif line_str.startswith("## "):
                plain_flowables.append(
                    Paragraph(_escape_and_wrap_indic(line_str[3:].strip(), indic_font), styles["h2"]))
            elif line_str.startswith("### "):
                plain_flowables.append(
                    Paragraph(_escape_and_wrap_indic(line_str[4:].strip(), indic_font), styles["h3"]))
            elif line_str.startswith(("- ", "* ")):
                plain_flowables.append(
                    Paragraph(f"&bull;  {_escape_and_wrap_indic(line_str[2:].strip(), indic_font)}", styles["bullet"]))
            elif line_str.startswith("> "):
                plain_flowables.append(
                    Paragraph(_escape_and_wrap_indic(line_str[2:].strip(), indic_font), styles["blockquote"]))
            else:
                plain_flowables.append(Paragraph(_escape_and_wrap_indic(line_str, indic_font), styles["body"]))
        return plain_flowables

    flowables = []
    for elem in root:
        tag = elem.tag.lower()
        if tag == "h1":
            text = inner_xml_to_reportlab(elem, indic_font)
            flowables.append(Paragraph(text, styles["h1"]))
        elif tag == "h2":
            text = inner_xml_to_reportlab(elem, indic_font)
            flowables.append(_CardHeading(text, styles["h2"]))
        elif tag == "h3":
            text = inner_xml_to_reportlab(elem, indic_font)
            flowables.append(Paragraph(text, styles["h3"]))
        elif tag == "p":
            img_child = elem.find("img")
            if img_child is not None and len(elem) == 1 and not (elem.text or "").strip():
                src = img_child.attrib.get("src", "").strip()
                alt = img_child.attrib.get("alt", "").strip() or "Diagram"
                resolved = _resolve_image_path(src)
                if resolved:
                    tbl = _create_image_flowable(resolved, alt, styles, max_w=min(avail_w, 360.0), max_h=180.0)
                    if tbl is not None:
                        flowables.append(tbl)
                        continue
            text = inner_xml_to_reportlab(elem, indic_font)
            if text:
                flowables.append(Paragraph(text, styles["body"]))
        elif tag == "img":
            src = elem.attrib.get("src", "").strip()
            alt = elem.attrib.get("alt", "").strip() or "Diagram"
            resolved = _resolve_image_path(src)
            if resolved:
                tbl = _create_image_flowable(resolved, alt, styles, max_w=min(avail_w, 360.0), max_h=180.0)
                if tbl is not None:
                    flowables.append(tbl)
        elif tag in ("ul", "ol"):
            is_ol = tag == "ol"
            for idx, li in enumerate(elem.findall("li"), start=1):
                li_text = inner_xml_to_reportlab(li, indic_font)
                bullet_prefix = f"{idx}." if is_ol else "&bull;"
                p_text = f"{bullet_prefix}  {li_text}"
                flowables.append(Paragraph(p_text, styles["bullet"]))
        elif tag == "hr":
            flowables.append(
                HRFlowable(width="100%", thickness=1, color=colors.HexColor("#F2A69D"), spaceAfter=8, spaceBefore=8))
        elif tag == "pre":
            code_elem = elem.find("code")
            code_text = code_elem.text if code_elem is not None and code_elem.text else elem.text or ""
            code_html = html.escape(code_text.strip()).replace("\n", "<br/>").replace("  ", "&nbsp;&nbsp;")
            flowables.append(Paragraph(code_html, styles["code"]))
        elif tag == "blockquote":
            bq_text = inner_xml_to_reportlab(elem, indic_font)
            flowables.append(Paragraph(bq_text, styles["blockquote"]))
        elif tag == "table":
            rows: list[list[Paragraph]] = []
            is_header_row: list[bool] = []

            thead = elem.find("thead")
            if thead is not None:
                for tr in thead.findall("tr"):
                    row = [Paragraph(inner_xml_to_reportlab(th, indic_font), styles["th"]) for th in tr]
                    if row:
                        rows.append(row)
                        is_header_row.append(True)

            tbody = elem.find("tbody")
            if tbody is not None:
                for tr in tbody.findall("tr"):
                    row = [Paragraph(inner_xml_to_reportlab(td, indic_font), styles["td"]) for td in tr]
                    if row:
                        rows.append(row)
                        is_header_row.append(False)

            if thead is None and tbody is None:
                for tr in elem.findall("tr"):
                    row = [Paragraph(inner_xml_to_reportlab(td, indic_font), styles["td"]) for td in tr]
                    if row:
                        rows.append(row)
                        is_header_row.append(False)

            if rows:
                num_cols = max(len(r) for r in rows)
                for r in rows:
                    while len(r) < num_cols:
                        r.append(Paragraph("", styles["td"]))

                col_w = avail_w / max(1, num_cols)
                t_style = [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#EBDCCB")),
                ]
                for r_idx, is_head in enumerate(is_header_row):
                    if is_head:
                        t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#FDF3D7")))
                    else:
                        bg_col = colors.HexColor("#FBF7EE") if r_idx % 2 == 1 else colors.white
                        t_style.append(("BACKGROUND", (0, r_idx), (-1, r_idx), bg_col))

                flowables.append(Spacer(1, 4))
                flowables.append(Table(rows, colWidths=[col_w] * num_cols, style=TableStyle(t_style)))
                flowables.append(Spacer(1, 6))
        else:
            text = "".join(elem.itertext()).strip()
            if text:
                flowables.append(Paragraph(html.escape(text), styles["body"]))
    return flowables


def _get_sketch_font(size: int = 11, bold: bool = False, for_text: str = "") -> ImageFont.ImageFont:
    """Load a clean TrueType or built-in font for sketched diagram labels."""
    return get_pillow_font(size=size, bold=bold, for_text=for_text)


def _draw_sketch_arrow(
        draw: ImageDraw.ImageDraw,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: tuple[int, int, int] = (26, 41, 66),
        width: int = 2,
        head_len: float = 6.0,
) -> None:
    """Draw a hand-sketched arrow with a directional polygon head."""
    draw.line([(x1, y1), (x2, y2)], fill=color, width=int(width))
    angle = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - head_len * math.cos(angle - math.pi / 6), y2 - head_len * math.sin(angle - math.pi / 6))
    p2 = (x2 - head_len * math.cos(angle + math.pi / 6), y2 - head_len * math.sin(angle + math.pi / 6))
    draw.polygon([(x2, y2), p1, p2], fill=color)


def render_notebook_sketch(
        title: str = "",
        domain: str = "",
        visual_suggestion: str = "",
        width: int = 260,
        height: int = 140,
) -> bytes:
    """Render an organic, notebook-style sketch illustration on a transparent canvas."""
    img = Image.new("RGBA", (width, height), (250, 248, 245, 0))
    draw = ImageDraw.Draw(img)

    dom = f"{domain} {visual_suggestion} {title}".lower()
    font_sm = _get_sketch_font(10, bold=True)
    font_lbl = _get_sketch_font(11, bold=False)

    if any(k in dom for k in ("bio", "photosynth", "plant", "leaf", "cell", "organ", "dna", "gene")):
        # Biology / Photosynthesis hand-drawn sketch (matching sample.html)
        draw.ellipse([(20, 14), (52, 46)], outline=(243, 156, 18), fill=(254, 249, 231), width=2)
        for x1, y1, x2, y2 in [
            (36, 6, 36, 12), (36, 48, 36, 54), (12, 30, 18, 30), (54, 30, 60, 30),
            (19, 17, 15, 13), (53, 43, 57, 47), (19, 43, 15, 47), (53, 17, 57, 13)
        ]:
            draw.line([(x1, y1), (x2, y2)], fill=(243, 156, 18), width=2)

        _draw_sketch_arrow(draw, 50, 40, 86, 62, color=(214, 48, 49), width=2)
        draw.text((66, 35), "hv (photons)", fill=(214, 48, 49), font=font_sm)

        leaf_pts = [
            (95, 108), (88, 86), (110, 65), (145, 58), (180, 65),
            (182, 88), (160, 110), (125, 118), (95, 108)
        ]
        draw.polygon(leaf_pts, fill=(234, 250, 241), outline=(39, 174, 96))
        draw.line([(95, 108), (180, 65)], fill=(39, 174, 96), width=2)
        draw.line([(115, 96), (125, 82)], fill=(39, 174, 96), width=1)
        draw.line([(138, 84), (152, 72)], fill=(39, 174, 96), width=1)

        draw.text((10, 90), "H2O + CO2", fill=(26, 41, 66), font=font_lbl)
        _draw_sketch_arrow(draw, 68, 96, 92, 101, color=(26, 41, 66), width=2)
        _draw_sketch_arrow(draw, 168, 93, 192, 104, color=(26, 41, 66), width=2)
        draw.text((156, 112), "O2 + Sugars", fill=(26, 41, 66), font=font_lbl)

    elif any(k in dom for k in ("quantum", "oscillator", "harmonic", "schrodinger", "potential", "wavepacket")):
        # Quantum / Harmonic Oscillator potential well and Gaussian ground state wavepacket
        ox, oy = 30, height - 20
        cx = width // 2 - 10
        _draw_sketch_arrow(draw, ox, oy, ox, 16, color=(100, 116, 139), width=1)
        _draw_sketch_arrow(draw, ox, oy, width - 16, oy, color=(100, 116, 139), width=1)
        draw.text((ox - 14, 14), "V", fill=(100, 116, 139), font=font_sm)
        draw.text((width - 14, oy + 2), "x", fill=(100, 116, 139), font=font_sm)

        # Potential well parabola V(x) = 1/2 k x^2
        parab_pts = []
        for xi in range(-55, 56, 3):
            px = cx + xi
            py = (oy - 8) - int((xi * xi) / 42.0)
            parab_pts.append((px, py))
        for i in range(len(parab_pts) - 1):
            draw.line([parab_pts[i], parab_pts[i + 1]], fill=(148, 163, 184), width=2)
        draw.text((cx + 36, 26), "V = 1/2 k x^2", fill=(100, 116, 139), font=font_sm)

        # Ground state level E0 line
        e0_y = oy - 28
        draw.line([(cx - 44, e0_y), (cx + 44, e0_y)], fill=(217, 119, 6), width=1)
        draw.text((cx + 48, e0_y - 6), "E0 = 1/2 hw", fill=(217, 119, 6), font=font_sm)

        # Ground state wavefunction psi0(x) Gaussian curve
        psi_pts = []
        for xi in range(-38, 39, 2):
            px = cx + xi
            py = e0_y - int(34.0 * math.exp(-(xi * xi) / 240.0))
            psi_pts.append((px, py))
        for i in range(len(psi_pts) - 1):
            draw.line([psi_pts[i], psi_pts[i + 1]], fill=(21, 128, 61), width=2)
        draw.text((cx - 16, e0_y - 42), "psi_0(x)", fill=(21, 128, 61), font=font_sm)

    elif any(k in dom for k in ("physic", "kinemat", "motion", "gravity", "force", "mechanic", "projectile")):
        ox, oy = 35, height - 24
        _draw_sketch_arrow(draw, ox, oy, ox, 18, color=(100, 116, 139), width=1)
        _draw_sketch_arrow(draw, ox, oy, width - 18, oy, color=(100, 116, 139), width=1)
        draw.text((ox - 14, 16), "y", fill=(100, 116, 139), font=font_sm)
        draw.text((width - 14, oy + 2), "x", fill=(100, 116, 139), font=font_sm)

        curve_pts = []
        for t in range(0, 26):
            x = ox + t * 7.5
            norm_t = (t - 12.5) / 12.5
            y = (oy - 80) + norm_t * norm_t * 80
            curve_pts.append((x, y))
        for i in range(len(curve_pts) - 1):
            draw.line([curve_pts[i], curve_pts[i + 1]], fill=(21, 128, 61), width=2)

        _draw_sketch_arrow(draw, ox, oy, ox + 36, oy - 36, color=(214, 48, 49), width=2)
        draw.text((ox + 40, oy - 46), "v0", fill=(214, 48, 49), font=font_sm)

        apex_x = ox + int(12.5 * 7.5)
        apex_y = oy - 80
        draw.ellipse([(apex_x - 3, apex_y - 3), (apex_x + 3, apex_y + 3)], fill=(26, 41, 66))
        _draw_sketch_arrow(draw, apex_x, apex_y, apex_x, apex_y + 26, color=(217, 119, 6), width=2)
        draw.text((apex_x + 6, apex_y + 8), "g", fill=(217, 119, 6), font=font_sm)
        draw.text((apex_x - 16, apex_y - 18), "h_max", fill=(26, 41, 66), font=font_lbl)

    elif any(k in dom for k in ("chem", "molecul", "atom", "bond", "reaction")):
        cx, cy = 80, 70
        r = 30
        pts = []
        for i in range(6):
            ang = i * (math.pi / 3) - math.pi / 6
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        for i in range(6):
            draw.line([pts[i], pts[(i + 1) % 6]], fill=(26, 41, 66), width=2)
        draw.ellipse([(cx - 15, cy - 15), (cx + 15, cy + 15)], outline=(21, 128, 61), width=1)

        draw.line([pts[0], (pts[0][0] + 20, pts[0][1] - 10)], fill=(26, 41, 66), width=2)
        draw.text((pts[0][0] + 24, pts[0][1] - 16), "OH", fill=(214, 48, 49), font=font_sm)

        _draw_sketch_arrow(draw, 130, cy, 175, cy, color=(16, 185, 129), width=2)
        draw.text((138, cy - 16), "+ H+", fill=(16, 185, 129), font=font_sm)
        draw.text((182, cy - 8), "Product", fill=(26, 41, 66), font=font_lbl)

    elif any(k in dom for k in ("math", "calculus", "function", "curve", "plot", "graph")):
        ox, oy = 35, height - 26
        _draw_sketch_arrow(draw, ox, oy, ox, 18, color=(100, 116, 139), width=1)
        _draw_sketch_arrow(draw, ox, oy, width - 18, oy, color=(100, 116, 139), width=1)
        draw.text((ox - 14, 16), "y", fill=(100, 116, 139), font=font_sm)
        draw.text((width - 14, oy + 2), "x", fill=(100, 116, 139), font=font_sm)

        pts = []
        for t in range(0, 32):
            x = ox + t * 6.0
            norm = t / 31.0
            y = oy - 12 - math.sin(norm * math.pi * 0.9) * 75
            pts.append((x, y))
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=(21, 128, 61), width=2)

        mx, my = pts[15]
        draw.ellipse([(mx - 3, my - 3), (mx + 3, my + 3)], fill=(214, 48, 49))
        draw.line([(mx - 26, my + 13), (mx + 30, my - 15)], fill=(214, 48, 49), width=1)
        draw.text((mx + 6, my - 28), "dy/dx = f'(x)", fill=(214, 48, 49), font=font_sm)

    else:
        nodes = [(55, 45, "Input"), (195, 45, "Process"), (125, 105, "Feedback")]
        for x, y, lbl in nodes:
            draw.ellipse([(x - 26, y - 16), (x + 26, y + 16)], outline=(26, 41, 66), fill=(254, 249, 231), width=2)
            draw.text((x - len(lbl) * 3.1, y - 6), lbl, fill=(26, 41, 66), font=font_sm)

        _draw_sketch_arrow(draw, 84, 45, 166, 45, color=(21, 128, 61), width=2)
        _draw_sketch_arrow(draw, 185, 63, 150, 93, color=(21, 128, 61), width=2)
        _draw_sketch_arrow(draw, 102, 93, 68, 63, color=(21, 128, 61), width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_handwritten_notes_pdf(
        title: str,
        content: str,
        tags: Optional[list[str]] = None,
        student_email: Optional[str] = None,
        visual: str = "",
        image_path: Optional[str] = None,
        subject: str = "general",
        margin_tip: str = "",
        output_path: Optional[str] = None,
        branding: Optional[Union[InfographicBranding, dict, str, Path]] = None,
        draw_ruled_lines: bool = False,
) -> str:
    """Generate a notebook-styled study notes PDF with ruled paper, margin, and branding."""
    brand = resolve_branding(branding)
    target_dir = get_notes_dir()

    clean_title = title.strip() or "Study Notes"
    clean_slug = re.sub(r"[^a-zA-Z0-9]+", "_", clean_title.lower()).strip("_")[:32]
    slug = clean_slug or "notes"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_filename = f"notes_{slug}_{timestamp}.pdf"
    if output_path:
        target_path = os.path.abspath(output_path)
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    else:
        target_path = str(target_dir / default_filename)

    margin_left = 96
    margin_right = 36
    avail_w = 612 - margin_left - margin_right

    doc = SimpleDocTemplate(
        target_path,
        pagesize=letter,
        leftMargin=margin_left,
        rightMargin=margin_right,
        topMargin=48,
        bottomMargin=48,
        title=f"{brand.product_name} Notes \u2013 {clean_title}",
        author=brand.product_name,
        subject=subject,
        creator=brand.product_name,
        displayDocTitle=True,
    )

    primary_font, primary_bold, primary_italic, indic_font = _register_notebook_fonts()

    styles = {
        "title": ParagraphStyle(
            "NotesTitle",
            fontName=primary_bold,
            fontSize=26,
            leading=30,
            textColor=colors.HexColor("#161616"),
            spaceAfter=4,
        ),
        "h1": ParagraphStyle(
            "NotesH1",
            fontName=primary_bold,
            fontSize=18,
            leading=24,
            textColor=colors.HexColor("#161616"),
            spaceBefore=10,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "NotesH2",
            fontName=primary_bold,
            fontSize=14,
            leading=20,
            textColor=colors.HexColor("#161616"),
            spaceBefore=8,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "NotesH3",
            fontName=primary_italic,
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#15803D"),
            spaceBefore=6,
            spaceAfter=2,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "NotesBody",
            fontName=primary_font,
            fontSize=11,
            leading=16,
            textColor=colors.HexColor("#161616"),
            spaceAfter=8,
        ),
        "bullet": ParagraphStyle(
            "NotesBullet",
            fontName=primary_font,
            fontSize=10.5,
            leading=15,
            textColor=colors.HexColor("#161616"),
            leftIndent=14,
            spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "NotesCode",
            fontName="Courier",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#161616"),
            backColor=colors.HexColor("#F1F5F9"),
            borderColor=colors.HexColor("#161616"),
            borderWidth=1,
            borderPadding=4,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "caption": ParagraphStyle(
            "NotesCaption",
            fontName=primary_italic,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#8C7E68"),
            alignment=1,
            spaceBefore=3,
        ),
        "blockquote": ParagraphStyle(
            "NotesBlockquote",
            fontName=primary_italic,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#16A34A"),
            backColor=colors.HexColor("#F0FDF4"),
            borderColor=colors.HexColor("#BBF7D0"),
            borderWidth=1,
            borderPadding=5,
            leftIndent=16,
            spaceBefore=4,
            spaceAfter=6,
        ),
        "th": ParagraphStyle(
            "NotesTH",
            fontName=primary_bold,
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#161616"),
            alignment=0,
        ),
        "td": ParagraphStyle(
            "NotesTD",
            fontName=primary_font,
            fontSize=8.5,
            leading=11.5,
            textColor=colors.HexColor("#161616"),
            alignment=0,
        ),
    }

    story = []

    # 1. Document Title with green wavy accent
    story.append(Paragraph(_escape_and_wrap_indic(clean_title, indic_font), styles["title"]))
    story.append(_WavyUnderline())

    # 2. Metadata tag pills: Subject, Date, Tags, Student
    pill_items = [subject.capitalize(), get_current_date_str()]
    if tags:
        pill_items.extend(str(t) for t in tags)
    if student_email:
        pill_items.append(student_email)
    story.append(_TagPills(pill_items))

    # 3. Optional Diagram Figure (Embedded image or organic hand-sketched diagram)
    fig_flowable = None
    resolved_img = _resolve_image_path(image_path) or _resolve_image_path(visual)
    if resolved_img:
        fig_flowable = _create_image_flowable(resolved_img, clean_title, styles)
    if fig_flowable is None and (visual or clean_title or subject):
        try:
            png_bytes = render_notebook_sketch(
                title=clean_title,
                domain=subject,
                visual_suggestion=visual,
                width=260,
                height=140,
            )
            rl_img = RLImage(io.BytesIO(png_bytes), width=220, height=118)
            caption_p = Paragraph(f"<i>Fig \u2014 {_escape_and_wrap_indic(clean_title, indic_font)}</i>",
                                  styles["caption"])
            fig_flowable = Table(
                [[rl_img], [caption_p]],
                colWidths=[224],
                style=[
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ],
            )
        except Exception:
            fig_flowable = None

    # 4. Markdown Content Flowables
    content_flowables = _convert_markdown_to_flowables(content, styles, avail_w=avail_w, indic_font=indic_font)

    # If a diagram figure is present and we have content paragraphs, place the diagram neatly
    if fig_flowable is not None:
        if content_flowables and isinstance(content_flowables[0], Paragraph):
            first_elem = content_flowables.pop(0)
            lead_table = Table(
                [[first_elem, fig_flowable]],
                colWidths=[avail_w - 232, 228],
                style=[
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ],
            )
            story.append(lead_table)
        else:
            story.append(fig_flowable)
            story.append(Spacer(1, 6))

    story.extend(content_flowables)

    # 5. Build Document with Underlay Background & Two-Pass Canvas
    def background_callback(c: canvas.Canvas, doc_ref: SimpleDocTemplate) -> None:
        _draw_notebook_background(
            c, doc_ref, margin_tip=margin_tip, draw_ruled_lines=draw_ruled_lines
        )

    bound_canvas_maker = _create_notes_canvas_maker(brand)
    doc.build(
        story,
        onFirstPage=background_callback,
        onLaterPages=background_callback,
        canvasmaker=bound_canvas_maker,
    )
    return target_path
