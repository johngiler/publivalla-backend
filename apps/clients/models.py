from django.db import models

from apps.common.models import TimeStampedActiveModel
from apps.common.utils.image_webp import ensure_imagefields_webp
from apps.common.utils.media_layout import client_brand_logo_upload, client_cover_upload


class ClientStatus(models.TextChoices):
    ACTIVE = "active", "Activo"
    SUSPENDED = "suspended", "Suspendido"


class Client(TimeStampedActiveModel):
    """
    Empresa cliente del marketplace. Varios usuarios (UserProfile con rol cliente) pueden
    vincularse a la misma fila; cada usuario solo puede estar vinculado a una empresa a la vez.
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="clients",
        help_text="Tenant al que pertenece la empresa cliente (RIF único por workspace cuando está indicado).",
    )
    company_name = models.CharField(max_length=255)
    rif = models.CharField(
        max_length=32,
        blank=True,
        null=True,
        help_text="Identificación fiscal; se puede completar después en Mi empresa.",
    )
    contact_name = models.CharField(max_length=255, blank=True)
    representative_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Representante legal o firmante (hoja de negociación, cartas).",
    )
    representative_id_number = models.CharField(
        max_length=32,
        blank=True,
        help_text="Cédula de identidad del representante (ej. V-17.311.805).",
    )
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=ClientStatus.choices,
        default=ClientStatus.ACTIVE,
    )
    cover_image = models.ImageField(
        upload_to=client_cover_upload,
        blank=True,
        null=True,
        help_text="Portada de empresa: media/<slug>/clients/covers/AÑO/MES/ (histórico: covers/clients/…).",
    )

    class Meta:
        ordering = ["company_name"]
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "rif"),
                name="clients_client_workspace_rif_uniq",
            ),
        ]

    def save(self, *args, **kwargs):
        _webp_fields = ("cover_image",)
        _uf = kwargs.get("update_fields")
        if _uf is None or any(f in _uf for f in _webp_fields):
            ensure_imagefields_webp(self, _webp_fields)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.company_name


class ClientBrand(TimeStampedActiveModel):
    """Marca promocionada por una empresa cliente (p. ej. Adidas, Victoria's Secret)."""

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="brands",
    )
    name = models.CharField(max_length=255)
    logo = models.ImageField(
        upload_to=client_brand_logo_upload,
        blank=True,
        null=True,
        help_text="Logo de marca: media/<slug>/clients/brands/AÑO/MES/.",
    )

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=("client", "name"),
                name="clients_clientbrand_client_name_uniq",
            ),
        ]

    def save(self, *args, **kwargs):
        _webp_fields = ("logo",)
        _uf = kwargs.get("update_fields")
        if _uf is None or any(f in _uf for f in _webp_fields):
            ensure_imagefields_webp(self, _webp_fields)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ClientMemberBrand(models.Model):
    """Marcas de la empresa asignadas a un usuario cliente (puede ser ninguna, una o varias)."""

    profile = models.ForeignKey(
        "users.UserProfile",
        on_delete=models.CASCADE,
        related_name="brand_links",
    )
    brand = models.ForeignKey(
        ClientBrand,
        on_delete=models.CASCADE,
        related_name="member_links",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["brand__name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "brand"),
                name="clients_clientmemberbrand_profile_brand_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.profile_id} → {self.brand_id}"


class ClientAdSpaceFavorite(TimeStampedActiveModel):
    """Toma marcada como favorita por un cliente (mismo workspace que el espacio)."""

    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name="ad_space_favorites",
    )
    ad_space = models.ForeignKey(
        "ad_spaces.AdSpace",
        on_delete=models.CASCADE,
        related_name="client_favorites",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=("client", "ad_space"),
                name="clients_favorite_client_ad_space_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.client_id} ♥ {self.ad_space_id}"
