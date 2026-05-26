from django.db import migrations, models

import apps.common.utils.media_layout


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_order_reservation_info_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="invoice_digital",
            field=models.FileField(
                blank=True,
                help_text="Factura digital externa subida por el admin (PDF o imagen); sustituye la nota de cobro generada.",
                null=True,
                upload_to=apps.common.utils.media_layout.order_invoice_digital_upload,
            ),
        ),
    ]
