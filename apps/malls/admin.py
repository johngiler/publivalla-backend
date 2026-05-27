from django.contrib import admin

from apps.malls.models import ShoppingCenter


@admin.register(ShoppingCenter)
class ShoppingCenterAdmin(admin.ModelAdmin):
    list_display = (
        "slug",
        "name",
        "workspace",
        "city",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "workspace")
    search_fields = ("slug", "name", "city")
