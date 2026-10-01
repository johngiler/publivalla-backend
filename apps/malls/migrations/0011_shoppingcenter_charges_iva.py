from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("malls", "0010_remove_shoppingcenter_lessor_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="shoppingcenter",
            name="charges_iva",
            field=models.BooleanField(
                default=True,
                help_text="Si está desactivado, las tomas de este centro no suman IVA (tasa 0).",
            ),
        ),
    ]
