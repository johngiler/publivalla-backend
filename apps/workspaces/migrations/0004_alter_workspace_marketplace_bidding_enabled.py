from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0003_workspace_marketplace_bidding_enabled"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workspace",
            name="marketplace_bidding_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Si está activo, varios clientes pueden enviar solicitudes (estado enviada) "
                    "para la misma toma; el equipo elige cuál adjudicar en el panel Pujas."
                ),
                verbose_name="Pujas en marketplace",
            ),
        ),
    ]
