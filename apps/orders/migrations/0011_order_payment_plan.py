import django.utils.timezone
from django.db import migrations, models
import apps.common.utils.media_layout


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0010_orderitem_custom_rental_start"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrderPaymentPlan",
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
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                (
                    "enabled",
                    models.BooleanField(
                        default=False,
                        help_text="Si está activo, el cobro se divide en cuotas en lugar de un solo pago.",
                    ),
                ),
                (
                    "order",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_plan",
                        to="orders.order",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="OrderPaymentInstallment",
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
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                (
                    "sequence",
                    models.PositiveSmallIntegerField(
                        help_text="Orden de la cuota (1 = requerida para activar el contrato).",
                    ),
                ),
                (
                    "due_date",
                    models.DateField(
                        help_text="Vencimiento: inicio del primer mes cubierto por la cuota.",
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pendiente"),
                            ("invoiced", "Facturada"),
                            ("paid", "Pagada"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "invoice_pdf",
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to=apps.common.utils.media_layout.order_payment_installment_generated_upload,
                    ),
                ),
                (
                    "invoice_digital",
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to=apps.common.utils.media_layout.order_payment_installment_invoice_digital_upload,
                    ),
                ),
                (
                    "payment_receipt",
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to=apps.common.utils.media_layout.order_payment_installment_receipt_upload,
                    ),
                ),
                ("notified_2d_at", models.DateTimeField(blank=True, null=True)),
                ("notified_1d_at", models.DateTimeField(blank=True, null=True)),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="installments",
                        to="orders.orderpaymentplan",
                    ),
                ),
            ],
            options={
                "ordering": ["sequence", "id"],
            },
        ),
        migrations.CreateModel(
            name="OrderPaymentInstallmentMonth",
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
                ("year", models.PositiveSmallIntegerField()),
                ("month", models.PositiveSmallIntegerField()),
                (
                    "installment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="months",
                        to="orders.orderpaymentinstallment",
                    ),
                ),
            ],
            options={
                "ordering": ["year", "month"],
            },
        ),
        migrations.AddConstraint(
            model_name="orderpaymentinstallment",
            constraint=models.UniqueConstraint(
                fields=("plan", "sequence"),
                name="orders_installment_plan_sequence_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="orderpaymentinstallmentmonth",
            constraint=models.UniqueConstraint(
                fields=("installment", "year", "month"),
                name="orders_installment_month_uniq",
            ),
        ),
    ]
