"""Semantic, labeled vector illustration engine for educational lesson cards.

Generates high-contrast, labeled educational diagrams using Pillow:
- Mode A: Process Pipelines (multi-stage cards, arrows, entity badges)
- Mode B: Motion & Function Graphs (labeled axes, motion profiles, shaded area, curves)
- Mode C: Labeled Trees & Taxonomies (hierarchical nodes with labels)
"""
from __future__ import annotations

import io
import math
import re
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .config import get_pillow_font


def _get_font(size: int = 12, bold: bool = False, for_text: str = "") -> ImageFont.ImageFont:
    """Load a clean font with universal fallback for Cloud Run and local environments."""
    return get_pillow_font(size=size, bold=bold, for_text=for_text)


def _draw_arrow(draw: ImageDraw.ImageDraw, x1: float, y1: float, x2: float, y2: float,
                color: tuple[int, int, int] = (148, 163, 184), size: float = 6.0) -> None:
    """Draw a directional line with a triangular arrow head."""
    draw.line([(x1, y1), (x2, y2)], fill=color, width=2)
    angle = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - size * math.cos(angle - math.pi / 6), y2 - size * math.sin(angle - math.pi / 6))
    p2 = (x2 - size * math.cos(angle + math.pi / 6), y2 - size * math.sin(angle + math.pi / 6))
    draw.polygon([(x2, y2), p1, p2], fill=color)


def _draw_badge(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float],
                text: str, fill: tuple[int, int, int], text_color: tuple[int, int, int],
                outline: Optional[tuple[int, int, int]] = None, font_size: int = 11,
                bold: bool = True, radius: int = 4) -> None:
    """Draw a rounded badge pill with centered or clipped text."""
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)
    font = _get_font(font_size, bold=bold, for_text=text)
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        tw = right - left
        th = bottom - top
    except Exception:
        tw = len(text) * (font_size * 0.55)
        th = font_size
    bx1, by1, bx2, by2 = box
    tx = bx1 + max(4.0, (bx2 - bx1 - tw) / 2.0)
    ty = by1 + max(2.0, (by2 - by1 - th) / 2.0 - 1.0)
    draw.text((tx, ty), text, fill=text_color, font=font)


def _parse_stages(visual_suggestion: str, title: str,
                  takeaways: Optional[list[str]] = None) -> list[str]:
    """Extract distinct entity/stage names from visual suggestions or step metadata."""
    text = visual_suggestion or ""
    # 1. Look for brackets e.g. components [Sun, Chlorophyll, ATP] or nodes [A -> B -> C]
    bracket_match = re.search(r"\[(.*?)\]", text)
    if bracket_match:
        raw_items = re.split(r"[,➔\->→]", bracket_match.group(1))
        cleaned = [i.strip() for i in raw_items if i.strip() and not i.strip().startswith("flow=")]
        if len(cleaned) >= 2:
            return cleaned[:4]

    # 2. Look for explicit arrow sequence e.g. A -> B -> C
    if "->" in text or "→" in text:
        parts = re.split(r"->|→", text)
        cleaned = [p.strip() for p in parts if p.strip()]
        if len(cleaned) >= 2:
            return cleaned[:4]

    # 3. Fallback: derive semantic 3-stage concept flow from title & takeaways
    t_words = [w for w in title.split() if w.lower() not in ("the", "of", "and", "a", "in", "for")]
    stage1 = " ".join(t_words[:2]) if t_words else "Initial State"
    stage2 = "Core Mechanism"
    stage3 = "Target Outcome"
    if takeaways and len(takeaways) > 0:
        first_tk = takeaways[0].split(".")[0].strip()
        words = first_tk.split()
        if len(words) > 3:
            stage3 = " ".join(words[:3])
        elif words:
            stage3 = " ".join(words)
    return [stage1[:18], stage2, stage3[:18]]


