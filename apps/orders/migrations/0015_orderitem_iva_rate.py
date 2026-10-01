from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0014_sambil_historical_orders_code_fixes"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="iva_rate",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("0.16"),
                help_text="Tasa de IVA congelada al enviar el pedido (0 si el centro no cobra IVA).",
                max_digits=5,
            ),
        ),
    ]
