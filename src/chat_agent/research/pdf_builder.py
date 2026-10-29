from __future__ import annotations

import html
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from chat_agent.infographics.config import find_icon
from chat_agent.infographics.notes_builder import get_reports_dir, register_pdf_fonts
from chat_agent.research.models import ResearchMode, ResearchSource, TokenEconomics

logger = logging.getLogger(__name__)

IST_ZONE = timezone(timedelta(hours=5, minutes=30), name="IST")


def format_human_ist_datetime(dt: datetime | None = None) -> str:
    """Format datetime as human-friendly IST (e.g., '28 Oct 2026, 12:49 AM IST')."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    ist_dt = dt.astimezone(IST_ZONE)
    return ist_dt.strftime("%d %b %Y, %I:%M %p IST")



_RESEARCH_FONTS_REGISTERED: bool = False
_RESEARCH_FONT: str = "Lora"
_RESEARCH_BOLD: str = "Lora-Bold"
_RESEARCH_ITALIC: str = "Lora-Italic"
_RESEARCH_BOLD_ITALIC: str = "Lora-BoldItalic"


def register_research_fonts() -> tuple[str, str, str, str]:
    """Register Lora serif font family for publication-grade research and deliberation PDFs."""
    global _RESEARCH_FONTS_REGISTERED, _RESEARCH_FONT, _RESEARCH_BOLD, _RESEARCH_ITALIC, _RESEARCH_BOLD_ITALIC
    if _RESEARCH_FONTS_REGISTERED:
        return _RESEARCH_FONT, _RESEARCH_BOLD, _RESEARCH_ITALIC, _RESEARCH_BOLD_ITALIC

    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        registered: set[str] = set(pdfmetrics.getRegisteredFontNames())
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(pkg_dir, "..", "..", ".."))
        fonts_dir = os.path.join(project_root, "assets", "fonts")

        lora_reg = os.path.join(fonts_dir, "Lora-Regular.ttf")
        lora_bold = os.path.join(fonts_dir, "Lora-Bold.ttf")
        lora_italic = os.path.join(fonts_dir, "Lora-Italic.ttf")
        lora_bold_italic = os.path.join(fonts_dir, "Lora-BoldItalic.ttf")

        if os.path.isfile(lora_reg):
            if "Lora" not in registered:
                pdfmetrics.registerFont(TTFont("Lora", lora_reg))
                b_font = "Lora"
                if os.path.isfile(lora_bold):
                    pdfmetrics.registerFont(TTFont("Lora-Bold", lora_bold))
                    b_font = "Lora-Bold"
                i_font = "Lora"
                if os.path.isfile(lora_italic):
                    pdfmetrics.registerFont(TTFont("Lora-Italic", lora_italic))
                    i_font = "Lora-Italic"
                bi_font = b_font
                if os.path.isfile(lora_bold_italic):
                    pdfmetrics.registerFont(TTFont("Lora-BoldItalic", lora_bold_italic))
                    bi_font = "Lora-BoldItalic"
                pdfmetrics.registerFontFamily(
                    "Lora",
                    normal="Lora",
                    bold=b_font,
                    italic=i_font,
                    boldItalic=bi_font,
                )
            _RESEARCH_FONT = "Lora"
            _RESEARCH_BOLD = "Lora-Bold" if "Lora-Bold" in pdfmetrics.getRegisteredFontNames() else "Lora"
            _RESEARCH_ITALIC = "Lora-Italic" if "Lora-Italic" in pdfmetrics.getRegisteredFontNames() else "Lora"
            _RESEARCH_BOLD_ITALIC = "Lora-BoldItalic" if "Lora-BoldItalic" in pdfmetrics.getRegisteredFontNames() else _RESEARCH_BOLD
            _RESEARCH_FONTS_REGISTERED = True
            return _RESEARCH_FONT, _RESEARCH_BOLD, _RESEARCH_ITALIC, _RESEARCH_BOLD_ITALIC
    except Exception as exc:
        logger.debug("Failed to register Lora fonts (%s); falling back to default.", exc)

    primary, p_bold, p_italic, _ = register_pdf_fonts()
    _RESEARCH_FONT = primary
    _RESEARCH_BOLD = p_bold
    _RESEARCH_ITALIC = p_italic
    _RESEARCH_BOLD_ITALIC = p_bold
    _RESEARCH_FONTS_REGISTERED = True
    return _RESEARCH_FONT, _RESEARCH_BOLD, _RESEARCH_ITALIC, _RESEARCH_BOLD_ITALIC

class PublicationCanvas(canvas.Canvas):
    """Two-pass canvas providing running headers, topic metadata, and dynamic page counts."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []
        self.doc_title: str = "Aryhant Intelligence Publication"
        self.icon_path: str | None = None

    def showPage(self) -> None:
        state = dict(self.__dict__)
        state.pop("_saved_page_states", None)
        self._saved_page_states.append(state)
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_decorations(num_pages)
            super().showPage()
        super().save()

    def _draw_decorations(self, page_count: int) -> None:
        self.saveState()
        primary_font, _, _, _ = register_research_fonts()
        self.setFillColor(colors.HexColor("#475569"))

        # Top running header on multi-page documents (page 2+)
        if self._pageNumber > 1:
            self.setFont(primary_font, 8)
            header_text = self.doc_title[:80]
            start_x = 36
            if self.icon_path and os.path.exists(self.icon_path):
                try:
                    self.drawImage(self.icon_path, 36, 792 - 26, width=12, height=12, preserveAspectRatio=True, mask='auto')
                    start_x = 52
                except Exception:
                    pass
            self.drawString(start_x, 792 - 24, header_text)

            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(36, 792 - 28, 612 - 36, 792 - 28)

        # Bottom footer
        self.setFont(primary_font, 8)
        self.drawString(36, 20, "Aryhant Autonomous Intelligence | Verified Publication")
        self.drawRightString(612 - 36, 20, f"Page {self._pageNumber} of {page_count}")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(36, 30, 612 - 36, 30)
        self.restoreState()


