from django.db import models

from apps.common.utils.image_webp import ensure_imagefields_webp
from apps.common.utils.media_layout import (
    ad_space_cover_upload,
    ad_space_gallery_upload,
    ad_space_location_image_upload,
    ad_space_production_image_upload,
)
from apps.common.models import TimeStampedActiveModel


class AdSpaceType(models.TextChoices):
    """Etiquetas legacy usadas al migrar tipos por workspace."""

    BILLBOARD = "billboard", "Valla (genérico)"
    BANNER = "banner", "Banner / pendón (genérico)"
    ELEVATOR = "elevator", "Ascensor"
    OTHER = "other", "Otro"
    VALLA_VERTICAL = "valla_vertical", "Valla vertical / gigantografía vertical"
    VALLA_HORIZONTAL = "valla_horizontal", "Valla horizontal / gigantografía horizontal"
    GIGANTOGRAFIA_FACHADA = "gigantografia_fachada", "Gigantografía en fachada"
    PENDON_BALCON = "pendon_balcon", "Pendón de balcón"
    PENDON_ATRIO = "pendon_atrio", "Pendón de atrio / colgante central"
    PENDON_PASILLO = "pendon_pasillo", "Pendón de pasillo"
    PENDON_PLAZA = "pendon_plaza", "Pendón de plaza"
    PENDON_COLUMNA = "pendon_columna", "Pendón de columna"


class AdSpaceAvailability(models.TextChoices):
    AVAILABLE = "available", "Disponible"
    OCCUPIED = "occupied", "Ocupado"
    BLOCKED = "blocked", "Bloqueado"


class AdSpaceProductType(TimeStampedActiveModel):
    """Tipo de elemento publicitario configurable por workspace (admin)."""

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="ad_space_product_types",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=64)

    class Meta:
        ordering = ["name", "slug"]
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "slug"),
                name="ad_spaces_product_type_workspace_slug_uniq",
            ),
        ]

    def __str__(self):
        return self.name


class AdSpace(TimeStampedActiveModel):
    code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text="Código único de la toma: prefijo-T{número}[sufijo], ej. DEMO-T1, CC-T2A.",
    )
    shopping_center = models.ForeignKey(
        "malls.ShoppingCenter",
        on_delete=models.CASCADE,
        related_name="ad_spaces",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    monthly_price_usd = models.DecimalField(max_digits=12, decimal_places=2)
    availability = models.CharField(
        max_length=20,
        choices=AdSpaceAvailability.choices,
        default=AdSpaceAvailability.AVAILABLE,
        help_text="Disponibilidad comercial (disponible, ocupado o bloqueado manualmente).",
    )
    cover_image = models.ImageField(
        upload_to=ad_space_cover_upload,
        blank=True,
        null=True,
        help_text="Copia de la primera imagen de galería (portada).",
    )

    class Meta:
        ordering = ["shopping_center", "code"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        _webp_fields = ("cover_image",)
        _uf = kwargs.get("update_fields")
        if _uf is None or any(f in _uf for f in _webp_fields):
            ensure_imagefields_webp(self, _webp_fields)
        return super().save(*args, **kwargs)


class AdSpaceFormat(models.Model):
    """Línea de tipo / medidas asociada a un espacio publicitario."""

    ad_space = models.ForeignKey(
        AdSpace,
        on_delete=models.CASCADE,
        related_name="formats",
    )
    product_type = models.ForeignKey(
        AdSpaceProductType,
        on_delete=models.PROTECT,
        related_name="space_formats",
    )
    width = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    location = models.TextField(blank=True, default="")
    double_sided = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.ad_space_id}:{self.product_type_id}"


class AdSpaceImage(models.Model):
    """Imágenes de galería de portada (ordenadas). La portada es la primera."""

    ad_space = models.ForeignKey(
        AdSpace,
        on_delete=models.CASCADE,
        related_name="gallery_images",
    )
    image = models.ImageField(upload_to=ad_space_gallery_upload)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.ad_space_id}:{self.sort_order}"

    def save(self, *args, **kwargs):
        _webp_fields = ("image",)
        _uf = kwargs.get("update_fields")
        if _uf is None or any(f in _uf for f in _webp_fields):
            ensure_imagefields_webp(self, _webp_fields)
        return super().save(*args, **kwargs)


class AdSpaceLocationImage(models.Model):
    """Plano o foto de ubicación del espacio (una o varias)."""

    ad_space = models.ForeignKey(
        AdSpace,
        on_delete=models.CASCADE,
        related_name="location_images",
    )
    image = models.ImageField(upload_to=ad_space_location_image_upload)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"loc:{self.ad_space_id}:{self.sort_order}"

    def save(self, *args, **kwargs):
        _webp_fields = ("image",)
        _uf = kwargs.get("update_fields")
        if _uf is None or any(f in _uf for f in _webp_fields):
            ensure_imagefields_webp(self, _webp_fields)
        return super().save(*args, **kwargs)


class AdSpaceProductionImage(models.Model):
    """Referencia de arte y producción (una o varias)."""

    ad_space = models.ForeignKey(
        AdSpace,
        on_delete=models.CASCADE,
        related_name="production_images",
    )
    image = models.ImageField(upload_to=ad_space_production_image_upload)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"prod:{self.ad_space_id}:{self.sort_order}"

    def save(self, *args, **kwargs):
        _webp_fields = ("image",)
        _uf = kwargs.get("update_fields")
        if _uf is None or any(f in _uf for f in _webp_fields):
            ensure_imagefields_webp(self, _webp_fields)
        return super().save(*args, **kwargs)
