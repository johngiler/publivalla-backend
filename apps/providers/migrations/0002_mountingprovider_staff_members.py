from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("providers", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="mountingprovider",
            name="staff_members",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Personal autorizado en sitio: [{"full_name": "...", "id_number": "V-..."}].',
            ),
        ),
    ]
