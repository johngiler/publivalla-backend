from django.db import models

from apps.common.models import TimeStampedActiveModel


class MountingProvider(TimeStampedActiveModel):
    """
    Empresa autorizada para montaje en el marketplace del tenant.
    Puede operar en uno o varios centros comerciales del mismo workspace.
    """

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="mounting_providers",
        help_text="Owner / tenant al que pertenece este proveedor.",
    )
    company_name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=64, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    rif = models.CharField(max_length=32, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    sort_order = models.PositiveSmallIntegerField(default=0)
    shopping_centers = models.ManyToManyField(
        "malls.ShoppingCenter",
        related_name="mounting_providers",
        blank=True,
        help_text="Centros donde este proveedor está autorizado.",
    )

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "company_name"],
                name="providers_mountingprovider_workspace_company_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.company_name} ({self.workspace_id})"
