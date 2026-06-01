from django.contrib import admin

from apps.ad_spaces.models import AdSpace, AdSpaceFormat, AdSpaceProductType


class AdSpaceFormatInline(admin.TabularInline):
    model = AdSpaceFormat
    extra = 0
    raw_id_fields = ("product_type",)


@admin.register(AdSpace)
class AdSpaceAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "shopping_center", "monthly_price_usd", "status")
    list_filter = ("shopping_center", "status")
    inlines = [AdSpaceFormatInline]


@admin.register(AdSpaceProductType)
class AdSpaceProductTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "workspace", "is_active")
    list_filter = ("workspace",)
