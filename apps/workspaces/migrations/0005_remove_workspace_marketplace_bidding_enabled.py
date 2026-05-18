from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0004_alter_workspace_marketplace_bidding_enabled"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="workspace",
            name="marketplace_bidding_enabled",
        ),
    ]
