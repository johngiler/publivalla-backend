"""Generación de PDFs (hoja de negociación, carta municipio, factura) con ReportLab."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.utils import ImageReader


IVA_RATE = Decimal("0.16")

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


def build_negotiation_sheet_pdf_bytes(*, order) -> bytes:
    """Hoja de negociación (referencia visual: campos centrados / arrendador-inquilino)."""
    client = order.client
    items = list(order.items.select_related(
        "ad_space", "ad_space__shopping_center").all())
    if not items:
        raise ValueError("El pedido no tiene líneas.")
    sc = items[0].ad_space.shopping_center
    lessor = (sc.lessor_legal_name or "").strip() or "Arrendador"
    lessor_rif = (sc.lessor_rif or "").strip() or "—"
    center_name = sc.name
    tenant = client.company_name
    rif = (client.rif or "").strip() or "—"
    rep = (client.representative_name or "").strip() or "—"
    rep_ci = (client.representative_id_number or "").strip()
    rep_line = rep
    if rep_ci:
        rep_line = f"{rep} (C.I: {rep_ci})"

    # Resumen de elementos: códigos de toma
    codes = ", ".join(it.ad_space.code for it in items)
    start = min(it.start_date for it in items)
    end = max(it.end_date for it in items)
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    total = order.total_amount or Decimal("0")
    iva = (total * IVA_RATE).quantize(Decimal("0.01"))
    total_con_iva = (total + iva).quantize(Decimal("0.01"))

    monthly_lines = []
    for it in items:
        monthly_lines.append(
            f"${it.monthly_price:,.2f} USD / mes · {it.ad_space.code} — {it.ad_space.title}"
        )
    monthly_txt = "<br/>".join(_escape(x) for x in monthly_lines)

    pay_cond = (order.payment_conditions or "").strip(
    ) or "Según acuerdo comercial con el centro."
    obs = (order.negotiation_observations or "").strip() or codes

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.6 * cm,
        bottomMargin=2 * cm,
        title="Hoja negociación",
    )
    title_st, body_st, label_st, small_st = _styles()
    story = []
    _prepend_order_logo(story, order)
    story.append(Paragraph("HOJA NEGOCIACION TOMAS PUBLICITARIAS", title_st))
    story.append(Spacer(1, 0.4 * cm))

    def row(label: str, value: str):
        return [
            Paragraph(f"<b>{_escape(label)}</b>", label_st),
            Paragraph(_escape(value), body_st),
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
        row("CANON DE ARRENDAMIENTO MENSUAL", monthly_txt),
        row(
            "TOTAL NEGOCIACION",
            f"${total:,.2f} USD más ${iva:,.2f} de IVA (total ${total_con_iva:,.2f} USD con IVA)",
        ),
        row("CONDICIONES DE PAGO", pay_cond),
        row("OBSERVACIONES", obs),
    ]
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
    story.append(Spacer(1, 1.2 * cm))
    story.append(
        Table(
            [
                [
                    Paragraph(
                        f"<b>{_escape(lessor)}</b><br/><br/>_________________________", body_st),
                    Paragraph(
                        f"<b>{_escape(tenant)}</b><br/><br/>_________________________", body_st),
                ]
            ],
            colWidths=[8.5 * cm, 8.5 * cm],
        )
    )

    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf


def build_municipality_authorization_pdf_bytes(*, order) -> bytes:
    """Carta modelo para alcaldía (referencia visual imagen 2)."""
    client = order.client
    items = list(order.items.select_related(
        "ad_space", "ad_space__shopping_center").all())
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

    authority = (sc.municipal_authority_line or "").strip(
    ) or "Sres. Alcaldía Municipio correspondiente"
    tenant = client.company_name
    rif = (client.rif or "").strip() or "—"

    loc_bits = []
    for it in items:
        loc_bits.append(
            f"{it.ad_space.venue_zone or it.ad_space.location_description or it.ad_space.title} ({sc.name})"
        )
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
        w = it.ad_space.width or ""
        h = it.ad_space.height or ""
        medidas = f"{w}×{h}" if w and h else "—"
        tipo = it.ad_space.get_type_display() if hasattr(
            it.ad_space, "get_type_display") else it.ad_space.type
        ubic = (it.ad_space.venue_zone or it.ad_space.location_description or it.ad_space.title or "").strip() or "—"
        obs = (it.ad_space.installation_notes or "").strip() or "—"
        table_data.append(
            [
                _p_cell(str(tipo), cell_st),
                _p_cell(str(it.ad_space.quantity or 1), cell_st),
                _p_cell(str(medidas), cell_st),
                _p_cell(ubic, tight_st),
                _p_cell(obs, tight_st),
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
    lessor = (sc.lessor_legal_name or "").strip() or "Arrendador"
    lessor_rif = (sc.lessor_rif or "").strip() or "—"
    story.append(
        Paragraph(
            f"<b>Coordinación de Mercadeo</b><br/>{_escape(lessor)}<br/>RIF {_escape(lessor_rif)}",
            ParagraphStyle("sig", parent=body_st,
                           alignment=TA_CENTER, fontSize=9),
        )
    )
    doc.build(story)
    pdf = buf.getvalue()
    buf.close()
    return pdf


def build_invoice_pdf_bytes(*, order) -> bytes:
    """Factura resumida (referencia comercial; no es timbrado fiscal externo)."""
    client = order.client
    items = list(order.items.select_related(
        "ad_space", "ad_space__shopping_center").all())
    total = order.total_amount or Decimal("0")
    iva = (total * IVA_RATE).quantize(Decimal("0.01"))
    grand = (total + iva).quantize(Decimal("0.01"))
    inv_no = (order.invoice_number or "").strip() or f"REF-{order.pk}"

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm,
                            rightMargin=2 * cm, topMargin=2.5 * cm, bottomMargin=2 * cm)
    title_st, body_st, _, _ = _styles()
    story = []
    _prepend_order_logo(story, order)
    story.append(Paragraph("FACTURA / NOTA DE COBRO", title_st))
    story.append(
        Paragraph(f"<b>Nº referencia:</b> {_escape(inv_no)}", body_st))
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
        desc = f"{it.ad_space.code} — {it.ad_space.title}"
        rows.append(
            [
                _p_cell(desc, inv_cell),
                _p_cell("1", inv_num),
                _p_cell(f"${it.subtotal:,.2f}", inv_num),
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
    items = list(order.items.select_related(
        "ad_space", "ad_space__shopping_center").all())
    sc = items[0].ad_space.shopping_center if items else None
    center_name = (sc.name if sc else "") or "—"
    codes = ", ".join(it.ad_space.code for it in items) if items else "—"
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
        row("Tomas / elementos", codes),
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
