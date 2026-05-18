from django.contrib import admin

from apps.workspaces.models import Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("slug", "name", "legal_name")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        (None, {"fields": ("slug", "name", "legal_name", "is_active")}),
        (
            "Marca visual",
            {
                "description": "Logotipo completo e isotipo: archivos distintos (el isotipo es solo el símbolo; el logo suele incluir nombre o claim).",
                "fields": (
                    "logo",
                    "logo_mark",
                    "logo_png_artifacts",
                    "favicon",
                    "primary_color",
                    "secondary_color",
                ),
            },
        ),
        (
            "Textos del marketplace",
            {"fields": ("marketplace_title", "marketplace_tagline", "support_email")},
        ),
        (
            "Contacto y ubicación",
            {
                "fields": ("phone", "country", "city"),
                "description": "Datos opcionales del owner; pueden mostrarse en pie u otros bloques públicos.",
            },
        ),
        (
            "Carga de catálogo (seed)",
            {
                "fields": (
                    "catalog_seeded_at",
                    "catalog_seeded_centers",
                    "catalog_seed_feeder",
                ),
                "description": (
                    "Auditoría de seed_production_catalog (cualquier owner/centro). "
                    "catalog_seeded_centers: slug del CC → fecha ISO de la última importación."
                ),
            },
        ),
        (
            "Permisos del panel (marketplace)",
            {
                "fields": (
                    "can_create_shopping_centers",
                    "can_create_ad_spaces",
                    "can_create_marketplace_admin_users",
                ),
                "description": "Si desactivas una opción, la API y el panel bloquean esa acción para los administradores del owner.",
            },
        ),
    )
    readonly_fields = (
        "catalog_seeded_at",
        "catalog_seeded_centers",
        "catalog_seed_feeder",
    )
