from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("malls", "0009_alter_shoppingcenter_high_season_months"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="shoppingcenter",
            name="lessor_legal_name",
        ),
        migrations.RemoveField(
            model_name="shoppingcenter",
            name="lessor_rif",
        ),
    ]
