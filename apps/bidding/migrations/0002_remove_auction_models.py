from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("bidding", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(name="SpaceBid"),
        migrations.DeleteModel(name="SpaceAuction"),
    ]