def _render_pipeline(draw: ImageDraw.ImageDraw, w: int, h: int, title: str,
                     items: list[str], domain_color: tuple[int, int, int],
                     step_number: int) -> None:
    """Render Mode A: Horizontal process flow with numbered stage cards and arrows."""
    banner_text = f"PROCESS FLOW • {title.upper()}"[:48]
    _draw_badge(draw, (12, 10, w - 12, 32), banner_text, fill=(241, 245, 249),
                text_color=(30, 41, 59), outline=(203, 213, 225), font_size=11, bold=True)

    n = max(2, min(len(items), 4))
    arrow_w = 22
    total_arrow_w = (n - 1) * arrow_w
    avail_w = (w - 28) - total_arrow_w
    card_w = avail_w / n
    card_h = h - 56
    top_y = 44

    for i in range(n):
        cx = 14 + i * (card_w + arrow_w)
        # Stage card
        draw.rounded_rectangle([(cx, top_y), (cx + card_w, top_y + card_h)], radius=6,
                               fill=(255, 255, 255), outline=(203, 213, 225), width=1)
        # Accent top bar
        draw.rounded_rectangle([(cx, top_y), (cx + card_w, top_y + 4)], radius=2,
                               fill=domain_color)

        # Stage number pill
        badge_num = f"STAGE {i + 1}"
        _draw_badge(draw, (cx + 8, top_y + 10, cx + card_w - 8, top_y + 26),
                    badge_num, fill=(238, 242, 255), text_color=(67, 56, 202),
                    outline=(199, 210, 254), font_size=9, bold=True)

        # Stage label text
        raw_label = items[i] if i < len(items) else f"Step {i + 1}"
        words = raw_label.split()
        line1 = " ".join(words[:2]) if words else ""
        line2 = " ".join(words[2:5]) if len(words) > 2 else ""

        font = _get_font(11, bold=True, for_text=line1)
        draw.text((cx + 10, top_y + 36), line1[:15], fill=(15, 23, 42), font=font)
        if line2:
            font_sub = _get_font(10, bold=False, for_text=line2)
            draw.text((cx + 10, top_y + 54), line2[:18], fill=(71, 85, 105), font=font_sub)

        # Connector arrow
        if i < n - 1:
            ax1 = cx + card_w + 3
            ax2 = ax1 + arrow_w - 6
            ay = top_y + card_h / 2
            _draw_arrow(draw, ax1, ay, ax2, ay, color=(148, 163, 184), size=5)


