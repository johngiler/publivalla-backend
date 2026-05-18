# Generated manually for bloqueos internos (nota + orden de listado).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("availability", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="availabilityblock",
            name="note",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Motivo interno (solo panel admin).",
                max_length=500,
            ),
        ),
        migrations.AlterModelOptions(
            name="availabilityblock",
            options={"ordering": ["-start_date", "-id"]},
        ),
    ]
