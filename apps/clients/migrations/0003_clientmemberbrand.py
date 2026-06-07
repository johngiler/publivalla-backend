import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clients", "0002_clientbrand"),
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientMemberBrand",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "brand",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="member_links",
                        to="clients.clientbrand",
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="brand_links",
                        to="users.userprofile",
                    ),
                ),
            ],
            options={
                "ordering": ["brand__name", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="clientmemberbrand",
            constraint=models.UniqueConstraint(
                fields=("profile", "brand"),
                name="clients_clientmemberbrand_profile_brand_uniq",
            ),
        ),
    ]
