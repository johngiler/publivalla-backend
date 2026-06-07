"""
Base común para PDFs de pedidos (ReportLab).

Toda subclase debe definir ``DOCUMENT_TITLE`` (metadato / pestaña del visor).
Márgenes, autor y flujo ``build()`` quedan centralizados para evitar divergencias.
"""

from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate


class OrderPdfBuilder:
    """Generador PDF de documentos ligados a un pedido."""

    DOCUMENT_TITLE: str = ""
    LEFT_MARGIN = 2 * cm
    RIGHT_MARGIN = 2 * cm
    TOP_MARGIN = 2.6 * cm
    BOTTOM_MARGIN = 2 * cm
    PDF_AUTHOR = "Publivalla"
    PDF_CREATOR = "Publivalla"

    def __init__(self, order, **kwargs) -> None:
        self.order = order

    @property
    def document_title(self) -> str:
        title = (self.DOCUMENT_TITLE or "").strip()
        if not title:
            raise ValueError(
                f"{type(self).__name__} debe definir DOCUMENT_TITLE (metadato del PDF)."
            )
        return title

    @classmethod
    def prepend_branding_for(cls, order, story: list, **kwargs) -> None:
        cls(order, **kwargs).prepend_branding(story)

    @classmethod
    def render_story(cls, order, story: list, **kwargs) -> bytes:
        return cls(order, **kwargs).build_from_story(story)

    def prepend_branding(self, story: list) -> None:
        from apps.orders.utils.pdf_documents import _prepend_order_logo

        _prepend_order_logo(story, self.order)

    def create_document(self, buf: BytesIO) -> SimpleDocTemplate:
        return SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=self.LEFT_MARGIN,
            rightMargin=self.RIGHT_MARGIN,
            topMargin=self.TOP_MARGIN,
            bottomMargin=self.BOTTOM_MARGIN,
            title=self.document_title,
            author=self.PDF_AUTHOR,
            creator=self.PDF_CREATOR,
        )

    def build_story(self) -> list:
        """Opcional: contenido platypus; si no se sobrescribe, usar ``render_story``."""
        raise NotImplementedError(
            f"{type(self).__name__}: implementa build_story() o usa render_story()."
        )

    def build_from_story(self, story: list) -> bytes:
        """Renderiza un story ya armado (misma metadata y márgenes que ``build()``)."""
        buf = BytesIO()
        doc = self.create_document(buf)
        doc.build(story)
        pdf = buf.getvalue()
        buf.close()
        return pdf

    def build(self) -> bytes:
        return self.build_from_story(self.build_story())
