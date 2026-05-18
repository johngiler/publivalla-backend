from django.contrib import admin

from apps.providers.models import MountingProvider


@admin.register(MountingProvider)
class MountingProviderAdmin(admin.ModelAdmin):
    list_display = (
        "company_name",
        "workspace",
        "is_active",
        "sort_order",
        "created_at",
    )
    list_filter = ("is_active", "workspace")
    search_fields = ("company_name", "rif", "email")
    filter_horizontal = ("shopping_centers",)
