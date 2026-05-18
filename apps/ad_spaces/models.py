from django.db import models

from apps.common.utils.image_webp import ensure_imagefields_webp
from apps.common.utils.media_layout import ad_space_cover_upload, ad_space_gallery_upload
from apps.common.models import TimeStampedActiveModel


class AdSpaceType(models.TextChoices):
    """Tipos genéricos (compat.) + formatos alineados a catálogos PDF de espacios en CC."""

    BILLBOARD = "billboard", "Valla (genérico)"
    BANNER = "banner", "Banner / pendón (genérico)"
    ELEVATOR = "elevator", "Ascensor"
    OTHER = "other", "Otro"
    # Vallas / gigantografías
    VALLA_VERTICAL = "valla_vertical", "Valla vertical / gigantografía vertical"
    VALLA_HORIZONTAL = "valla_horizontal", "Valla horizontal / gigantografía horizontal"
    GIGANTOGRAFIA_FACHADA = "gigantografia_fachada", "Gigantografía en fachada"
    # Pendones (balcón, atrio, pasillos, plaza, columna)
    PENDON_BALCON = "pendon_balcon", "Pendón de balcón"
    PENDON_ATRIO = "pendon_atrio", "Pendón de atrio / colgante central"
    PENDON_PASILLO = "pendon_pasillo", "Pendón de pasillo"
    PENDON_PLAZA = "pendon_plaza", "Pendón de plaza"
    PENDON_COLUMNA = "pendon_columna", "Pendón de columna"


class AdSpaceStatus(models.TextChoices):
    AVAILABLE = "available", "Disponible"
    RESERVED = "reserved", "Reservado"
    OCCUPIED = "occupied", "Ocupado"
    BLOCKED = "blocked", "Bloqueado"


class AdSpace(TimeStampedActiveModel):
    code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text="Código único de la toma: prefijo-T{número}[sufijo], ej. DEMO-T1, CC-T2A (el prefijo no depende del centro).",
    )
    shopping_center = models.ForeignKey(
        "malls.ShoppingCenter",
        on_delete=models.CASCADE,
        related_name="ad_spaces",
    )
    type = models.CharField(max_length=32, choices=AdSpaceType.choices)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    width = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    material = models.CharField(max_length=255, blank=True)
    location_description = models.TextField(blank=True)
    level = models.CharField(max_length=64, blank=True)
    monthly_price_usd = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=AdSpaceStatus.choices,
        default=AdSpaceStatus.AVAILABLE,
    )
    cover_image = models.ImageField(
        upload_to=ad_space_cover_upload,
        blank=True,
        null=True,
        help_text="Copia de la primera imagen de galería; media/<slug>/spaces/covers/AÑO/MES/ (histórico: spaces/covers/…). La galería va en spaces/gallery/….",
    )
    # PDF: zona comercial (Plaza Jardín, pasillo X→Y, etc.)
    venue_zone = models.CharField(max_length=255, blank=True)
    double_sided = models.BooleanField(default=False)
    # PDF: «Especificaciones para artes y producción»
    production_specs = models.TextField(blank=True)
    # PDF: observaciones de montaje (bolsillo 4,5 cm, prohibición pendón corrido, etc.)
    installation_notes = models.TextField(blank=True)
    hem_pocket_top_cm = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        help_text="Hueco superior tipo bolsillo (ej. 4,5 cm en pendones balcón).",
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


class AdSpaceImage(models.Model):
    """Imágenes de galería de una toma (ordenadas). La portada es la primera."""

    ad_space = models.ForeignKey(
        AdSpace,
        on_delete=models.CASCADE,
        related_name="gallery_images",
    )
    image = models.ImageField(
        upload_to=ad_space_gallery_upload,
        help_text="Galería de la toma: media/<slug>/spaces/gallery/AÑO/MES/ (histórico: spaces/gallery/…).",
    )
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
