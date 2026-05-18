from django.db import models

from apps.common.models import TimeStampedActiveModel


class AvailabilityBlockType(models.TextChoices):
    OCCUPIED = "occupied", "Ocupado"
    EXPIRED = "expired", "Caducado"


class AvailabilityBlock(TimeStampedActiveModel):
    ad_space = models.ForeignKey(
        "ad_spaces.AdSpace",
        on_delete=models.CASCADE,
        related_name="availability_blocks",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    type = models.CharField(max_length=20, choices=AvailabilityBlockType.choices)
    note = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Motivo interno (mantenimiento, reserva manual, etc.).",
    )

    class Meta:
        ordering = ["-start_date", "-id"]

    def __str__(self):
        return f"{self.ad_space_id} {self.start_date}–{self.end_date}"
