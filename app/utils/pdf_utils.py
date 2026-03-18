from __future__ import annotations

from io import BytesIO


def render_html_to_pdf(html: str) -> bytes:
    """Convert an HTML string to PDF bytes using xhtml2pdf."""
    from xhtml2pdf import pisa

    buf = BytesIO()
    result = pisa.CreatePDF(html.encode("utf-8"), dest=buf, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"PDF generation failed (error code {result.err})")
    return buf.getvalue()
