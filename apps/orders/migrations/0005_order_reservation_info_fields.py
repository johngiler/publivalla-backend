from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0004_alter_order_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="activity_description",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Reseña o descripción de la actividad (checkout).",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="campaign_concept",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Campaña o concepto publicitario (checkout).",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="complementary_info",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Información complementaria asociada (checkout).",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="instagram_handle",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Cuenta de Instagram del cliente (checkout, sin @).",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="promotion_brand",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Marca a promocionar (checkout).",
                max_length=255,
            ),
        ),
    ]
