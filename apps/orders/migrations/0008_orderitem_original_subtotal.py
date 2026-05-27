from decimal import Decimal

from django.db import migrations, models


def backfill_original_subtotal(apps, schema_editor):
    OrderItem = apps.get_model("orders", "OrderItem")
    for item in OrderItem.objects.all().iterator():
        OrderItem.objects.filter(pk=item.pk).update(
            original_subtotal=item.subtotal or Decimal("0"),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0007_remove_order_negotiation_invoice_text_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="original_subtotal",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0"),
                help_text="Subtotal de catálogo al enviar el pedido; referencia para descuentos por toma.",
                max_digits=12,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_original_subtotal, migrations.RunPython.noop),
    ]
