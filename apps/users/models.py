from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.common.utils.media_layout import user_profile_cover_upload


class UserProfile(models.Model):
    """
    Rol de aplicación (JWT + permisos DRF). Distinto de is_staff de Django.

    Reglas de vínculo con empresa (Client):
    - Un usuario tiene como máximo un perfil (`user` es OneToOne) y ese perfil apunta a como mucho
      una empresa (`client`). Así cada usuario representa una sola empresa al reservar; el pedido
      usa siempre `get_marketplace_client(user)` → ese único `client`.
    - Una empresa puede tener muchos perfiles/usuarios (`Client.member_profiles`): varias cuentas
      pueden operar para la misma razón social.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Administrador marketplace"
        CLIENT = "client", "Cliente marketplace"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.CLIENT,
        db_index=True,
    )
    cover_image = models.ImageField(
        upload_to=user_profile_cover_upload,
        blank=True,
        null=True,
        help_text="Foto de perfil: media/<slug>/users/covers/AÑO/MES/ (histórico: covers/users/…).",
    )
    client = models.ForeignKey(
        "clients.Client",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="member_profiles",
        help_text="Empresa que este usuario representa (como mucho una). Obligatorio si el rol es "
        "cliente marketplace. Varios usuarios pueden compartir la misma empresa.",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="staff_profiles",
        help_text="Administrador marketplace: obligatorio (owner del panel). "
        "Cliente marketplace: obligatorio y debe ser el workspace de la empresa vinculada.",
    )

    class Meta:
        ordering = ["user_id"]

    def clean(self):
        super().clean()
        if self.role == self.Role.ADMIN:
            if self.client_id:
                raise ValidationError(
                    {
                        "client": "Los administradores del marketplace no llevan empresa vinculada. "
                        "Quita el cliente o cambia el rol."
                    }
                )
            if not self.workspace_id:
                raise ValidationError(
                    {
                        "workspace": "El workspace del owner es obligatorio para administradores del marketplace."
                    }
                )
        elif self.role == self.Role.CLIENT:
            if not self.client_id:
                raise ValidationError(
                    {
                        "client": "Selecciona la empresa para usuarios con rol cliente marketplace.",
                    }
                )
            if not self.workspace_id:
                raise ValidationError(
                    {
                        "workspace": "Selecciona el workspace del owner (debe ser el de la empresa).",
                    }
                )
            cid = self.client_id
            wid = self.workspace_id
            from apps.clients.models import Client

            try:
                c = Client.objects.get(pk=cid)
            except Client.DoesNotExist:
                raise ValidationError({"client": "La empresa indicada no existe."}) from None
            if c.workspace_id != wid:
                raise ValidationError(
                    {
                        "workspace": "El workspace debe coincidir con el del cliente seleccionado.",
                    }
                )

    def __str__(self):
        return f"{self.user.username} ({self.role})"
