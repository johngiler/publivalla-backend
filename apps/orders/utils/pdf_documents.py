"""Generación de PDFs (hoja de negociación, carta municipio, factura) con ReportLab."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.db.models import Prefetch
from django.utils import timezone

from apps.ad_spaces.models import AdSpaceFormat
from apps.ad_spaces.utils.display import (
    ad_space_all_location_texts,
    ad_space_element_summary,
    ad_space_formats_ordered,
    ad_space_location_text,
    format_double_sided_observation,
    format_medidas_label,
    format_type_name,
)

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Flowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.utils import ImageReader


IVA_RATE = Decimal("0.16")

# Bloque firma arrendador / inquilino (hoja de negociación): altura de maquetación fija;
# la imagen se dibuja más grande y puede solapar nombre y línea sin separarlas.
_PARTY_SIG_COL_W = 7.8 * cm
_SIG_ZONE_LAYOUT_H = 0.35 * cm
_SIG_DRAW_MAX_W = 14.8 * cm
_SIG_DRAW_MAX_H = 5.6 * cm
_STAMP_DRAW_MAX_W = 7.0 * cm
_STAMP_DRAW_MAX_H = 7.0 * cm
_PARTY_SIG_NAME_ROW_H = 16
_PARTY_SIG_LINE_ROW_H = 12

# Márgenes 2cm + 2cm en SimpleDocTemplate de estos PDFs
_INNER_W = A4[0] - 4 * cm


def _inner_table_width() -> float:
    """Ancho interior disponible para tablas (A4 menos márgenes laterales de 2cm)."""
    return _INNER_W


def _table_paragraph_styles():
    """Estilos para celdas con ajuste de línea (evita solapamiento entre columnas)."""
    base = getSampleStyleSheet()
    cell = ParagraphStyle(
        "PdfTableCell",
        parent=base["Normal"],
        fontSize=8,
        leading=10,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#1f2937"),
        wordWrap="LTR",
        splitLongWords=1,
    )
    head = ParagraphStyle(
        "PdfTableHead",
        parent=cell,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
        textColor=colors.HexColor("#111827"),
    )
    cell_tight = ParagraphStyle(
        "PdfTableCellTight",
        parent=cell,
        fontSize=7,
        leading=9,
    )
    return cell, head, cell_tight


def _p_cell(text: str, style: ParagraphStyle, *, bold: bool = False) -> Paragraph:
    t = _escape(text or "")
    if bold:
        t = f"<b>{t}</b>"
    return Paragraph(t, style)


def _make_order_logo_flowable(order, *, max_width: float = 7.5 * cm):
    """
    Logotipo del workspace en el flujo del PDF (encima del texto, sin solapar).
    Solo PNG dedicado (``logo_png_artifacts`` en Mi negocio).
    """
    try:
        client = order.client
    except Exception:
        return None
    ws = getattr(client, "workspace", None)
    if ws is None:
        return None

    png = getattr(ws, "logo_png_artifacts", None)
    if not png or not getattr(png, "name", None):
        return None
    if Path(str(png.name)).suffix.lower() != ".png":
        return None
    try:
        png.open("rb")
        try:
            data = png.read()
        finally:
            png.close()
        if not data:
            return None
        reader = ImageReader(BytesIO(data))
        iw, ih = reader.getSize()
        target_w = max_width
        scale = target_w / max(float(iw), 1.0)
        w_pt = target_w
        h_pt = float(ih) * scale
        flow = Image(BytesIO(data), width=w_pt, height=h_pt)
        flow.hAlign = "CENTER"
        return flow
    except Exception:
        return None


def _prepend_order_logo(story: list, order) -> None:
    """Inserta logo + espacio al inicio del story (si hay PNG de marca)."""
    logo = _make_order_logo_flowable(order)
    if logo is not None:
        story.insert(0, Spacer(1, 0.35 * cm))
        story.insert(0, logo)


def _styles():
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "T",
        parent=base["Heading1"],
        fontSize=13,
        alignment=TA_CENTER,
        spaceAfter=16,
        textColor=colors.HexColor("#111827"),
        leading=16,
    )
    body = ParagraphStyle(
        "B",
        parent=base["Normal"],
        fontSize=10,
        leading=14,
        alignment=TA_JUSTIFY,
        textColor=colors.HexColor("#1f2937"),
        wordWrap="LTR",
        splitLongWords=1,
    )
    label = ParagraphStyle(
        "L",
        parent=base["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#374151"),
        fontName="Helvetica-Bold",
        wordWrap="LTR",
        splitLongWords=1,
    )
    small = ParagraphStyle(
        "S",
        parent=base["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#6b7280"),
        wordWrap="LTR",
        splitLongWords=1,
    )
    return title, body, label, small


def _escape(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _read_workspace_png_bytes(ws, field_name: str) -> bytes | None:
    """Lee bytes de un FileField PNG del workspace (Mi negocio)."""
    if ws is None:
        return None
    f = getattr(ws, field_name, None)
    if not f or not getattr(f, "name", None):
        return None
    if Path(str(f.name)).suffix.lower() != ".png":
        return None
    try:
        f.open("rb")
        try:
            data = f.read()
        finally:
            f.close()
        return data or None
    except Exception:
        return None


def _order_workspace(order):
    client = order.client
    ws = getattr(client, "workspace", None)
    if ws is None and getattr(client, "workspace_id", None):
        from apps.workspaces.models import Workspace

        ws = Workspace.objects.filter(pk=client.workspace_id).first()
    return ws


def _workspace_lessor_identity(order) -> tuple[str, str]:
    """
    Arrendador en documentos del pedido: el owner (workspace) del cliente.
    Razón social → nombre comercial → «Arrendador»; RIF del workspace si existe.
    """
    ws = _order_workspace(order)
    if ws is None:
        return "Arrendador", "—"
    name = (ws.legal_name or "").strip() or (ws.name or "").strip() or "Arrendador"
    rif = (getattr(ws, "rif", None) or "").strip() or "—"
    return name, rif


def _workspace_legal_stamp_footer(ws) -> tuple[str, str]:
    """Razón social y RIF del owner para el pie bajo la línea cuando no hay sello PNG."""
    if ws is None:
        return "", ""
    legal = (ws.legal_name or "").strip()
    rif = (getattr(ws, "rif", None) or "").strip()
    return legal, rif


def _lessor_stamp_footer_rows(
    legal_name: str,
    rif: str,
    body_st,
    *,
    centered: bool = False,
) -> list:
    """Bloque de texto (razón social + RIF) en la zona del sello."""
    if not legal_name and not rif:
        return []
    footer_st = ParagraphStyle(
        "LessorStampFooter",
        parent=body_st,
        fontSize=8,
        leading=10,
        alignment=TA_CENTER if centered else TA_LEFT,
    )
    lines: list[str] = []
    if legal_name:
        lines.append(_escape(legal_name))
    if rif:
        lines.append(f"RIF {_escape(rif)}")
    return [
        Spacer(1, 0.1 * cm),
        Paragraph("<br/>".join(lines), footer_st),
    ]


def _lessor_pdf_assets(order) -> tuple[bytes | None, bytes | None]:
    """
    Firma y sello del arrendador (workspace).
    Sin firma no se insertan imágenes (el sello solo se usa si hay firma).
    """
    ws = _order_workspace(order)
    signature = _read_workspace_png_bytes(ws, "signature_png")
    if not signature:
        return None, None
    stamp = _read_workspace_png_bytes(ws, "stamp_png")
    return signature, stamp


class SignatureOverlayFlowable(Flowable):
    """
    Reserva una franja de altura fija entre nombre y línea.
    La firma se escala grande y se dibuja centrada en esa franja, solapando texto y línea.
    """

    def __init__(
        self,
        png_bytes: bytes | None,
        *,
        width: float,
        zone_height: float,
        max_draw_w: float,
        max_draw_h: float,
        h_align: str = "LEFT",
    ):
        super().__init__()
        self.png_bytes = png_bytes
        self.width = width
        self.zone_height = zone_height
        self.max_draw_w = max_draw_w
        self.max_draw_h = max_draw_h
        self.h_align = h_align

    def wrap(self, availWidth, availHeight):
        return self.width, self.zone_height

    def draw(self):
        if not self.png_bytes:
            return
        try:
            reader = ImageReader(BytesIO(self.png_bytes))
            iw, ih = reader.getSize()
            scale = min(
                self.max_draw_w / max(float(iw), 1.0),
                self.max_draw_h / max(float(ih), 1.0),
            )
            dw = float(iw) * scale
            dh = float(ih) * scale
            if self.h_align == "CENTER":
                x = (self.width - dw) / 2.0
            else:
                x = 0.0
            y = (self.zone_height - dh) / 2.0
            self.canv.drawImage(reader, x, y, width=dw, height=dh, mask="auto")
        except Exception:
            return


def _make_scaled_png_image(
    png_bytes: bytes,
    *,
    max_w: float,
    max_h: float,
    h_align: str = "LEFT",
) -> Image | None:
    try:
        reader = ImageReader(BytesIO(png_bytes))
        iw, ih = reader.getSize()
        scale = min(
            max_w / max(float(iw), 1.0),
            max_h / max(float(ih), 1.0),
        )
        img = Image(
            BytesIO(png_bytes),
            width=float(iw) * scale,
            height=float(ih) * scale,
        )
        img.hAlign = h_align
        return img
    except Exception:
        return None


def _party_signature_cell(
    name: str,
    body_st,
    *,
    signature_png: bytes | None = None,
    stamp_png: bytes | None = None,
    stamp_footer_legal_name: str = "",
    stamp_footer_rif: str = "",
) -> Table:
    """Bloque nombre + firma superpuesta + línea (columna arrendador / inquilino)."""
    line_st = ParagraphStyle(
        "PartySigLine",
        parent=body_st,
        fontSize=9,
        leading=_PARTY_SIG_LINE_ROW_H,
    )
    rows: list[list] = [
        [Paragraph(f"<b>{_escape(name)}</b>", body_st)],
        [
            SignatureOverlayFlowable(
                signature_png,
                width=_PARTY_SIG_COL_W,
                zone_height=_SIG_ZONE_LAYOUT_H,
                max_draw_w=_SIG_DRAW_MAX_W,
                max_draw_h=_SIG_DRAW_MAX_H,
                h_align="LEFT",
            )
        ],
        [Paragraph("_________________________", line_st)],
    ]
    style_cmds: list = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("ROWHEIGHT", (0, 0), (0, 0), _PARTY_SIG_NAME_ROW_H),
        ("ROWHEIGHT", (0, 1), (0, 1), _SIG_ZONE_LAYOUT_H),
        ("ROWHEIGHT", (0, 2), (0, 2), _PARTY_SIG_LINE_ROW_H),
    ]
    stamp_rendered = False
    if stamp_png:
        stamp = _make_scaled_png_image(
            stamp_png,
            max_w=_STAMP_DRAW_MAX_W,
            max_h=_STAMP_DRAW_MAX_H,
            h_align="LEFT",
        )
        if stamp:
            rows.append([stamp])
            stamp_row = len(rows) - 1
            style_cmds.append(("TOPPADDING", (0, stamp_row), (0, stamp_row), 6))
            stamp_rendered = True
    if not stamp_rendered:
        for footer_item in _lessor_stamp_footer_rows(
            stamp_footer_legal_name,
            stamp_footer_rif,
            body_st,
        ):
            if isinstance(footer_item, Spacer):
                rows.append([footer_item])
            else:
                rows.append([footer_item])
                footer_row = len(rows) - 1
                style_cmds.append(("TOPPADDING", (0, footer_row), (0, footer_row), 6))
    inner = Table(rows, colWidths=[_PARTY_SIG_COL_W])
    inner.setStyle(TableStyle(style_cmds))
    return inner


def _municipality_lessor_signature_block(
    *,
    lessor: str,
    body_st,
    signature_png: bytes | None = None,
    stamp_png: bytes | None = None,
    stamp_footer_legal_name: str = "",
    stamp_footer_rif: str = "",
) -> list:
    """Cierre centrado de la carta al municipio (texto + firma/sello opcionales)."""
    sig_st = ParagraphStyle(
        "MunSig",
        parent=body_st,
        alignment=TA_CENTER,
        fontSize=9,
    )
    mun_sig_w = 10 * cm
    flow: list = []
    if signature_png:
        mun_sig = Table(
            [
                [
                    SignatureOverlayFlowable(
                        signature_png,
                        width=mun_sig_w,
                        zone_height=_SIG_ZONE_LAYOUT_H,
                        max_draw_w=17 * cm,
                        max_draw_h=_SIG_DRAW_MAX_H,
                        h_align="CENTER",
                    )
                ],
                [
                    Paragraph(
                        f"<b>Gerencia de Mercadeo</b><br/>{_escape(lessor)}",
                        sig_st,
                    )
                ],
            ],
            colWidths=[mun_sig_w],
        )
        mun_sig.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ("ROWHEIGHT", (0, 0), (0, 0), _SIG_ZONE_LAYOUT_H),
                    ("TOPPADDING", (0, 1), (0, 1), -4),
                ]
            )
        )
        mun_sig.hAlign = "CENTER"
        flow.append(mun_sig)
    else:
        flow.append(
            Paragraph(
                f"<b>Gerencia de Mercadeo</b><br/>{_escape(lessor)}",
                sig_st,
            )
        )
    stamp_rendered = False
    if stamp_png:
        stamp = _make_scaled_png_image(
            stamp_png,
            max_w=_STAMP_DRAW_MAX_W,
            max_h=_STAMP_DRAW_MAX_H,
            h_align="CENTER",
        )
        if stamp:
            flow.append(Spacer(1, 0.15 * cm))
            flow.append(stamp)
            stamp_rendered = True
    if not stamp_rendered:
        flow.extend(
            _lessor_stamp_footer_rows(
                stamp_footer_legal_name,
                stamp_footer_rif,
                body_st,
                centered=True,
            )
        )
    return flow


def _order_items_for_pdf(order):
    """Líneas del pedido con toma, centro y tipos/medidas (formats) precargados."""
    fmt_qs = AdSpaceFormat.objects.select_related("product_type").order_by(
        "sort_order", "id"
    )
    return list(
        order.items.select_related("ad_space", "ad_space__shopping_center")
        .prefetch_related(Prefetch("ad_space__formats", queryset=fmt_qs))
        .all()
    )


def _municipality_table_rows_for_item(order_item) -> list[dict]:
    """Una fila por línea de tipo del espacio; si no hay tipos, una fila resumen."""
    ad = order_item.ad_space
    formats = ad_space_formats_ordered(ad)
    if not formats:
        return [
            {
                "tipo": (ad.name or "").strip() or "—",
                "cantidad": 1,
                "medidas": "—",
                "ubicacion": ad_space_location_text(ad) or "—",
                "obs": "—",
            }
        ]
    rows = []
    for fmt in formats:
        ubic = (fmt.location or "").strip() or ad_space_location_text(ad) or "—"
        rows.append(
            {
                "tipo": format_type_name(fmt),
                "cantidad": fmt.quantity if fmt.quantity is not None else 1,
                "medidas": format_medidas_label(fmt),
                "ubicacion": ubic,
                "obs": format_double_sided_observation(fmt),
            }
        )
    return rows


def build_negotiation_sheet_pdf_bytes(
    *,
    order,
    tenant_signature_png: bytes | None = None,
) -> bytes:
    """Hoja de negociación (referencia visual: campos centrados / arrendador-inquilino)."""
    client = order.client
    items = _order_items_for_pdf(order)
    if not items:
        raise ValueError("El pedido no tiene líneas.")
    sc = items[0].ad_space.shopping_center
    lessor, lessor_rif = _workspace_lessor_identity(order)
    center_name = sc.name
    tenant = client.company_name
    rif = (client.rif or "").strip() or "—"
    rep = (client.representative_name or "").strip() or "—"
    rep_ci = (client.representative_id_number or "").strip()
    rep_line = rep
    if rep_ci:
        rep_line = f"{rep} (C.I: {rep_ci})"

    # Resumen de elementos: códigos de toma (con tipos si hay varios)
    codes = ", ".join(ad_space_element_summary(it.ad_space) for it in items)
    start = min(it.start_date for it in items)
    end = max(it.end_date for it in items)
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    from apps.orders.services.order_services import order_line_pricing_totals

    catalog_subtotal, discount_total = order_line_pricing_totals(order)
    total = order.total_amount or Decimal("0")
    iva = (total * IVA_RATE).quantize(Decimal("0.01"))
    total_con_iva = (total + iva).quantize(Decimal("0.01"))

    importe_lines = []
    description_lines = []
    for it in items:
        code = (it.ad_space.code or "").strip()
        title = (it.ad_space.name or "").strip()
        orig = (
            it.original_subtotal
            if it.original_subtotal is not None
            else it.subtotal
        )
        sub = it.subtotal
        head = code or title or "Toma"
        if orig > sub:
            importe_lines.append(
                f"{head}: ${orig:,.2f} catálogo → ${sub:,.2f} acordado "
                f"(desc. ${(orig - sub):,.2f})"
            )
        else:
            importe_lines.append(f"{head}: ${sub:,.2f} USD sin IVA")
        if title:
            fmt_labels = []
            for fmt in ad_space_formats_ordered(it.ad_space):
                label = format_type_name(fmt)
                if label != "—" and label not in fmt_labels:
                    fmt_labels.append(label)
            extra = f" — {', '.join(fmt_labels)}" if fmt_labels else ""
            description_lines.append(
                f"{code} — {title}{extra}" if code else f"{title}{extra}"
            )
        elif code:
            description_lines.append(code)
    importe_txt = "<br/>".join(_escape(x) for x in importe_lines)

    pay_cond = "Según acuerdo comercial con el centro."
    obs_parts = []
    if description_lines:
        obs_parts.append("\n".join(description_lines))
    obs = "\n\n".join(obs_parts) if obs_parts else codes

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.6 * cm,
        bottomMargin=2 * cm,
        title="Hoja de negociación",
    )
    title_st, body_st, label_st, small_st = _styles()
    story = []
    _prepend_order_logo(story, order)
    story.append(Paragraph("HOJA NEGOCIACION TOMAS PUBLICITARIAS", title_st))
    story.append(Spacer(1, 0.4 * cm))

    def row(label: str, value: str, *, html: bool = False):
        value_paragraph = (
            Paragraph(value, body_st)
            if html
            else Paragraph(_escape(value), body_st)
        )
        return [
            Paragraph(f"<b>{_escape(label)}</b>", label_st),
            value_paragraph,
        ]

    data = [
        row("CENTRO", center_name),
        row("ARRENDADOR", f"{lessor} — RIF {lessor_rif}"),
        row("INQUILINO", f"{tenant} — RIF {rif}"),
        row("REPRESENTANTE", rep_line),
        row("ELEMENTO PUBLICITARIO", codes),
        row(
            "PERÍODO NEGOCIACIÓN",
            f"Del {start.strftime('%d/%m/%Y')} al {end.strftime('%d/%m/%Y')}",
        ),
        row("DURACION CONTRATO",
            f"{months} {'mes' if months == 1 else 'meses'}"),
        row("IMPORTE POR TOMA (SIN IVA)", importe_txt, html=True),
    ]
    if discount_total > 0:
        data.extend(
            [
                row(
                    "SUBTOTAL CATÁLOGO (SIN IVA)",
                    f"${catalog_subtotal:,.2f} USD",
                ),
                row("DESCUENTO ACORDADO", f"-${discount_total:,.2f} USD"),
                row("SUBTOTAL ACORDADO (SIN IVA)", f"${total:,.2f} USD"),
            ]
        )
    data.extend(
        [
        row(
            "TOTAL NEGOCIACION (CON IVA)",
            f"${total_con_iva:,.2f} USD",
        ),
        row("CONDICIONES DE PAGO", pay_cond),
        row("OBSERVACIONES", obs),
        ]
    )
    t = Table(data, colWidths=[5 * cm, 12 * cm])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 0.5 * cm))
    story.append(
        Paragraph(
            "<i>(*) Los impuestos municipales serán cancelados por la empresa.</i>",
            small_st,
        )
    )
    story.append(Spacer(1, 2.0 * cm))
    lessor_signature, lessor_stamp = _lessor_pdf_assets(order)
    ws = _order_workspace(order)
    footer_legal, footer_rif = _workspace_legal_stamp_footer(ws)
    sig_table = Table(
        [
            [
                _party_signature_cell(
                    lessor,
                    body_st,
                    signature_png=lessor_signature,
                    stamp_png=lessor_stamp,
                    stamp_footer_legal_name=footer_legal,
                    stamp_footer_rif=footer_rif,
                ),
                _party_signature_cell(
                    tenant,
                    body_st,
                    signature_png=tenant_signature_png,
                ),
            ]
        ],
        colWidths=[8.5 * cm, 8.5 * cm],
    )
    sig_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(sig_table)

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf


def build_municipality_authorization_pdf_bytes(*, order) -> bytes:
    """Carta modelo para alcaldía (referencia visual imagen 2)."""
    client = order.client
    items = _order_items_for_pdf(order)
    if not items:
        raise ValueError("El pedido no tiene líneas.")
    sc = items[0].ad_space.shopping_center
    city = (sc.authorization_letter_city or "Caracas").strip()
    now = timezone.localtime(timezone.now())
    meses = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    date_str = f"{now.day} de {meses[now.month - 1]} de {now.year}"

    authority = (sc.municipal_authority_line or "").strip() or (
        "Sres. Alcaldía Municipio correspondiente"
    )
    tenant = client.company_name
    rif = (client.rif or "").strip() or "—"

    loc_bits = []
    for it in items:
        locs = ad_space_all_location_texts(it.ad_space)
        loc_txt = ", ".join(locs) if locs else ad_space_location_text(it.ad_space)
        loc_bits.append(f"{loc_txt} ({sc.name})")
    location_txt = "; ".join(loc_bits) if loc_bits else sc.name

    start = min(it.start_date for it in items)
    end = max(it.end_date for it in items)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.6 * cm,
        bottomMargin=2 * cm,
        title="Carta al municipio",
    )
    title_st, body_st, label_st, small_st = _styles()
    story = []
    _prepend_order_logo(story, order)
    story.append(Paragraph(f"{_escape(city)}, {date_str}", ParagraphStyle(
        "R", parent=body_st, alignment=TA_RIGHT)))
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph("<b>Atención:</b>", body_st))
    story.append(Paragraph(f"<u><b>{_escape(authority)}</b></u>", body_st))
    story.append(Paragraph("<b>Presente.-</b>", body_st))
    story.append(Spacer(1, 0.6 * cm))
    body_txt = (
        f"Por medio de la presente autorizamos a la empresa <b>{_escape(tenant)}</b>, "
        f"<b>RIF {_escape(rif)}</b> a realizar, ante sus oficinas, todos los trámites necesarios para la "
        f"solicitud de permisos y pagos de impuestos de elementos publicitarios ubicados "
        f"<b>{_escape(location_txt)}</b>, período del: <b>{start.strftime('%d-%m-%Y')}</b> al "
        f"<b>{end.strftime('%d-%m-%Y')}</b> con las siguientes características:"
    )
    story.append(Paragraph(body_txt, body_st))
    story.append(Spacer(1, 0.5 * cm))

    cell_st, head_st, tight_st = _table_paragraph_styles()
    inner = _inner_table_width()
    # Fracciones que suman 1.0; más ancho a ubicación y observación para evitar solapamiento
    fr_tipo, fr_cant, fr_med, fr_ubi, fr_obs = 0.18, 0.06, 0.14, 0.34, 0.28
    tw = [inner * f for f in (fr_tipo, fr_cant, fr_med, fr_ubi, fr_obs)]
    table_data = [
        [
            _p_cell("TIPO DE ELEMENTO", head_st, bold=True),
            _p_cell("CANT.", head_st, bold=True),
            _p_cell("MEDIDAS POR ELEMENTO", head_st, bold=True),
            _p_cell("UBICACIÓN", head_st, bold=True),
            _p_cell("OBSERVACIÓN", head_st, bold=True),
        ]
    ]
    for it in items:
        for row in _municipality_table_rows_for_item(it):
            table_data.append(
                [
                    _p_cell(str(row["tipo"]), cell_st),
                    _p_cell(str(row["cantidad"]), cell_st),
                    _p_cell(str(row["medidas"]), cell_st),
                    _p_cell(row["ubicacion"], tight_st),
                    _p_cell(row["obs"], tight_st),
                ]
            )
    t = Table(table_data, colWidths=tw, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("Quedo de usted, muy atentamente.",
                 ParagraphStyle("C", parent=body_st, alignment=TA_CENTER)))
    story.append(Spacer(1, 1.2 * cm))
    lessor, _ = _workspace_lessor_identity(order)
    lessor_signature, lessor_stamp = _lessor_pdf_assets(order)
    ws = _order_workspace(order)
    footer_legal, footer_rif = _workspace_legal_stamp_footer(ws)
    story.extend(
        _municipality_lessor_signature_block(
            lessor=lessor,
            body_st=body_st,
            signature_png=lessor_signature,
            stamp_png=lessor_stamp,
            stamp_footer_legal_name=footer_legal,
            stamp_footer_rif=footer_rif,
        )
    )
    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf


def build_invoice_pdf_bytes(*, order) -> bytes:
    """Factura resumida (referencia comercial; no es timbrado fiscal externo)."""
    from apps.orders.services import order_line_pricing_totals

    client = order.client
    items = _order_items_for_pdf(order)
    total = order.total_amount or Decimal("0")
    catalog, discount = order_line_pricing_totals(order)
    iva = (total * IVA_RATE).quantize(Decimal("0.01"))
    grand = (total + iva).quantize(Decimal("0.01"))
    order_ref = (order.code or "").strip() or f"#{order.pk}"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2 * cm,
        title="Nota de cobro",
    )
    title_st, body_st, _, _ = _styles()
    story = []
    _prepend_order_logo(story, order)
    story.append(Paragraph("NOTA DE COBRO", title_st))
    story.append(
        Paragraph(f"<b>Pedido:</b> {_escape(order_ref)}", body_st))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        f"<b>Empresa:</b> {_escape(client.company_name)} &nbsp; RIF: {_escape((client.rif or '').strip() or '—')}", body_st))
    story.append(Spacer(1, 0.5 * cm))
    cell_st, head_st, _ = _table_paragraph_styles()
    inv_cell = ParagraphStyle(
        "InvCell",
        parent=cell_st,
        fontSize=9,
        leading=11,
    )
    inv_head = ParagraphStyle(
        "InvHead", parent=head_st, fontSize=9, leading=11)
    inv_num = ParagraphStyle(
        "InvNum",
        parent=inv_cell,
        alignment=TA_RIGHT,
    )
    rows = [
        [
            _p_cell("Descripción", inv_head, bold=True),
            _p_cell("Cant.", inv_head, bold=True),
            _p_cell("Importe USD", inv_head, bold=True),
        ]
    ]
    for it in items:
        desc = f"{it.ad_space.code} — {it.ad_space.name}"
        rows.append(
            [
                _p_cell(desc, inv_cell),
                _p_cell("1", inv_num),
                _p_cell(f"${it.subtotal:,.2f}", inv_num),
            ]
        )
    if discount > 0:
        rows.append(
            [
                _p_cell("", inv_cell),
                _p_cell("Subtotal catálogo", inv_num),
                _p_cell(f"${catalog:,.2f}", inv_num),
            ]
        )
        rows.append(
            [
                _p_cell("", inv_cell),
                _p_cell("Descuento", inv_num),
                _p_cell(f"-${discount:,.2f}", inv_num),
            ]
        )
    rows.append([_p_cell("", inv_cell), _p_cell("Subtotal", inv_num,
                bold=True), _p_cell(f"${total:,.2f}", inv_num, bold=True)])
    rows.append(
        [
            _p_cell("", inv_cell),
            _p_cell(f"IVA ({int(IVA_RATE * 100)} %)", inv_num),
            _p_cell(f"${iva:,.2f}", inv_num),
        ]
    )
    rows.append([_p_cell("", inv_cell), _p_cell("Total", inv_num,
                bold=True), _p_cell(f"${grand:,.2f}", inv_num, bold=True)])
    t = Table(rows, colWidths=[10 * cm, 3 * cm, 4 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("GRID", (0, 0), (-1, -2), 0.25, colors.HexColor("#e5e7eb")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#111827")),
            ]
        )
    )
    story.append(t)
    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf


def build_installation_permit_request_pdf_bytes(*, order, permit) -> bytes:
    """Solicitud de permiso de instalación enviada por la empresa (PDF interno / correo)."""
    client = order.client
    items = _order_items_for_pdf(order)
    sc = items[0].ad_space.shopping_center if items else None
    center_name = (sc.name if sc else "") or "—"
    ref = (order.code or "").strip() or f"#{order.pk}"
    now = timezone.localtime(timezone.now())

    staff = permit.staff_members or []
    if not isinstance(staff, list):
        staff = []

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.6 * cm,
        bottomMargin=2 * cm,
        title="Solicitud permiso instalación",
    )
    title_st, body_st, label_st, small_st = _styles()
    story = []
    _prepend_order_logo(story, order)
    story.append(Paragraph("SOLICITUD DE PERMISO DE INSTALACIÓN", title_st))
    story.append(Spacer(1, 0.35 * cm))
    story.append(
        Paragraph(
            f"<b>Pedido:</b> {_escape(ref)} &nbsp;·&nbsp; <b>Fecha del documento:</b> "
            f"{_escape(now.strftime('%d/%m/%Y %H:%M'))}",
            body_st,
        )
    )
    story.append(Spacer(1, 0.45 * cm))

    def row(label: str, value: str):
        return [
            Paragraph(f"<b>{_escape(label)}</b>", label_st),
            Paragraph(_escape(value), body_st),
        ]

    data = [
        row("Empresa", (client.company_name or "").strip() or "—"),
        row("RIF empresa", (client.rif or "").strip() or "—"),
        row("Centro comercial", center_name),
        row("Fecha de montaje indicada",
            permit.mounting_date.strftime("%d/%m/%Y")),
        row("Empresa de instalación",
            (permit.installation_company_name or "").strip() or "—"),
    ]
    ref_m = (permit.municipal_reference or "").strip()
    if ref_m:
        data.append(row("Referencia municipal", ref_m))
    notes = (permit.notes or "").strip()
    if notes:
        data.append(row("Notas", notes))

    t = Table(data, colWidths=[5 * cm, 12 * cm])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph("<b>Personal en sitio (cuadrilla)</b>", label_st))
    story.append(Spacer(1, 0.2 * cm))

    tc_st, th_st, _ = _table_paragraph_styles()
    staff_rows = [
        [
            _p_cell("Nombre completo", th_st, bold=True),
            _p_cell("Cédula / documento", th_st, bold=True),
        ]
    ]
    for m in staff:
        if not isinstance(m, dict):
            continue
        fn = (m.get("full_name") or "").strip() or "—"
        nid = (m.get("id_number") or "").strip() or "—"
        staff_rows.append([_p_cell(fn, tc_st), _p_cell(nid, tc_st)])
    if len(staff_rows) == 1:
        staff_rows.append([_p_cell("—", tc_st), _p_cell("—", tc_st)])

    st = Table(staff_rows, colWidths=[10 * cm, 7 * cm])
    st.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(st)
    story.append(Spacer(1, 0.8 * cm))
    story.append(
        Paragraph(
            "<i>Documento generado automáticamente al enviar la solicitud desde el marketplace "
            "(uso interno del centro / trámites).</i>",
            small_st,
        )
    )

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf
