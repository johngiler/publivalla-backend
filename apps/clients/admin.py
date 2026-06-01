from django.contrib import admin

from apps.clients.models import Client, ClientAdSpaceFavorite


@admin.register(ClientAdSpaceFavorite)
class ClientAdSpaceFavoriteAdmin(admin.ModelAdmin):
    list_display = ("id", "client", "ad_space", "created_at", "is_active")
    list_filter = ("is_active",)
    search_fields = ("client__company_name", "ad_space__code", "ad_space__name")
    raw_id_fields = ("client", "ad_space")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("company_name", "workspace", "rif", "email", "status")
    list_filter = ("workspace", "status")
    search_fields = ("company_name", "rif", "email")
