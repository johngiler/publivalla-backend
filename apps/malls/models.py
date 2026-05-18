from decimal import Decimal

from django.db import models

from apps.common.utils.image_webp import ensure_imagefields_webp
from apps.common.utils.media_layout import shopping_center_cover_upload
from apps.common.models import TimeStampedActiveModel


class RentalBillingUnit(models.TextChoices):
    CALENDAR_MONTH = "calendar_month", "Por mes de calendario"
    CALENDAR_DAY = "calendar_day", "Por día de calendario"


class ShoppingCenter(TimeStampedActiveModel):
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="shopping_centers",
        help_text="Owner / tenant al que pertenece este centro comercial.",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(
        max_length=80,
        help_text="Identificador en URL pública (?center=, detalle /api/catalog/centers/{slug}/). Único por workspace.",
    )
    city = models.CharField(max_length=120)
    district = models.CharField(
        max_length=120,
        blank=True,
        help_text="Zona o urbanización para el titular de la tarjeta en portada (ej. Chacao).",
    )
    address = models.TextField(blank=True)
    country = models.CharField(max_length=120, blank=True, default="Venezuela")
    phone = models.CharField(max_length=64, blank=True)
    contact_email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(
        upload_to=shopping_center_cover_upload,
        blank=True,
        null=True,
        help_text="Portada del centro: media/<slug>/centers/covers/AÑO/MES/ (histórico: centers/covers/…).",
    )
    on_homepage = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Si se incluye en el listado público GET /api/centers/ (la portada del sitio lista tomas).",
    )
    listing_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Orden en ese listado de centros (menor primero).",
    )
    marketplace_catalog_enabled = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Si el catálogo público de tomas está habilitado para este centro (reservas en marketplace).",
    )
    lessor_legal_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Razón social del arrendador (Constructora Acme, C.A., etc.).",
    )
    lessor_rif = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="RIF del arrendador en documentos legales.",
    )
    municipal_authority_line = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Destinatario carta municipio, ej. «Sres. Alcaldía Municipio Chacao».",
    )
    municipal_permit_notice = models.TextField(
        blank=True,
        default="",
        help_text="Aviso en catálogo: el cliente debe gestionar permiso municipal.",
    )
    advertising_regulations = models.TextField(
        blank=True,
        default="",
        help_text="Normativas de uso de tomas publicitarias (HTML o texto plano).",
    )
    authorization_letter_city = models.CharField(
        max_length=120,
        blank=True,
        default="Caracas",
        help_text="Ciudad en el encabezado de fecha de la carta al municipio.",
    )
    high_season_months = models.JSONField(
        default=list,
        blank=True,
        help_text="Meses de calendario (1–12) en temporada alta cada año, p. ej. [11, 12, 1].",
    )
    high_season_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text="Factor sobre el canon mensual en meses de temporada alta (1.25 = +25 %).",
    )
    rental_billing_unit = models.CharField(
        max_length=20,
        choices=RentalBillingUnit.choices,
        default=RentalBillingUnit.CALENDAR_MONTH,
        help_text=(
            "Cómo se cotiza y reserva en marketplace: meses de calendario o días "
            "(canon diario = mensual ÷ 30)."
        ),
    )

    class Meta:
        ordering = ["listing_order", "slug"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                name="malls_shoppingcenter_workspace_slug_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.slug} — {self.name}"

    def save(self, *args, **kwargs):
        _webp_fields = ("cover_image",)
        _uf = kwargs.get("update_fields")
        if _uf is None or any(f in _uf for f in _webp_fields):
            ensure_imagefields_webp(self, _webp_fields)
        return super().save(*args, **kwargs)
