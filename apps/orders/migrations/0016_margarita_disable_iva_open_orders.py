"""Sambil Margarita no cobra IVA. Ajusta líneas abiertas y hojas sin firmar."""

from decimal import Decimal

from django.db import migrations
from django.db.models import Q

# Aún no hay hoja firmada ni un paso posterior a la solicitud aprobada.
_OPEN_STATUSES = ("draft", "submitted", "client_approved")


def forwards(apps, schema_editor):
    from apps.malls.models import ShoppingCenter
    from apps.malls.utils.high_season import is_sambil_margarita_center
    from apps.orders.models import Order, OrderItem
    from apps.orders.utils.document_generation import (
        regenerate_unsigned_negotiation_sheet,
    )
    from apps.orders.utils.validators import order_has_negotiation_sheet_signed

    centers = [
        center
        for center in ShoppingCenter.objects.select_related("workspace")
        if (center.workspace.slug or "") == "sambil"
        and is_sambil_margarita_center(center)
    ]
    if not centers:
        print("[margarita-iva] no se encontró Sambil Margarita; nada que hacer")
        return

    updated_centers = ShoppingCenter.objects.filter(
        pk__in=[center.pk for center in centers],
        charges_iva=True,
    ).update(charges_iva=False)

    open_orders = Order.objects.filter(status__in=_OPEN_STATUSES).exclude(
        Q(negotiation_sheet_signed__isnull=False)
        & ~Q(negotiation_sheet_signed="")
    )
    lines = OrderItem.objects.filter(
        ad_space__shopping_center__in=centers,
        order__in=open_orders,
    ).exclude(iva_rate=Decimal("0"))
    order_ids = list(lines.values_list("order_id", flat=True).distinct())
    updated_lines = lines.update(iva_rate=Decimal("0"))

    regenerated = 0
    for order in Order.objects.filter(pk__in=order_ids).order_by("pk"):
        if order_has_negotiation_sheet_signed(order):
            continue
        if regenerate_unsigned_negotiation_sheet(order):
            regenerated += 1

    print(
        "[margarita-iva] centros=%s lineas=%s hojas_regeneradas=%s"
        % (updated_centers, updated_lines, regenerated)
    )


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0015_orderitem_iva_rate"),
        ("malls", "0011_shoppingcenter_charges_iva"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
