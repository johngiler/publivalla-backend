from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_order_invoice_digital"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="order",
            name="invoice_number",
        ),
        migrations.RemoveField(
            model_name="order",
            name="negotiation_observations",
        ),
        migrations.RemoveField(
            model_name="order",
            name="payment_conditions",
        ),
    ]
