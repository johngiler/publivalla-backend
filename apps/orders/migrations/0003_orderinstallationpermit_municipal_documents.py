from django.db import migrations, models

import apps.common.utils.media_layout


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0002_renumber_order_codes_per_workspace"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderinstallationpermit",
            name="municipal_permit_issued",
            field=models.FileField(
                blank=True,
                help_text="Permiso emitido por la alcaldía (PDF o imagen).",
                null=True,
                upload_to=apps.common.utils.media_layout.order_installation_permit_pdf_upload,
            ),
        ),
        migrations.AddField(
            model_name="orderinstallationpermit",
            name="municipal_tax_payment_receipt",
            field=models.FileField(
                blank=True,
                help_text="Soporte de pago del impuesto municipal (PDF o imagen).",
                null=True,
                upload_to=apps.common.utils.media_layout.order_installation_permit_pdf_upload,
            ),
        ),
    ]
