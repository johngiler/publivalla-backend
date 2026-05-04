from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0007_workspace_creation_capabilities"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_host",
            field=models.CharField(
                blank=True,
                help_text="Ej. smtp.gmail.com. Si está vacío, no se envían correos automáticos de pedidos con esta cuenta.",
                max_length=255,
                verbose_name="Servidor SMTP (envío de notificaciones)",
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_port",
            field=models.PositiveIntegerField(default=587, verbose_name="Puerto SMTP"),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_use_tls",
            field=models.BooleanField(default=True, verbose_name="Usar TLS al conectar al SMTP"),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_username",
            field=models.CharField(blank=True, max_length=255, verbose_name="Usuario SMTP"),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_password",
            field=models.CharField(
                blank=True,
                help_text="Se guarda en base de datos; restringe acceso al servidor y usa contraseña de aplicación si aplica.",
                max_length=512,
                verbose_name="Contraseña SMTP",
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_from_address",
            field=models.EmailField(
                blank=True,
                help_text="Correo que verán admin y cliente en notificaciones de pedidos.",
                max_length=254,
                verbose_name="Dirección remitente (From)",
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="transactional_email_from_name",
            field=models.CharField(
                blank=True,
                help_text="Ej. nombre del marketplace; si está vacío se usa el nombre comercial del workspace.",
                max_length=120,
                verbose_name="Nombre remitente (opcional)",
            ),
        ),
    ]
