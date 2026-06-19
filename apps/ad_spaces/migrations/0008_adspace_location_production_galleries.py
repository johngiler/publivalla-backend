"""Galerías de ubicación y arte/producción; migra el archivo único legacy."""

from django.db import migrations, models

import apps.common.utils.media_layout


def _migrate_legacy_single_images(apps, schema_editor):
    AdSpace = apps.get_model("ad_spaces", "AdSpace")
    LocationImage = apps.get_model("ad_spaces", "AdSpaceLocationImage")
    ProductionImage = apps.get_model("ad_spaces", "AdSpaceProductionImage")

    for sp in AdSpace.objects.all().iterator():
        loc = getattr(sp, "location_image", None)
        if loc:
            LocationImage.objects.create(
                ad_space_id=sp.pk,
                image=loc,
                sort_order=0,
            )
        prod = getattr(sp, "production_image", None)
        if prod:
            ProductionImage.objects.create(
                ad_space_id=sp.pk,
                image=prod,
                sort_order=0,
            )


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("ad_spaces", "0007_alter_adspace_availability"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdSpaceLocationImage",
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
                (
                    "image",
                    models.ImageField(
                        upload_to=apps.common.utils.media_layout.ad_space_location_image_upload
                    ),
                ),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "ad_space",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="location_images",
                        to="ad_spaces.adspace",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="AdSpaceProductionImage",
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
                (
                    "image",
                    models.ImageField(
                        upload_to=apps.common.utils.media_layout.ad_space_production_image_upload
                    ),
                ),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "ad_space",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="production_images",
                        to="ad_spaces.adspace",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.RunPython(_migrate_legacy_single_images, _noop_reverse),
        migrations.RemoveField(
            model_name="adspace",
            name="location_image",
        ),
        migrations.RemoveField(
            model_name="adspace",
            name="production_image",
        ),
    ]
