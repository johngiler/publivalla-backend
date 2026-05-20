from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedActiveModel
from apps.common.utils.media_layout import (
    order_art_attachment_upload,
    order_generated_document_upload,
    order_installation_permit_pdf_upload,
    order_payment_receipt_upload,
    order_signed_document_upload,
)


class OrderPaymentMethod(models.TextChoices):
    """Medio de pago indicado por el cliente (checkout); visible en el panel admin."""

    UNSET = "", "Sin indicar"
    CARD = "card", "Tarjeta"
    BANK_TRANSFER = "bank_transfer", "Transferencia bancaria"
    MOBILE_PAYMENT = "mobile_payment", "Pago móvil"
    ZELLE = "zelle", "Zelle"
    CRYPTO = "crypto", "Cripto"
    CASH = "cash", "Efectivo"
    OTHER = "other", "Otro"


class OrderStatus(models.TextChoices):
    """
    Orden = flujo comercial típico (el valor en BD no depende del orden declarado).
    Arte aprobado va después de facturada y pagada (subida de artes con pedido pagado).
    """

    DRAFT = "draft", "Borrador"
    SUBMITTED = "submitted", "Enviada"
    CLIENT_APPROVED = "client_approved", "Solicitud aprobada"
    INVOICED = "invoiced", "Facturada"
    PAID = "paid", "Pagada"
    ART_APPROVED = "art_approved", "Arte aprobado"
    PERMIT_PENDING = "permit_pending", "Permiso alcaldía"
    INSTALLATION = "installation", "Instalación"
    ACTIVE = "active", "Activa"
    EXPIRED = "expired", "Vencida"
    CANCELLED = "cancelled", "Rechazada"


class Order(TimeStampedActiveModel):
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    status = models.CharField(
        max_length=32,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    submitted_at = models.DateTimeField(null=True, blank=True)
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    payment_method = models.CharField(
        max_length=32,
        choices=OrderPaymentMethod.choices,
        default=OrderPaymentMethod.UNSET,
        blank=True,
        db_index=True,
    )
    payment_receipt = models.FileField(
        upload_to=order_payment_receipt_upload,
        blank=True,
        null=True,
        help_text="Comprobante subido por el cliente en checkout (media/<slug>/orders/receipts/…; histórico: orders/receipts/…).",
    )
    code = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        help_text="Código único de pedido (#SLUG-ORDER-000001). Se asigna al crear.",
    )
    payment_conditions = models.TextField(
        blank=True,
        default="",
        help_text="Condiciones de pago (hoja de negociación).",
    )
    negotiation_observations = models.TextField(
        blank=True,
        default="",
        help_text="Observaciones en hoja de negociación (líneas del pedido, texto libre).",
    )
    negotiation_sheet_pdf = models.FileField(
        upload_to=order_generated_document_upload,
        blank=True,
        null=True,
        help_text="Hoja de negociación generada al aprobar la solicitud (histórico: orders/generated/…).",
    )
    municipality_authorization_pdf = models.FileField(
        upload_to=order_generated_document_upload,
        blank=True,
        null=True,
        help_text="Carta de autorización para trámite en alcaldía (histórico: orders/generated/…).",
    )
    invoice_pdf = models.FileField(
        upload_to=order_generated_document_upload,
        blank=True,
        null=True,
        help_text="Factura PDF generada al marcar como facturada (histórico: orders/generated/…).",
    )
    negotiation_sheet_signed = models.FileField(
        upload_to=order_signed_document_upload,
        blank=True,
        null=True,
        help_text="Hoja de negociación firmada por el cliente (histórico: orders/signed/…).",
    )
    invoice_number = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Número o referencia de factura (opcional, en PDF).",
    )
    installation_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Cuando mercadeo del CC validó la instalación conforme.",
    )

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not (self.code or "").strip():
            self._assign_code()

    def _assign_code(self):
        from apps.clients.models import Client
        from apps.orders.utils.references import (
            format_order_public_reference,
            workspace_order_sequence,
        )

        slug = ""
        sequence = self.pk
        if self.client_id:
            row = (
                Client.objects.select_related("workspace")
                .filter(pk=self.client_id)
                .only("workspace__slug", "workspace_id")
                .first()
            )
            if row and row.workspace_id:
                slug = row.workspace.slug or ""
                sequence = workspace_order_sequence(self.pk, row.workspace_id)
        ref = format_order_public_reference(sequence, slug)
        Order.objects.filter(pk=self.pk).update(code=ref)
        self.code = ref

    def __str__(self):
        ref = (self.code or "").strip()
        if ref:
            return f"{ref} ({self.get_status_display()})"
        return f"Order {self.pk} ({self.status})"


class OrderStatusEvent(models.Model):
    """Historial de cambios de estado (cliente y administración)."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32)
    created_at = models.DateTimeField(db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_status_events",
    )
    note = models.TextField(blank=True)

    class Meta:
        # Cronológico (más antiguo primero): encaja con líneas de tiempo en la UI.
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Order {self.order_id}: {self.from_status!r} → {self.to_status!r}"


class OrderItem(TimeStampedActiveModel):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    ad_space = models.ForeignKey(
        "ad_spaces.AdSpace",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"Item {self.pk} for order {self.order_id}"


class OrderArtAttachment(TimeStampedActiveModel):
    """Arte(s) enviado(s) por el cliente para revisión."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="art_attachments",
    )
    order_item = models.ForeignKey(
        "OrderItem",
        on_delete=models.CASCADE,
        related_name="art_attachments",
        null=True,
        blank=True,
        help_text="Línea del pedido (toma) a la que aplica el archivo; obligatorio si el pedido tiene varias líneas.",
    )
    file = models.FileField(
        upload_to=order_art_attachment_upload,
        help_text="Arte adjunto (media/<slug>/orders/arts/…; histórico: orders/arts/…).",
    )

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Art {self.pk} order {self.order_id}"


class OrderInstallationPermit(TimeStampedActiveModel):
    """Solicitud de permiso de instalación (datos para el CC / alcaldía)."""

    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="installation_permit",
    )
    mounting_date = models.DateField()
    installation_company_name = models.CharField(max_length=255)
    staff_members = models.JSONField(
        default=list,
        help_text='Lista: [{"full_name": "...", "id_number": "V-12345678"}]',
    )
    notes = models.TextField(blank=True, default="")
    municipal_reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Referencia o expediente municipal si aplica.",
    )
    request_pdf = models.FileField(
        upload_to=order_installation_permit_pdf_upload,
        blank=True,
        null=True,
        help_text="PDF generado al enviar la solicitud (media/<slug>/orders/installation_permits/…; histórico: orders/installation_permits/…).",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Permiso instalación pedido {self.order_id}"
