from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workspaces", "0009_workspace_transactional_email_use_ssl"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_method",
            field=models.CharField(
                blank=True,
                default="smtp",
                help_text="smtp: credenciales SMTP del formulario; api: relay por API key (Mailgun u otros en el futuro).",
                max_length=20,
                verbose_name="Método de envío transaccional",
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_provider",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Proveedor de relay por API key. Por ahora: mailgun.",
                max_length=40,
                verbose_name="Proveedor API (si method=api)",
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_api_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Se guarda en base de datos. Mantener vacío para conservar la clave ya guardada.",
                max_length=255,
                verbose_name="API key (si method=api)",
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_mailgun_domain",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Dominio verificado en Mailgun, ej. mg.tudominio.com.",
                max_length=255,
                verbose_name="Mailgun domain",
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_mailgun_region",
            field=models.CharField(
                blank=True,
                default="us",
                help_text="Región de Mailgun: us o eu (define el endpoint).",
                max_length=10,
                verbose_name="Mailgun region",
            ),
        ),
    ]

