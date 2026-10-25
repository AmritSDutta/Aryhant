"""Platypus PDF document builder for educational lesson infographics."""
from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Optional, Union

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .canvas import create_canvas_maker
from .config import (
    InfographicBranding,
    escape_and_wrap_indic,
    get_current_date_str,
    get_infographics_dir,
    register_pdf_fonts,
    resolve_branding,
)
from .diagrams import render_step_diagram
from .theme import _STEP_ACCENTS, _get_subject_palette


def generate_lesson_infographic(
    lesson_data: dict,
    output_path: Optional[str] = None,
    branding: Optional[Union[InfographicBranding, dict, str, Path]] = None,
) -> str:
    """Generate a high-density, professional editorial infographic study sheet as PDF.

    Driven by InfographicBranding, allowing easy white-labeling across products.
    Saves to temporary directory unless output_path is explicitly given.
    Returns the absolute path to the generated PDF.
    """
    brand = resolve_branding(branding)
    target_dir = get_infographics_dir()
    primary_font, primary_bold, primary_italic, indic_font = register_pdf_fonts()

    lesson_id = str(lesson_data.get("id") or lesson_data.get("lesson_id") or "live")[:10]
    title = str(lesson_data.get("title", "Educational Masterclass")).strip()
    subject = str(lesson_data.get("subject", "Science")).strip()
    grade = str(lesson_data.get("grade", "")).strip()
    overview = str(lesson_data.get("overview") or lesson_data.get("summary", "")).strip()
    steps = lesson_data.get("steps", [])

    clean_slug = re.sub(r"[^a-zA-Z0-9]+", "_", title.lower()).strip("_")[:32]
    slug = clean_slug or f"lesson_{lesson_id}"
    default_filename = f"{brand.filename_prefix}_{slug}_{lesson_id}.pdf"
    if output_path:
        target_path = os.path.abspath(output_path)
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    else:
        target_path = str(target_dir / default_filename)

    margin = 28
    avail_w = 612 - margin * 2
    doc = SimpleDocTemplate(
        target_path,
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=16,
        bottomMargin=margin,
        title=f"{brand.brand_title} \u2013 {title}",
        author=brand.product_name,
        subject=f"{subject} \u2014 Grade {grade}" if grade else subject,
        creator=brand.product_name,
        displayDocTitle=True,
    )

    accent_color, badge_bg, badge_txt = _get_subject_palette(subject)

    title_style = ParagraphStyle(
        "HeroTitle",
        fontName=primary_bold,
        fontSize=17,
        leading=21,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=2,
    )
    overview_style = ParagraphStyle(
        "HeroOverview",
        fontName=primary_font,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#475569"),
    )
    badge_style = ParagraphStyle(
        "SubjectBadge",
        fontName=primary_bold,
        fontSize=8,
        leading=10,
        textColor=badge_txt,
        alignment=1,
    )
    card_title_style = ParagraphStyle(
        "StepCardTitle",
        fontName=primary_bold,
        fontSize=10.5,
        leading=13,
        textColor=colors.HexColor("#0F172A"),
    )
    concept_style = ParagraphStyle(
        "StepConcept",
        fontName=primary_font,
        fontSize=7.5,
        leading=10.5,
        textColor=colors.HexColor("#334155"),
    )
    takeaway_style = ParagraphStyle(
        "StepTakeaway",
        fontName=primary_font,
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#065F46"),
    )
    checkpoint_style = ParagraphStyle(
        "StepCheckpoint",
        fontName=primary_italic,
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#92400E"),
    )
    footer_style = ParagraphStyle(
        "PosterFooter",
        fontName=primary_font,
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#64748B"),
        alignment=1,
    )

    story = []

    # 0. TOP BRANDING ROW
    top_l_style = ParagraphStyle(
        "TopBrandL",
        fontName=primary_bold,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#0F172A"),
    )
    top_r_style = ParagraphStyle(
        "TopBrandR",
        fontName=primary_font,
        fontSize=7.5,
        leading=11,
        textColor=colors.HexColor("#64748B"),
        alignment=2,
    )
    icon_path = brand.icon_path
    if icon_path and os.path.exists(icon_path):
        icon_cell = RLImage(icon_path, width=18, height=18)
        brand_p = Paragraph(f"<b>{escape_and_wrap_indic(brand.brand_title, indic_font)}</b>", top_l_style)
        right_p = Paragraph(escape_and_wrap_indic(brand.header_subtitle, indic_font), top_r_style)
        top_table = Table([[icon_cell, brand_p, right_p]], colWidths=[22, 160, avail_w - 182])
        top_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(top_table)
    else:
        top_table = Table([[
            Paragraph(f"<b>{escape_and_wrap_indic(brand.brand_title, indic_font)}</b>", top_l_style),
            Paragraph(escape_and_wrap_indic(brand.header_subtitle, indic_font), top_r_style),
        ]], colWidths=[avail_w // 2, avail_w // 2])
        top_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(top_table)

    story.append(HRFlowable(width="100%", thickness=0.75, color=colors.HexColor("#daa520"), spaceAfter=6))

    # 1. TOP HERO HEADER
    badge_label = f"<b>{escape_and_wrap_indic(subject.upper(), indic_font)}</b>" + (f" • GRADE {grade}" if grade else " • CURRICULUM")
    badge_table = Table([[Paragraph(badge_label, badge_style)]], colWidths=[155], rowHeights=[18])
    badge_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), badge_bg),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, accent_color),
        ("PADDING", (0, 0), (-1, -1), 1),
    ]))

    header_left = [
        badge_table,
        Spacer(1, 4),
        Paragraph(escape_and_wrap_indic(title, indic_font), title_style),
        Paragraph(escape_and_wrap_indic(overview if overview else f"Comprehensive study guide for {title}.", indic_font), overview_style),
    ]

    header_meta = (
        f"<b><font size=8 color='#334155'>{escape_and_wrap_indic(brand.hero_label, indic_font)}</font></b><br/>"
        f"<font size=7 color='#64748B'>Date: {get_current_date_str()}<br/>"
        f"Lesson ID: #{lesson_id}<br/>"
        f"Milestones: {len(steps)} Steps</font>"
    )
    header_right = [
        Paragraph(header_meta, ParagraphStyle("HMeta", fontName=primary_font, leading=11, alignment=2)),
    ]

    header_table = Table([[header_left, header_right]], colWidths=[avail_w - 140, 140])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#daa520")),
        ("LINELEFT", (0, 0), (0, -1), 4, accent_color),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8))

    # 2. HORIZONTAL MILESTONE PIPELINE
    if steps:
        pipe_cells = []
        col_w = []
        num_s = len(steps)
        arrow_w = 16 if num_s > 1 else 0
        total_arrow_w = arrow_w * (num_s - 1)
        step_box_w = (avail_w - total_arrow_w) / num_s

        for idx, s in enumerate(steps):
            s_num = s.get("step_number", idx + 1)
            s_title = s.get("title", f"Step {s_num}")
            short_title = s_title[:24] + ("..." if len(s_title) > 24 else "")
            color_stroke = _STEP_ACCENTS[idx % len(_STEP_ACCENTS)]

            cell_p = Paragraph(
                f"<b>{escape_and_wrap_indic(brand.step_prefix, indic_font)} {s_num}</b><br/><font size=7 color='#334155'>{escape_and_wrap_indic(short_title, indic_font)}</font>",
                ParagraphStyle("PipeCell", fontName=primary_font, fontSize=7.5, leading=9.5, alignment=1),
            )
            step_box = Table([[cell_p]], colWidths=[step_box_w], rowHeights=[30])
            step_box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFFFF")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#daa520")),
                ("LINELEFT", (0, 0), (0, -1), 3, color_stroke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING", (0, 0), (-1, -1), 2),
            ]))

            pipe_cells.append(step_box)
            col_w.append(step_box_w)

            if idx < num_s - 1:
                arrow = Paragraph("<b>➔</b>", ParagraphStyle("Arr", fontName=primary_bold, fontSize=11, leading=11, textColor=colors.HexColor("#94A3B8"), alignment=1))
                pipe_cells.append(arrow)
                col_w.append(arrow_w)

        pipeline_table = Table([pipe_cells], colWidths=col_w)
        pipeline_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(pipeline_table)
        story.append(Spacer(1, 8))

    # 3. STRUCTURED KNOWLEDGE CARDS
    for idx, s in enumerate(steps):
        s_num = s.get("step_number", idx + 1)
        s_title = s.get("title", f"Milestone {s_num}")
        concept = s.get("concept") or s.get("what_to_teach", "")
        visual_sug = s.get("visual_suggestion") or str(s.get("what_to_show", ""))
        takeaways = s.get("key_takeaways", [])
        checkpoint = s.get("checkpoint", "")
        stroke = _STEP_ACCENTS[idx % len(_STEP_ACCENTS)]

        card_header = Table([
            [
                Paragraph(f"<b>{escape_and_wrap_indic(brand.step_prefix, indic_font)} {s_num}: {escape_and_wrap_indic(s_title.upper(), indic_font)}</b>", card_title_style),
                Paragraph(f"<font size=7.5 color='#64748B'>{escape_and_wrap_indic(brand.milestone_prefix, indic_font)}{s_num}</font>", ParagraphStyle("MNum", fontName=primary_font, alignment=2)),
            ]
        ], colWidths=[avail_w - 90, 70])
        card_header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))

        diagram_bytes = render_step_diagram(
            visual_suggestion=visual_sug,
            domain=subject,
            title=s_title,
            step_number=s_num,
            concept=concept,
            takeaways=takeaways,
            width=480,
            height=240,
        )
        rl_img = RLImage(io.BytesIO(diagram_bytes), width=160, height=80)

        concept_clean = concept.replace("\n", " ").strip()
        tks_formatted = "<br/>".join([f"<b>✔</b> {escape_and_wrap_indic(t, indic_font)}" for t in takeaways[:2]]) if takeaways else f"<b>✔</b> {escape_and_wrap_indic('Master core concept principles.', indic_font)}"
        left_box = [
            Paragraph(escape_and_wrap_indic(concept_clean, indic_font), concept_style),
            Spacer(1, 3),
            Table([[Paragraph(f"<b>{escape_and_wrap_indic(brand.takeaways_header, indic_font)}</b><br/>{tks_formatted}", takeaway_style)]],
                  colWidths=[avail_w - 180],
                  style=[
                      ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0FDF4")),
                      ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#BBF7D0")),
                      ("PADDING", (0, 0), (-1, -1), 4),
                  ]),
        ]

        cp_text = f"<b>{escape_and_wrap_indic(brand.checkpoint_prefix, indic_font)}</b><br/>{escape_and_wrap_indic(checkpoint, indic_font)}" if checkpoint else f"<b>{escape_and_wrap_indic(brand.checkpoint_prefix, indic_font)}</b> {escape_and_wrap_indic('Review principles on the left.', indic_font)}"
        right_box = [
            rl_img,
            Spacer(1, 2),
            Table([[Paragraph(cp_text, checkpoint_style)]],
                  colWidths=[160],
                  style=[
                      ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFBEB")),
                      ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#FDE68A")),
                      ("PADDING", (0, 0), (-1, -1), 3),
                  ]),
        ]

        card_body = Table([[left_box, right_box]], colWidths=[avail_w - 175, 165])
        card_body.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))

        card_container = Table([[card_header], [Spacer(1, 2)], [card_body]], colWidths=[avail_w])
        card_container.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFFFF")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#daa520")),
            ("LINELEFT", (0, 0), (0, -1), 3.5, stroke),
            ("PADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))

        story.append(KeepTogether(card_container))
        story.append(Spacer(1, 5))

    # 4. POSTER FOOTER
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E1"), spaceAfter=3))
    footer_text = escape_and_wrap_indic(brand.format_footer(save_path=os.path.basename(target_path)), indic_font)
    story.append(Paragraph(footer_text, footer_style))

    bound_canvas_maker = create_canvas_maker(brand)
    doc.build(story, canvasmaker=bound_canvas_maker)
    return target_path
