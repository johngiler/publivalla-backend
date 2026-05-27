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
    address = models.TextField(blank=True)
    country = models.CharField(max_length=120, blank=True, default="Venezuela")
    description = models.TextField(blank=True)
    cover_image = models.ImageField(
        upload_to=shopping_center_cover_upload,
        blank=True,
        null=True,
        help_text="Portada del centro: media/<slug>/centers/covers/AÑO/MES/ (histórico: centers/covers/…).",
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
        help_text=(
            "Meses con canon +30 %: Margarita jul–ago y nov–dic; resto nov–dic. "
            "Se asignan al guardar según nombre/slug del centro."
        ),
    )
    high_season_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.30"),
        help_text="Recargo fijo en temporada alta (+30 %).",
    )
    rental_billing_unit = models.CharField(
        max_length=20,
        choices=RentalBillingUnit.choices,
        default=RentalBillingUnit.CALENDAR_MONTH,
        help_text="Cotización en marketplace: solo meses de calendario.",
    )

    class Meta:
        ordering = ["slug"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                name="malls_shoppingcenter_workspace_slug_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.slug} — {self.name}"

    def save(self, *args, **kwargs):
        from apps.malls.utils.high_season import apply_lease_high_season_on_center

        apply_lease_high_season_on_center(self)
        self.rental_billing_unit = RentalBillingUnit.CALENDAR_MONTH
        _webp_fields = ("cover_image",)
        _uf = kwargs.get("update_fields")
        if _uf is None or any(f in _uf for f in _webp_fields):
            ensure_imagefields_webp(self, _webp_fields)
        return super().save(*args, **kwargs)
