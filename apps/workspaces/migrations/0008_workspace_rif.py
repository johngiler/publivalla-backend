from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0007_workspace_signature_stamp_png"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="rif",
            field=models.CharField(
                blank=True,
                help_text="RIF fiscal del owner (opcional). Arrendador en documentos legales del pedido.",
                max_length=32,
                verbose_name="RIF",
            ),
        ),
        migrations.AlterField(
            model_name="workspace",
            name="legal_name",
            field=models.CharField(
                blank=True,
                help_text="Razón social u organismo propietario (opcional). Se usa como arrendador en PDFs del pedido.",
                max_length=255,
            ),
        ),
    ]
