from decimal import Decimal

from django.db import models

from apps.common.models import TimeStampedActiveModel


class AuctionStatus(models.TextChoices):
    DRAFT = "draft", "Borrador"
    OPEN = "open", "Abierta"
    CLOSED = "closed", "Cerrada"
    AWARDED = "awarded", "Adjudicada"
    CANCELLED = "cancelled", "Cancelada"


class SpaceAuction(TimeStampedActiveModel):
    """Puja por período fijo de una toma (opcional por workspace)."""

    ad_space = models.ForeignKey(
        "ad_spaces.AdSpace",
        on_delete=models.CASCADE,
        related_name="auctions",
    )
    start_date = models.DateField(help_text="Inicio del período de alquiler en disputa.")
    end_date = models.DateField(help_text="Fin del período de alquiler en disputa.")
    opens_at = models.DateTimeField(help_text="Momento en que se aceptan ofertas.")
    closes_at = models.DateTimeField(help_text="Cierre de la recepción de ofertas.")
    status = models.CharField(
        max_length=20,
        choices=AuctionStatus.choices,
        default=AuctionStatus.DRAFT,
        db_index=True,
    )
    minimum_bid_usd = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Oferta mínima inicial (USD).",
    )
    winning_bid = models.ForeignKey(
        "bidding.SpaceBid",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_auctions",
        help_text="Pedido generado al adjudicar la puja.",
    )
    note = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-closes_at", "-id"]
        verbose_name = "Puja de toma"
        verbose_name_plural = "Pujas de tomas"

    def __str__(self):
        return f"Puja {self.pk} — toma {self.ad_space_id} ({self.get_status_display()})"


class SpaceBid(TimeStampedActiveModel):
    auction = models.ForeignKey(
        SpaceAuction,
        on_delete=models.CASCADE,
        related_name="bids",
    )
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.PROTECT,
        related_name="space_bids",
    )
    amount_usd = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["-amount_usd", "-created_at", "-id"]
        verbose_name = "Oferta"
        verbose_name_plural = "Ofertas"

    def __str__(self):
        return f"Oferta {self.pk} — {self.amount_usd} USD"