def _render_motion_graph(draw: ImageDraw.ImageDraw, w: int, h: int, title: str,
                         visual_suggestion: str, domain_color: tuple[int, int, int]) -> None:
    """Render Mode B: Labeled coordinate motion profile or mathematical graph."""
    text_lower = visual_suggestion.lower()
    is_kinematics = any(k in text_lower for k in ("velocity", "acceleration", "motion", "train", "speed", "v-t"))

    banner_title = "MOTION PROFILE • VELOCITY vs TIME" if is_kinematics else f"CARTESIAN GRAPH • {title.upper()[:32]}"
    _draw_badge(draw, (12, 10, w - 12, 32), banner_title, fill=(241, 245, 249),
                text_color=(30, 41, 59), outline=(203, 213, 225), font_size=11, bold=True)

    ox, oy = 55, h - 35
    max_x, max_y = w - 30, 48

    # Grid lines
    for gy in range(max_y + 20, oy, 32):
        draw.line([(ox, gy), (max_x, gy)], fill=(241, 245, 249), width=1)

    # Coordinate axes
    draw.line([(ox, max_y), (ox, oy)], fill=(100, 116, 139), width=2)
    draw.line([(ox, oy), (max_x, oy)], fill=(100, 116, 139), width=2)

    font_axis = _get_font(10, bold=True)
    draw.text((max_x - 65, oy + 8), "Time t (s)", fill=(71, 85, 105), font=font_axis)
    draw.text((10, max_y + 2), "v (m/s)" if is_kinematics else "f(x)", fill=(71, 85, 105), font=font_axis)

    if is_kinematics:
        p0 = (ox, oy)
        p1 = (ox + 90, oy - 95)
        p2 = (ox + 230, oy - 95)
        p3 = (ox + 330, oy)

        # Shaded displacement area
        area_poly = [p0, p1, p2, p3]
        draw.polygon(area_poly, fill=(236, 253, 245))
        draw.line([p0, p1, p2, p3], fill=(16, 185, 129), width=3)

        # Region chips
        _draw_badge(draw, (p0[0] + 15, p1[1] - 18, p0[0] + 100, p1[1] - 2),
                    "a > 0 (Accel)", fill=(254, 243, 199), text_color=(180, 83, 9), font_size=9)
        _draw_badge(draw, (p1[0] + 25, p1[1] - 18, p1[0] + 115, p1[1] - 2),
                    "v = const (Cruise)", fill=(224, 242, 254), text_color=(3, 105, 161), font_size=9)
        _draw_badge(draw, (p2[0] + 15, p1[1] - 18, p2[0] + 95, p1[1] - 2),
                    "a < 0 (Braking)", fill=(254, 226, 226), text_color=(185, 28, 28), font_size=9)

        font_area = _get_font(10, bold=True)
        draw.text((ox + 100, oy - 45), "Area = Total Displacement (\u0394x)", fill=(5, 150, 105), font=font_area)
    else:
        pts = []
        for x in range(ox, max_x - 20, 4):
            t = (x - ox) / (max_x - ox - 20) * 2 * math.pi
            y = (oy + max_y) / 2 - math.sin(t) * (oy - max_y - 20) / 2.2
            pts.append((x, int(y)))
        if len(pts) > 1:
            draw.line(pts, fill=(37, 99, 235), width=3)
        if len(pts) > 6:
            peak_x, peak_y = pts[len(pts) // 4]
            draw.ellipse([(peak_x - 4, peak_y - 4), (peak_x + 4, peak_y + 4)], fill=(219, 39, 119))
            _draw_badge(draw, (peak_x + 8, peak_y - 12, peak_x + 85, peak_y + 4),
                        "Peak / Vertex", fill=(253, 242, 248), text_color=(157, 23, 77), font_size=9)


def _render_labeled_tree(draw: ImageDraw.ImageDraw, w: int, h: int, title: str,
                         domain_color: tuple[int, int, int]) -> None:
    """Render Mode C: Labeled hierarchical binary tree with text nodes."""
    banner = f"HIERARCHY & NODES • {title.upper()[:36]}"
    _draw_badge(draw, (12, 10, w - 12, 32), banner, fill=(241, 245, 249),
                text_color=(30, 41, 59), outline=(203, 213, 225), font_size=11, bold=True)

    root_pos = (w // 2, 60)
    c1_pos = (w // 4, 125)
    c2_pos = (3 * w // 4, 125)
    sc1_pos = (w // 8, 185)
    sc2_pos = (3 * w // 8, 185)

    draw.line([root_pos, c1_pos], fill=(148, 163, 184), width=2)
    draw.line([root_pos, c2_pos], fill=(148, 163, 184), width=2)
    draw.line([c1_pos, sc1_pos], fill=(203, 213, 225), width=2)
    draw.line([c1_pos, sc2_pos], fill=(203, 213, 225), width=2)

    nodes = [
        (root_pos, "Root Node", (224, 242, 254), (3, 105, 161), 80),
        (c1_pos, "Left Child", (220, 252, 231), (21, 128, 61), 74),
        (c2_pos, "Right Child", (254, 243, 199), (180, 83, 9), 74),
        (sc1_pos, "Leaf L1", (241, 245, 249), (71, 85, 105), 62),
        (sc2_pos, "Leaf L2", (241, 245, 249), (71, 85, 105), 62),
    ]
    for (nx, ny), lbl, bg, text_c, nw in nodes:
        box = (nx - nw / 2, ny - 12, nx + nw / 2, ny + 12)
        _draw_badge(draw, box, lbl, fill=bg, text_color=text_c,
                    outline=(148, 163, 184), font_size=9, bold=True)

    font_d = _get_font(9, bold=False)
    draw.text((15, 55), "Depth 0", fill=(148, 163, 184), font=font_d)
    draw.text((15, 120), "Depth 1", fill=(148, 163, 184), font=font_d)
    draw.text((15, 180), "Depth 2", fill=(148, 163, 184), font=font_d)


def render_step_diagram(
    visual_suggestion: str = "",
    domain: str = "",
    title: str = "",
    step_number: int = 1,
    concept: str = "",
    takeaways: Optional[list[str]] = None,
    width: int = 480,
    height: int = 240,
) -> bytes:
    """Render a clean, semantic, labeled educational diagram illustration."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        [(2, 2), (width - 3, height - 3)],
        radius=6,
        fill=(248, 250, 252),
        outline=(226, 232, 240),
        width=1,
    )

    text_lower = (visual_suggestion or "").lower()
    dom_lower = (domain or "").lower()
    clean_title = title or f"Step {step_number}"

    domain_color = (37, 99, 235)
    if "physic" in dom_lower:
        domain_color = (217, 119, 6)
    elif "biolog" in dom_lower or "chem" in dom_lower:
        domain_color = (16, 185, 129)
    elif "math" in dom_lower:
        domain_color = (2, 132, 199)
    elif "computer" in dom_lower:
        domain_color = (99, 102, 241)

    if any(k in text_lower for k in ("tree", "hierarchy", "taxonomy", "binary")):
        _render_labeled_tree(draw, width, height, clean_title, domain_color)
    elif (any(k in text_lower for k in ("velocity", "acceleration", "kinematics", "motion", "plot_curve",
                                       "curve", "graph", "wave", "harmonic", "parabola"))
          or "math" in dom_lower):
        _render_motion_graph(draw, width, height, clean_title, visual_suggestion, domain_color)
    else:
        items = _parse_stages(visual_suggestion, clean_title, takeaways)
        _render_pipeline(draw, width, height, clean_title, items, domain_color, step_number)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
