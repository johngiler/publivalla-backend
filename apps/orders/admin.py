from django.contrib import admin

from apps.orders.models import (
    Order,
    OrderArtAttachment,
    OrderInstallationPermit,
    OrderItem,
    OrderStatusEvent,
)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    raw_id_fields = ("ad_space",)
    fields = ("ad_space", "start_date", "end_date", "monthly_price", "subtotal", "is_active")


class OrderStatusEventInline(admin.TabularInline):
    model = OrderStatusEvent
    extra = 0
    readonly_fields = ("from_status", "to_status", "created_at", "actor", "note")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "client",
        "status",
        "total_amount",
        "payment_method",
        "submitted_at",
        "hold_expires_at",
        "is_active",
        "created_at",
    )
    list_filter = ("status", "payment_method", "client__workspace", "is_active")
    search_fields = (
        "code",
        "client__company_name",
        "client__email",
    )
    raw_id_fields = ("client",)
    readonly_fields = ("code", "created_at", "updated_at")
    date_hierarchy = "created_at"
    inlines = (OrderItemInline, OrderStatusEventInline)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "code",
                    "client",
                    "status",
                    "total_amount",
                    "payment_method",
                    "submitted_at",
                    "hold_expires_at",
                    "is_active",
                ),
            },
        ),
        (
            "Negociación y facturación",
            {
                "classes": ("collapse",),
                "fields": (
                    "installation_verified_at",
                ),
            },
        ),
        (
            "Documentos",
            {
                "classes": ("collapse",),
                "fields": (
                    "payment_receipt",
                    "negotiation_sheet_pdf",
                    "municipality_authorization_pdf",
                    "invoice_pdf",
                    "negotiation_sheet_signed",
                ),
            },
        ),
        (
            "Auditoría",
            {
                "classes": ("collapse",),
                "fields": ("created_at", "updated_at"),
            },
        ),
    )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "ad_space",
        "start_date",
        "end_date",
        "subtotal",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = ("order__code", "ad_space__code", "ad_space__title")
    raw_id_fields = ("order", "ad_space")


@admin.register(OrderStatusEvent)
class OrderStatusEventAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "from_status", "to_status", "actor", "created_at")
    list_filter = ("to_status",)
    search_fields = ("order__code", "note")
    raw_id_fields = ("order", "actor")
    readonly_fields = ("from_status", "to_status", "created_at", "actor", "note")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(OrderArtAttachment)
class OrderArtAttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "order_item", "file", "created_at", "is_active")
    list_filter = ("is_active",)
    search_fields = ("order__code",)
    raw_id_fields = ("order", "order_item")


@admin.register(OrderInstallationPermit)
class OrderInstallationPermitAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "mounting_date",
        "installation_company_name",
        "municipal_reference",
        "municipal_permit_issued",
        "municipal_tax_payment_receipt",
        "is_active",
    )
    search_fields = ("order__code", "installation_company_name", "municipal_reference")
    raw_id_fields = ("order",)
