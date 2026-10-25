"""Two-pass ReportLab Canvas for dynamic page numbers, disclaimers, and running headers."""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.pdfgen import canvas

from .config import _INDIC_REGEX, InfographicBranding, get_default_branding, register_pdf_fonts


class InfographicCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and draw total page counts, disclaimers, and footers."""

    branding: InfographicBranding = get_default_branding()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count: int):
        self.saveState()
        primary_font, _, _, indic_font = register_pdf_fonts()
        self.setFillColor(colors.HexColor("#64748B"))

        # Top running header on multi-page documents (pages 2+)
        if self._pageNumber > 1 and self.branding.running_header:
            h_font = indic_font if (indic_font and _INDIC_REGEX.search(self.branding.running_header)) else primary_font
            self.setFont(h_font, 7.5)
            self.drawString(28, 792 - 16, self.branding.running_header)
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.5)
            self.line(28, 792 - 20, 612 - 28, 792 - 20)

        # Bottom-left: disclaimer
        if self.branding.disclaimer:
            d_font = indic_font if (indic_font and _INDIC_REGEX.search(self.branding.disclaimer)) else primary_font
            self.setFont(d_font, 7.5)
            self.drawString(28, 14, self.branding.disclaimer)

        # Bottom-right: page number
        self.setFont(primary_font, 7.5)
        self.drawRightString(612 - 28, 14, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def create_canvas_maker(branding: InfographicBranding):
    """Factory creating an InfographicCanvas subclass bound to specific branding."""
    class BoundInfographicCanvas(InfographicCanvas):
        pass
    BoundInfographicCanvas.branding = branding
    return BoundInfographicCanvas
