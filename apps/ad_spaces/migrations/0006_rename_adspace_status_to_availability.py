from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("ad_spaces", "0005_refactor_ad_space_formats"),
    ]

    operations = [
        migrations.RenameField(
            model_name="adspace",
            old_name="status",
            new_name="availability",
        ),
    ]
