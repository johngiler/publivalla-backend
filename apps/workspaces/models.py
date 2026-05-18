"""
Tenant lógico del SaaS: un owner (marca operadora) con sus CCs, tomas y aislamiento de datos.

- Subdominio: `slug` estable por owner → `https://{slug}.<dominio apex>`.
- Branding macro: logos, colores, textos de soporte (el front puede leer un endpoint público por slug).
- Publivalla (plataforma): staff Django / superusuarios ven todo; no necesitan `workspace` en perfil.
- Admin comercial del owner: `UserProfile.role=admin` + `workspace` = solo su árbol.
"""

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedActiveModel
from apps.common.utils.media_layout import (
    workspace_brand_favicon_upload,
    workspace_brand_logo_mark_upload,
    workspace_brand_logo_png_artifacts_upload,
    workspace_brand_logo_upload,
)
from apps.workspaces.validators import (
    validate_brand_graphic,
    validate_favicon_file,
    validate_png_artifacts,
)


class Workspace(TimeStampedActiveModel):
    slug = models.SlugField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Identificador estable para subdominio y APIs (solo letras minúsculas, números, guiones).",
    )
    name = models.CharField(
        max_length=200,
        help_text="Nombre comercial del owner (marca operadora del marketplace).",
    )
    legal_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Razón social u organismo propietario (opcional).",
    )
    logo = models.FileField(
        "Logo (logotipo completo)",
        upload_to=workspace_brand_logo_upload,
        blank=True,
        null=True,
        validators=[validate_brand_graphic],
        help_text="Marca completa con tipografía (logotipo). Cabecera amplia, pie, emails. Formatos: SVG, PNG, JPEG, GIF o WebP. "
        "Almacenamiento bajo media/<slug>/workspaces/logos/…",
    )
    logo_mark = models.FileField(
        "Isotipo",
        upload_to=workspace_brand_logo_mark_upload,
        blank=True,
        null=True,
        validators=[validate_brand_graphic],
        help_text="Símbolo o marca reducida sin el nombre extendido (header compacto, favicon si no subes uno aparte). Mismos formatos que el logo. "
        "media/<slug>/workspaces/logo_marks/…",
    )
    favicon = models.FileField(
        "Favicon",
        upload_to=workspace_brand_favicon_upload,
        blank=True,
        null=True,
        validators=[validate_favicon_file],
        help_text="Icono de pestaña del navegador. SVG, PNG, ICO, JPEG, GIF o WebP. media/<slug>/workspaces/favicons/…",
    )
    logo_png_artifacts = models.FileField(
        "Logo PNG (correo, PDF y similares)",
        upload_to=workspace_brand_logo_png_artifacts_upload,
        blank=True,
        null=True,
        validators=[validate_png_artifacts],
        help_text="Solo PNG. Se usa en correos transaccionales y PDFs del pedido donde no aplica SVG. "
        "Opcional si ya subes mapas de bits en logotipo/isotipo; recomendado si solo usas SVG en marca. "
        "media/<slug>/workspaces/logo_png_artifacts/…",
    )
    primary_color = models.CharField(
        "Color primario",
        max_length=32,
        blank=True,
        help_text="Hex (ej. #2c2c81). Tema y acentos del marketplace.",
    )
    secondary_color = models.CharField(
        "Color secundario",
        max_length=32,
        blank=True,
        help_text="Hex. Acentos secundarios (ej. badges, CTAs alternos).",
    )
    support_email = models.EmailField(
        "Correo de soporte",
        blank=True,
        help_text="Contacto público del operador (p. ej. pie de página o avisos).",
    )
    phone = models.CharField(
        "Teléfono",
        max_length=32,
        blank=True,
        help_text="Contacto telefónico público del operador (opcional).",
    )
    country = models.CharField(
        "País",
        max_length=120,
        blank=True,
        help_text="País de la sede o operación del owner (opcional).",
    )
    city = models.CharField(
        "Ciudad",
        max_length=120,
        blank=True,
        help_text="Ciudad de la sede o operación del owner (opcional).",
    )
    marketplace_title = models.CharField(
        "Título del marketplace",
        max_length=120,
        blank=True,
        help_text="Nombre corto que ve el visitante (si está vacío, se usa el nombre del workspace).",
    )
    marketplace_tagline = models.CharField(
        "Eslogan / subtítulo",
        max_length=255,
        blank=True,
        help_text="Frase corta opcional (propuesta de valor). Sale en la API pública; la interfaz del marketplace aún puede no mostrarla hasta conectarla en el front.",
    )
    catalog_seeded_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Última importación de catálogo con seed_production_catalog en este workspace.",
    )
    catalog_seeded_centers = models.JSONField(
        default=dict,
        blank=True,
        help_text='Mapa slug de centro → fecha ISO de la última carga (p. ej. {"demo": "2026-05-18T12:00:00+00:00"}).',
    )
    catalog_seed_feeder = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Primer usuario administrador marketplace de este workspace (referencia de carga de catálogo).",
    )
    can_create_shopping_centers = models.BooleanField(
        "Puede crear centros comerciales",
        default=True,
        help_text="Si está desactivado, el panel no permite crear CCs (API y UI).",
    )
    can_create_ad_spaces = models.BooleanField(
        "Puede crear tomas",
        default=True,
        help_text="Si está desactivado, el panel no permite crear tomas / espacios publicitarios.",
    )
    can_create_marketplace_admin_users = models.BooleanField(
        "Puede crear administradores marketplace",
        default=True,
        help_text="Si está desactivado, no se pueden crear ni promover usuarios con rol administrador del panel.",
    )
    # Correo transaccional (notificaciones de pedidos): remitente SMTP del owner, distinto del correo personal.
    transactional_email_host = models.CharField(
        "Servidor SMTP (envío de notificaciones)",
        max_length=255,
        blank=True,
        help_text="Ej. smtp.gmail.com. Si está vacío, no se envían correos automáticos de pedidos con esta cuenta.",
    )
    transactional_email_port = models.PositiveIntegerField(
        "Puerto SMTP",
        default=587,
    )
    transactional_email_use_tls = models.BooleanField(
        "Usar TLS al conectar al SMTP",
        default=True,
    )
    transactional_email_use_ssl = models.BooleanField(
        "SSL implícito al conectar al SMTP",
        default=False,
        help_text="Conexión cifrada desde el inicio (típico en puerto 465). No combinar con STARTTLS en el mismo servidor.",
    )
    transactional_email_username = models.CharField(
        "Usuario SMTP",
        max_length=255,
        blank=True,
    )
    transactional_email_password = models.CharField(
        "Contraseña SMTP",
        max_length=512,
        blank=True,
        help_text="Se guarda en base de datos; restringe acceso al servidor y usa contraseña de aplicación si aplica.",
    )
    transactional_email_from_address = models.EmailField(
        "Dirección remitente (From)",
        blank=True,
        help_text="Correo que verán admin y cliente en notificaciones de pedidos.",
    )
    transactional_email_from_name = models.CharField(
        "Nombre remitente (opcional)",
        max_length=120,
        blank=True,
        help_text="Ej. nombre del marketplace; si está vacío se usa el nombre comercial del workspace.",
    )

    # Método de envío transaccional: SMTP o proveedor por API (Mailgun por ahora).
    transactional_email_method = models.CharField(
        "Método de envío transaccional",
        max_length=20,
        blank=True,
        default="smtp",
        help_text="smtp: credenciales SMTP del formulario; api: relay por API key (Mailgun u otros en el futuro).",
    )
    transactional_email_provider = models.CharField(
        "Proveedor API (si method=api)",
        max_length=40,
        blank=True,
        default="",
        help_text="Proveedor de relay por API key. Por ahora: mailgun.",
    )
    transactional_email_api_key = models.CharField(
        "API key (si method=api)",
        max_length=255,
        blank=True,
        default="",
        help_text="Se guarda en base de datos. Mantener vacío para conservar la clave ya guardada.",
    )
    transactional_email_mailgun_domain = models.CharField(
        "Mailgun domain",
        max_length=255,
        blank=True,
        default="",
        help_text="Dominio verificado en Mailgun, ej. mg.tudominio.com.",
    )
    transactional_email_mailgun_region = models.CharField(
        "Mailgun region",
        max_length=10,
        blank=True,
        default="us",
        help_text="Región de Mailgun: us o eu (define el endpoint).",
    )

    class Meta:
        ordering = ["slug"]
        verbose_name = "Workspace (owner)"
        verbose_name_plural = "Workspaces (owners)"

    def __str__(self):
        return f"{self.slug} — {self.name}"