def _sanitize_xml_text(elem: ET.Element) -> str:
    """Recursively extract and format XML element text into ReportLab Paragraph markup."""
    parts: list[str] = []
    if elem.text:
        parts.append(html.escape(elem.text))
    for child in elem:
        tag = child.tag.lower()
        child_text = _sanitize_xml_text(child)
        if tag in ("strong", "b"):
            parts.append(f"<b>{child_text}</b>")
        elif tag in ("em", "i"):
            parts.append(f"<i>{child_text}</i>")
        elif tag == "code":
            parts.append(f'<font name="Courier" color="#1E293B"><b>{child_text}</b></font>')
        elif tag == "a":
            href = child.attrib.get("href", "#")
            parts.append(f'<font color="#2563EB"><u><a href="{html.escape(href)}">{child_text}</a></u></font>')
        else:
            parts.append(child_text)
        if child.tail:
            parts.append(html.escape(child.tail))
    return "".join(parts)


def clean_llm_markdown_for_pdf(raw_text: str) -> str:
    """Pre-clean LLM-generated markdown before converting to ReportLab PDF."""
    if not raw_text:
        return ""
    text = raw_text.strip()

    # 1. Strip outer code fences if the model wrapped the entire output in ```markdown ... ```
    fence_pattern = r"^```(?:markdown|md)?\s*\n(.*?)\n```$"
    fence_match = re.match(fence_pattern, text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    # 2. Strip unsupported wrapping HTML containers emitted by LLMs that cause ET.ParseError
    text = re.sub(r"</?(?:div|section|article|main|style|script|span)[^>]*>", "", text, flags=re.IGNORECASE)

    # 3. Clean and normalize math formulas if present
    try:
        from chat_agent.utils.math_formatter import clean_math_text

        text = clean_math_text(text)
    except Exception as exc:
        logger.error("Math cleaning failed in clean_llm_markdown_for_pdf: %s", exc, exc_info=True)

    return text


def build_research_pdf(
    topic: str,
    mode: ResearchMode,
    markdown_content: str,
    word_count: int,
    sources: list[ResearchSource] | None = None,
    image_paths: list[str] | None = None,
    output_path: str | None = None,
    token_economics: TokenEconomics | None = None,
) -> str:
    """Compile Markdown research or deliberation report into a multi-page ReportLab PDF publication."""
    clean_topic = topic.strip()
    markdown_content = clean_llm_markdown_for_pdf(markdown_content)
    slug = re.sub(r"[^\w\-_]+", "_", clean_topic.lower())[:40].strip("_") or "report"
    timestamp = int(datetime.now(timezone.utc).timestamp())

    target_dir = get_reports_dir()
    default_filename = f"{mode.value}_{slug}_{timestamp}.pdf"
    final_pdf_path = os.path.abspath(output_path) if output_path else str(target_dir / default_filename)
    Path(final_pdf_path).parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        final_pdf_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=40,
        bottomMargin=40,
        title=f"Aryhant Publication - {clean_topic}",
        author="Aryhant Intelligence",
    )

    primary_font, primary_bold, primary_italic, _ = register_pdf_fonts()

    is_tech = mode == ResearchMode.TECHNICAL
    primary_accent = colors.HexColor("#0F172A") if is_tech else colors.HexColor("#0369A1")
    badge_bg = colors.HexColor("#EEF2F6") if is_tech else colors.HexColor("#E0F2FE")

    styles: dict[str, ParagraphStyle] = {
        "title": ParagraphStyle(
            "DocTitle",
            fontName=primary_bold,
            fontSize=22,
            leading=26,
            textColor=primary_accent,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "DocSubTitle",
            fontName=primary_italic,
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#475569"),
            spaceAfter=12,
        ),
        "h1": ParagraphStyle(
            "Heading1",
            fontName=primary_bold,
            fontSize=15,
            leading=19,
            textColor=primary_accent,
            spaceBefore=14,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "Heading2",
            fontName=primary_bold,
            fontSize=12.5,
            leading=16,
            textColor=colors.HexColor("#1E293B"),
            spaceBefore=10,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "Heading3",
            fontName=primary_bold,
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#334155"),
            spaceBefore=8,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "BodyText",
            fontName=primary_font,
            fontSize=9.5,
            leading=13.5,
            textColor=colors.HexColor("#1E293B"),
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "BulletText",
            fontName=primary_font,
            fontSize=9.0,
            leading=13.0,
            textColor=colors.HexColor("#1E293B"),
            leftIndent=12,
            spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "CodeBlock",
            fontName="Courier",
            fontSize=8.0,
            leading=10.5,
            textColor=colors.HexColor("#0F172A"),
            backColor=colors.HexColor("#F8FAFC"),
            borderColor=colors.HexColor("#CBD5E1"),
            borderWidth=0.5,
            borderPadding=4,
            spaceBefore=4,
            spaceAfter=6,
        ),
        "blockquote": ParagraphStyle(
            "Blockquote",
            fontName=primary_italic,
            fontSize=9.0,
            leading=13.0,
            textColor=colors.HexColor("#334155"),
            backColor=colors.HexColor("#F1F5F9"),
            leftIndent=14,
            borderPadding=4,
            spaceBefore=4,
            spaceAfter=6,
        ),
        "th": ParagraphStyle(
            "TableHeader",
            fontName=primary_bold,
            fontSize=8.5,
            leading=11.0,
            textColor=colors.white,
        ),
        "td": ParagraphStyle(
            "TableCell",
            fontName=primary_font,
            fontSize=8.0,
            leading=10.5,
            textColor=colors.HexColor("#1E293B"),
        ),
    }

    flowables: list[Any] = []

    # Title Banner Block with leading brand icon
    icon_path = find_icon(["icon.ico", "icon.png", "vedantu.jpg"])
    banner_text = f"<b>{html.escape(clean_topic)}</b>"
    mode_title = "TECHNICAL WHITEPAPER & ARCHITECTURAL DEEP-DIVE" if is_tech else "EXECUTIVE DECISION & COMPARATIVE BUYING GUIDE"
    now_str = format_human_ist_datetime()
    meta_subtitle = f"{mode_title} &bull; {word_count} Words &bull; Published {now_str}"

    if icon_path and os.path.exists(icon_path):
        try:
            icon_flowable = RLImage(icon_path, width=42, height=42)
            title_paras = [
                Paragraph(banner_text, styles["title"]),
                Paragraph(meta_subtitle, styles["subtitle"]),
            ]
            header_table = Table([[icon_flowable, title_paras]], colWidths=[52, 488])
            header_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            flowables.append(header_table)
        except Exception as icon_err:
            logger.warning("Failed to render header icon: %s", icon_err)
            flowables.append(Paragraph(banner_text, styles["title"]))
            flowables.append(Paragraph(meta_subtitle, styles["subtitle"]))
    else:
        flowables.append(Paragraph(banner_text, styles["title"]))
        flowables.append(Paragraph(meta_subtitle, styles["subtitle"]))

    flowables.append(HRFlowable(width="100%", thickness=1.5, color=primary_accent, spaceAfter=10))

    # Optional embedded images with proportional scaling
    if image_paths:
        for idx, img_p in enumerate(image_paths, 1):
            if os.path.exists(img_p):
                try:
                    img_flowable = RLImage(img_p)
                    max_w, max_h = 440.0, 260.0
                    nat_w, nat_h = float(img_flowable.imageWidth), float(img_flowable.imageHeight)
                    if nat_w > 0 and nat_h > 0:
                        scale = min(max_w / nat_w, max_h / nat_h, 1.0)
                        img_flowable.drawWidth = nat_w * scale
                        img_flowable.drawHeight = nat_h * scale
                    else:
                        img_flowable.drawWidth = 420
                        img_flowable.drawHeight = 210
                    flowables.append(img_flowable)
                    cap_text = f"<i>Figure {idx}: Visual Evidence & Architecture Overview</i>"
                    flowables.append(Paragraph(cap_text, styles["subtitle"]))
                    flowables.append(Spacer(1, 6))
                except Exception as img_err:
                    logger.warning("Failed to embed image %s in PDF: %s", img_p, img_err)

    # Parse Markdown content into Flowables
    try:
        import markdown

        html_body = markdown.markdown(
            markdown_content,
            extensions=["tables", "fenced_code", "sane_lists"],
            output_format="xhtml",
        )
        wrapped_xml = f"<root>{html_body}</root>"
        root = ET.fromstring(wrapped_xml)

        for elem in root:
            tag = elem.tag.lower()
            if tag == "h1":
                flowables.append(Paragraph(_sanitize_xml_text(elem), styles["h1"]))
            elif tag == "h2":
                flowables.append(Paragraph(_sanitize_xml_text(elem), styles["h2"]))
            elif tag == "h3":
                flowables.append(Paragraph(_sanitize_xml_text(elem), styles["h3"]))
            elif tag == "p":
                flowables.append(Paragraph(_sanitize_xml_text(elem), styles["body"]))
            elif tag == "pre":
                code_text = html.escape("".join(elem.itertext()))
                flowables.append(Paragraph(code_text.replace("\n", "<br/>"), styles["code"]))
            elif tag == "blockquote":
                flowables.append(Paragraph(_sanitize_xml_text(elem), styles["blockquote"]))
            elif tag == "ul":
                for li in elem.findall("li"):
                    flowables.append(Paragraph(f"&bull; {_sanitize_xml_text(li)}", styles["bullet"]))
            elif tag == "ol":
                start_num = int(elem.attrib.get("start", 1))
                for idx, li in enumerate(elem.findall("li"), start=start_num):
                    flowables.append(Paragraph(f"<b>{idx}.</b> {_sanitize_xml_text(li)}", styles["bullet"]))
            elif tag == "table":
                rows: list[list[Any]] = []
                for tr in elem.iter("tr"):
                    row_cells: list[Any] = []
                    for th in tr.findall("th"):
                        row_cells.append(Paragraph(_sanitize_xml_text(th), styles["th"]))
                    for td in tr.findall("td"):
                        row_cells.append(Paragraph(_sanitize_xml_text(td), styles["td"]))
                    if row_cells:
                        rows.append(row_cells)
                if rows:
                    col_count = max(len(r) for r in rows)
                    col_width = (612 - 72) / max(col_count, 1)
                    tbl = Table(rows, colWidths=[col_width] * col_count)
                    tbl.setStyle(TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), primary_accent),
                        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ]))
                    flowables.append(tbl)
                    flowables.append(Spacer(1, 6))
    except Exception as parse_err:
        logger.error("Markdown XML parsing failed for ReportLab flowables: %s. Using fallback paragraph parser.", parse_err, exc_info=True)
        for line in markdown_content.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("# "):
                flowables.append(Paragraph(html.escape(s[2:]), styles["h1"]))
            elif s.startswith("## "):
                flowables.append(Paragraph(html.escape(s[3:]), styles["h2"]))
            elif s.startswith("### "):
                flowables.append(Paragraph(html.escape(s[4:]), styles["h3"]))
            elif s.startswith(("- ", "* ")):
                flowables.append(Paragraph(f"&bull; {html.escape(s[2:])}", styles["bullet"]))
            elif re.match(r"^\d+\.\s+", s):
                m = re.match(r"^(\d+\.)\s+(.*)$", s)
                if m:
                    flowables.append(Paragraph(f"<b>{m.group(1)}</b> {html.escape(m.group(2))}", styles["bullet"]))
            else:
                flowables.append(Paragraph(html.escape(s), styles["body"]))

    # Sources & Citations Section at the end
    if sources:
        flowables.append(Spacer(1, 10))
        flowables.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"), spaceAfter=8))
        flowables.append(Paragraph("<b>Authoritative References & Intelligence Sources</b>", styles["h3"]))
        for idx, src in enumerate(sources, 1):
            s_title = html.escape(src.title or "Reference")
            s_url = html.escape(src.url)
            src_line = f"[{idx}] <b>{s_title}</b>: <font color='#2563EB'><u><a href='{s_url}'>{s_url}</a></u></font>"
            flowables.append(Paragraph(src_line, styles["bullet"]))

    # Models Used & Token Economics Section (Heuristic Estimate)
    if token_economics and token_economics.models_used:
        flowables.append(Spacer(1, 10))
        flowables.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"), spaceAfter=8))
        flowables.append(Paragraph("<b>Models Used & Token Economics (Estimated)</b>", styles["h3"]))

        econ_data: list[list[Any]] = [
            [
                Paragraph("<b>Stage / Role</b>", styles["th"]),
                Paragraph("<b>Model & Provider</b>", styles["th"]),
                Paragraph("<b>Tokens (Est. In / Out)</b>", styles["th"]),
                Paragraph("<b>Est. Cost (USD)*</b>", styles["th"]),
            ]
        ]
        for mu in token_economics.models_used:
            econ_data.append([
                Paragraph(html.escape(mu.role), styles["td"]),
                Paragraph(f"{html.escape(mu.model_name)}<br/><i>{html.escape(mu.provider)}</i>", styles["td"]),
                Paragraph(f"~{mu.input_tokens:,} in / ~{mu.output_tokens:,} out<br/><b>Total: ~{mu.total_tokens:,}</b>", styles["td"]),
                Paragraph(f"~${mu.estimated_cost_usd:.4f}", styles["td"]),
            ])

        econ_table = Table(econ_data, colWidths=[140, 160, 140, 100])
        econ_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), primary_accent),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ]))
        flowables.append(econ_table)

        summary_econ = (
            f"<b>Estimated Token Consumption:</b> ~{token_economics.total_tokens:,} tokens "
            f"(~{token_economics.total_input_tokens:,} prompt, ~{token_economics.total_output_tokens:,} generated) &bull; "
            f"<b>Estimated Compute Cost:</b> ~${token_economics.total_estimated_cost_usd:.4f} USD<br/>"
            f"<font size='7' color='#64748B'>*Note: Token metrics and compute costs are projected heuristic estimates based on provider pricing tiers.</font>"
        )
        flowables.append(Spacer(1, 4))
        flowables.append(Paragraph(summary_econ, styles["subtitle"]))

    def _make_canvas(*args: Any, **kwargs: Any) -> PublicationCanvas:
        c = PublicationCanvas(*args, **kwargs)
        c.doc_title = clean_topic
        c.icon_path = icon_path
        return c

    doc.build(flowables, canvasmaker=_make_canvas)
    return final_pdf_path
