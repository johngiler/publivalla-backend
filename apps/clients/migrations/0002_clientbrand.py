import apps.common.utils.media_layout
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("clients", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientBrand",
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
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "is_active",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                        help_text="Si está desmarcado, el registro se considera inactivo (no borrado).",
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "logo",
                    models.ImageField(
                        blank=True,
                        help_text="Logo de marca: media/<slug>/clients/brands/AÑO/MES/.",
                        null=True,
                        upload_to=apps.common.utils.media_layout.client_brand_logo_upload,
                    ),
                ),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="brands",
                        to="clients.client",
                    ),
                ),
            ],
            options={
                "ordering": ["name", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="clientbrand",
            constraint=models.UniqueConstraint(
                fields=("client", "name"),
                name="clients_clientbrand_client_name_uniq",
            ),
        ),
    ]
