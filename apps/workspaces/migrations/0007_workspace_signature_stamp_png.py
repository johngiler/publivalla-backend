from django.db import migrations, models

import apps.common.utils.media_layout
import apps.workspaces.validators


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0006_alter_workspace_transactional_email_from_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="signature_png",
            field=models.FileField(
                blank=True,
                help_text="Solo PNG. Firma del arrendador en hoja de negociación y carta al municipio. media/<slug>/workspaces/signatures/…",
                null=True,
                upload_to=apps.common.utils.media_layout.workspace_brand_signature_png_upload,
                validators=[apps.workspaces.validators.validate_png_artifacts],
                verbose_name="Firma (documentos PDF)",
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="stamp_png",
            field=models.FileField(
                blank=True,
                help_text="Solo PNG. Sello del arrendador en los mismos PDFs (junto a la firma cuando ambos están configurados). media/<slug>/workspaces/stamps/…",
                null=True,
                upload_to=apps.common.utils.media_layout.workspace_brand_stamp_png_upload,
                validators=[apps.workspaces.validators.validate_png_artifacts],
                verbose_name="Sello (documentos PDF)",
            ),
        ),
    ]
