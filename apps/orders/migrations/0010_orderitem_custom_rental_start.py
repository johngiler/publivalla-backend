from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0009_alter_orderitem_subtotal"),
    ]

    operations = [
        migrations.AddField(
            model_name="orderitem",
            name="custom_rental_start_enabled",
            field=models.BooleanField(
                default=False,
                help_text="Si está activo, el alquiler comienza en custom_rental_start_date (día del mes inicial).",
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="custom_rental_start_date",
            field=models.DateField(
                blank=True,
                help_text="Día de inicio acordado dentro del mes inicial de la reserva.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="first_month_agreed_subtotal",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Importe acordado solo para el mes inicial cuando el inicio es parcial.",
                max_digits=12,
                null=True,
            ),
        ),
    ]
