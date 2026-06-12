from decimal import Decimal

from django.db import transaction
from rest_framework import serializers

from apps.ad_spaces.utils.covers import ad_space_effective_cover_url
from apps.ad_spaces.models import AdSpace
from apps.common.utils.catalog_access import shopping_center_allows_public_catalog
from apps.clients.models import Client
from apps.orders.models import (
    Order,
    OrderArtAttachment,
    OrderInstallationPermit,
    OrderItem,
    OrderPaymentMethod,
    OrderStatus,
    OrderStatusEvent,
)
from apps.malls.models import ShoppingCenter
from apps.providers.models import MountingProvider
from apps.orders.services import log_order_status_transition
from apps.orders.utils.validators import (
    MIN_RESERVATION_CALENDAR_MONTHS,
    ad_space_allows_marketplace_reservation,
    contract_meets_min_months,
    line_subtotal,
)
from apps.users.utils import get_marketplace_client, is_platform_staff, user_is_admin
from apps.workspaces.tenant import get_workspace_for_request


_RECEIPT_MAX_BYTES = 5 * 1024 * 1024
_RECEIPT_ALLOWED_CT = frozenset(
    {"image/jpeg", "image/png", "image/webp", "application/pdf"}
)
_SIGNATURE_PNG_MAX_BYTES = 512 * 1024


def installation_permit_has_municipal_documents(permit) -> bool:
    if permit is None:
        return False
    return bool(permit.municipal_permit_issued) and bool(
        permit.municipal_tax_payment_receipt
    )


def validate_order_receipt_file(value):
    if value is None:
        return value
    if getattr(value, "size", 0) > _RECEIPT_MAX_BYTES:
        raise serializers.ValidationError("El archivo no puede superar 5 MB.")
    ct = (getattr(value, "content_type", None) or "").strip()
    if ct and ct not in _RECEIPT_ALLOWED_CT:
        raise serializers.ValidationError(
            "Formato no permitido. Usa JPG, PNG, WebP o PDF."
        )
    return value


def validate_negotiation_signature_png(value):
    if value is None:
        raise serializers.ValidationError("Debes dibujar tu firma en el recuadro.")
    if getattr(value, "size", 0) > _SIGNATURE_PNG_MAX_BYTES:
        raise serializers.ValidationError(
            "La firma es demasiado grande. Intenta dibujarla de nuevo."
        )
    if getattr(value, "size", 0) == 0:
        raise serializers.ValidationError("Debes dibujar tu firma en el recuadro.")
    ct = (getattr(value, "content_type", None) or "").strip().lower()
    if ct and ct != "image/png":
        raise serializers.ValidationError("La firma debe enviarse en formato PNG.")
    return value


def _validate_negotiation_signed_order_status(order) -> None:
    if order.status not in (
        OrderStatus.CLIENT_APPROVED,
        OrderStatus.INVOICED,
        OrderStatus.PAID,
    ):
        raise serializers.ValidationError(
            {
                "detail": (
                    "Solo puedes subir o actualizar la hoja firmada cuando el pedido está en "
                    "«Solicitud aprobada», «Facturada» o «Pagada» (por ejemplo, si el equipo actualizó el PDF de "
                    "negociación y necesitas firmar de nuevo)."
                )
            }
        )


def validate_order_invoice_digital_file(value):
    return validate_order_receipt_file(value)


def order_has_external_invoice(order) -> bool:
    return bool(getattr(getattr(order, "invoice_digital", None), "name", ""))


def normalize_order_instagram_handle(value: str) -> str:
    s = (value or "").strip()
    if s.startswith("@"):
        s = s[1:].strip()
    return s


class OrderReservationInfoWriteMixin(serializers.Serializer):
    """Campos de contexto comercial recogidos en checkout."""

    promotion_brand = serializers.CharField(max_length=255)
    campaign_concept = serializers.CharField()
    activity_description = serializers.CharField()
    complementary_info = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    instagram_handle = serializers.CharField(
        required=False, allow_blank=True, max_length=64, default=""
    )

    def validate_promotion_brand(self, value):
        s = (value or "").strip()
        if not s:
            raise serializers.ValidationError("Indica la marca a promocionar.")
        return s

    def validate_campaign_concept(self, value):
        s = (value or "").strip()
        if not s:
            raise serializers.ValidationError(
                "Indica la campaña o concepto publicitario."
            )
        return s

    def validate_activity_description(self, value):
        s = (value or "").strip()
        if not s:
            raise serializers.ValidationError(
                "Indica una reseña o descripción de la actividad."
            )
        return s

    def validate_complementary_info(self, value):
        return (value or "").strip()

    def validate_instagram_handle(self, value):
        return normalize_order_instagram_handle(value)


def order_reservation_info_kwargs(data: dict, *, pop: bool = False) -> dict:
    keys = (
        "promotion_brand",
        "campaign_concept",
        "activity_description",
        "complementary_info",
        "instagram_handle",
    )
    out = {}
    for key in keys:
        if pop:
            if key in ("complementary_info", "instagram_handle"):
                out[key] = data.pop(key, "")
            else:
                out[key] = data.pop(key)
        else:
            out[key] = data.get(key, "")
    return out


def _status_label(value: str) -> str:
    if not value:
        return ""
    try:
        return OrderStatus(value).label
    except ValueError:
        return value


class OrderClientSnapshotSerializer(serializers.ModelSerializer):
    """Datos de la empresa en respuestas de pedido (admin y cliente)."""

    status_label = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = (
            "id",
            "company_name",
            "rif",
            "contact_name",
            "representative_name",
            "representative_id_number",
            "email",
            "phone",
            "address",
            "city",
            "status",
            "status_label",
        )
        read_only_fields = fields

    def get_status_label(self, obj):
        return obj.get_status_display()


class OrderArtAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    order_item_code = serializers.SerializerMethodField()
    order_item_title = serializers.SerializerMethodField()

    class Meta:
        model = OrderArtAttachment
        fields = (
            "id",
            "file",
            "file_url",
            "created_at",
            "order_item",
            "order_item_code",
            "order_item_title",
        )
        read_only_fields = (
            "id",
            "file",
            "file_url",
            "created_at",
            "order_item",
            "order_item_code",
            "order_item_title",
        )

    def get_file_url(self, obj):
        f = obj.file
        if not f:
            return None
        return f.url

    def get_order_item_code(self, obj):
        item = getattr(obj, "order_item", None)
        if item is None:
            return None
        ad = getattr(item, "ad_space", None)
        if ad is None:
            return None
        code = getattr(ad, "code", None)
        return str(code).strip() if code else None

    def get_order_item_title(self, obj):
        item = getattr(obj, "order_item", None)
        if item is None:
            return None
        ad = getattr(item, "ad_space", None)
        if ad is None:
            return None
        title = getattr(ad, "title", None)
        return str(title).strip() if title else None


class OrderInstallationPermitSerializer(serializers.ModelSerializer):
    request_pdf_url = serializers.SerializerMethodField()
    municipal_permit_issued_url = serializers.SerializerMethodField()
    municipal_tax_payment_receipt_url = serializers.SerializerMethodField()

    class Meta:
        model = OrderInstallationPermit
        fields = (
            "id",
            "mounting_date",
            "installation_company_name",
            "staff_members",
            "notes",
            "municipal_reference",
            "created_at",
            "request_pdf_url",
            "municipal_permit_issued_url",
            "municipal_tax_payment_receipt_url",
        )
        read_only_fields = fields

    def get_request_pdf_url(self, obj):
        f = obj.request_pdf
        if not f:
            return None
        return f.url

    def get_municipal_permit_issued_url(self, obj):
        f = obj.municipal_permit_issued
        if not f:
            return None
        return f.url

    def get_municipal_tax_payment_receipt_url(self, obj):
        f = obj.municipal_tax_payment_receipt
        if not f:
            return None
        return f.url


class OrderItemSerializer(serializers.ModelSerializer):
    ad_space_code = serializers.CharField(source="ad_space.code", read_only=True)
    ad_space_title = serializers.CharField(source="ad_space.name", read_only=True)
    shopping_center_id = serializers.IntegerField(
        source="ad_space.shopping_center_id", read_only=True
    )
    shopping_center_name = serializers.CharField(
        source="ad_space.shopping_center.name", read_only=True
    )
    shopping_center_slug = serializers.CharField(
        source="ad_space.shopping_center.slug", read_only=True
    )
    shopping_center_city = serializers.CharField(
        source="ad_space.shopping_center.city", read_only=True
    )
    ad_space_cover_image = serializers.SerializerMethodField()
    ad_space_gallery_images = serializers.SerializerMethodField()
    discount_amount = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = (
            "id",
            "ad_space",
            "ad_space_code",
            "ad_space_title",
            "shopping_center_id",
            "ad_space_cover_image",
            "ad_space_gallery_images",
            "shopping_center_slug",
            "shopping_center_city",
            "shopping_center_name",
            "start_date",
            "end_date",
            "monthly_price",
            "original_subtotal",
            "subtotal",
            "discount_amount",
            "custom_rental_start_enabled",
            "custom_rental_start_date",
            "first_month_agreed_subtotal",
        )

    def get_discount_amount(self, obj):
        orig = obj.original_subtotal if obj.original_subtotal is not None else obj.subtotal
        diff = (orig - obj.subtotal).quantize(Decimal("0.01"))
        return str(diff if diff > 0 else Decimal("0"))

    def get_ad_space_gallery_images(self, obj):
        ad = obj.ad_space
        out = []
        for row in ad.gallery_images.all():
            if row.image:
                out.append(row.image.url)
        return out

    def get_ad_space_cover_image(self, obj):
        return ad_space_effective_cover_url(obj.ad_space)


class OrderStatusEventSerializer(serializers.ModelSerializer):
    from_label = serializers.SerializerMethodField()
    to_label = serializers.SerializerMethodField()
    actor_username = serializers.CharField(
        source="actor.username", read_only=True, allow_null=True
    )

    class Meta:
        model = OrderStatusEvent
        fields = (
            "id",
            "from_status",
            "to_status",
            "from_label",
            "to_label",
            "created_at",
            "actor_username",
            "note",
        )
        read_only_fields = fields

    def get_from_label(self, obj):
        return _status_label(obj.from_status)

    def get_to_label(self, obj):
        return _status_label(obj.to_status)


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    art_attachments = OrderArtAttachmentSerializer(many=True, read_only=True)
    installation_permit = serializers.SerializerMethodField()
    status_timeline = OrderStatusEventSerializer(
        source="status_events", many=True, read_only=True
    )
    status_label = serializers.SerializerMethodField()
    hold_active = serializers.SerializerMethodField()
    code = serializers.CharField(read_only=True)
    payment_method_label = serializers.SerializerMethodField()
    payment_receipt_url = serializers.SerializerMethodField()
    negotiation_sheet_pdf_url = serializers.SerializerMethodField()
    municipality_authorization_pdf_url = serializers.SerializerMethodField()
    invoice_pdf_url = serializers.SerializerMethodField()
    invoice_digital_url = serializers.SerializerMethodField()
    invoice_file_url = serializers.SerializerMethodField()
    has_external_invoice = serializers.SerializerMethodField()
    installation_permit_request_pdf_url = serializers.SerializerMethodField()
    negotiation_sheet_signed_url = serializers.SerializerMethodField()
    client_company_name = serializers.CharField(
        source="client.company_name", read_only=True
    )
    workspace_slug = serializers.CharField(
        source="client.workspace.slug", read_only=True
    )
    client_detail = OrderClientSnapshotSerializer(source="client", read_only=True)
    catalog_subtotal = serializers.SerializerMethodField()
    discount_total = serializers.SerializerMethodField()
    line_pricing_editable = serializers.SerializerMethodField()
    split_payment_enabled = serializers.SerializerMethodField()
    payment_plan = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "id",
            "client",
            "client_company_name",
            "workspace_slug",
            "code",
            "client_detail",
            "status",
            "status_label",
            "hold_active",
            "total_amount",
            "catalog_subtotal",
            "discount_total",
            "line_pricing_editable",
            "split_payment_enabled",
            "payment_plan",
            "submitted_at",
            "hold_expires_at",
            "created_at",
            "payment_method",
            "payment_method_label",
            "payment_receipt_url",
            "promotion_brand",
            "campaign_concept",
            "activity_description",
            "complementary_info",
            "instagram_handle",
            "installation_verified_at",
            "negotiation_sheet_pdf_url",
            "municipality_authorization_pdf_url",
            "invoice_pdf_url",
            "invoice_digital_url",
            "invoice_file_url",
            "has_external_invoice",
            "installation_permit_request_pdf_url",
            "negotiation_sheet_signed_url",
            "items",
            "art_attachments",
            "installation_permit",
            "status_timeline",
            "updated_at",
        )
        read_only_fields = (
            "status",
            "status_label",
            "hold_active",
            "total_amount",
            "catalog_subtotal",
            "discount_total",
            "line_pricing_editable",
            "split_payment_enabled",
            "payment_plan",
            "submitted_at",
            "hold_expires_at",
            "created_at",
            "payment_method",
            "payment_method_label",
            "payment_receipt_url",
            "promotion_brand",
            "campaign_concept",
            "activity_description",
            "complementary_info",
            "instagram_handle",
            "installation_verified_at",
            "negotiation_sheet_pdf_url",
            "municipality_authorization_pdf_url",
            "invoice_pdf_url",
            "invoice_digital_url",
            "invoice_file_url",
            "has_external_invoice",
            "installation_permit_request_pdf_url",
            "negotiation_sheet_signed_url",
            "workspace_slug",
            "code",
            "updated_at",
        )

    def get_status_label(self, obj):
        from apps.orders.services.order_hold_services import order_display_status_label

        return order_display_status_label(obj)

    def get_hold_active(self, obj):
        from apps.orders.services.order_hold_services import order_hold_is_active

        return order_hold_is_active(obj)

    def get_payment_method_label(self, obj):
        v = obj.payment_method or ""
        if not v:
            return OrderPaymentMethod.UNSET.label
        try:
            return OrderPaymentMethod(v).label
        except ValueError:
            return v

    def get_payment_receipt_url(self, obj):
        f = obj.payment_receipt
        if not f:
            return None
        return f.url

    def _file_url(self, f):
        if not f:
            return None
        return f.url

    def get_negotiation_sheet_pdf_url(self, obj):
        return self._file_url(obj.negotiation_sheet_pdf)

    def get_municipality_authorization_pdf_url(self, obj):
        return self._file_url(obj.municipality_authorization_pdf)

    def get_invoice_pdf_url(self, obj):
        return self._file_url(obj.invoice_pdf)

    def get_invoice_digital_url(self, obj):
        return self._file_url(obj.invoice_digital)

    def get_invoice_file_url(self, obj):
        if order_has_external_invoice(obj):
            return self._file_url(obj.invoice_digital)
        return self._file_url(obj.invoice_pdf)

    def get_has_external_invoice(self, obj):
        return order_has_external_invoice(obj)

    def get_installation_permit_request_pdf_url(self, obj):
        from django.core.exceptions import ObjectDoesNotExist

        try:
            p = obj.installation_permit
        except ObjectDoesNotExist:
            return None
        return self._file_url(p.request_pdf)

    def get_negotiation_sheet_signed_url(self, obj):
        return self._file_url(obj.negotiation_sheet_signed)

    def get_catalog_subtotal(self, obj):
        from apps.orders.services import order_line_pricing_totals

        catalog, _ = order_line_pricing_totals(obj)
        return str(catalog)

    def get_discount_total(self, obj):
        from apps.orders.services import order_line_pricing_totals

        _, discount = order_line_pricing_totals(obj)
        return str(discount)

    def get_line_pricing_editable(self, obj):
        from apps.orders.utils.validators import order_line_pricing_editable

        return order_line_pricing_editable(obj)

    def get_split_payment_enabled(self, obj):
        from apps.orders.services.payment_plan_services import order_uses_split_payment

        return order_uses_split_payment(obj)

    def get_payment_plan(self, obj):
        from apps.orders.services.payment_plan_services import get_payment_plan_payload

        return get_payment_plan_payload(obj)

    def get_installation_permit(self, obj):
        from django.core.exceptions import ObjectDoesNotExist

        try:
            p = obj.installation_permit
        except ObjectDoesNotExist:
            return None
        return OrderInstallationPermitSerializer(p).data


class OrderClientPaymentPatchSerializer(serializers.ModelSerializer):
    """
    Comprobante y método de pago solo cuando el pedido está facturado o pagado
    (el pago ya no se envía al crear la solicitud).
    """

    _ALLOWED = frozenset({OrderStatus.INVOICED, OrderStatus.PAID})

    class Meta:
        model = Order
        fields = ("payment_method", "payment_receipt")
        extra_kwargs = {
            "payment_receipt": {"required": False, "allow_null": True},
            "payment_method": {"required": False},
        }

    def validate_payment_receipt(self, value):
        return validate_order_receipt_file(value)

    def validate(self, attrs):
        if self.instance and self.instance.status not in self._ALLOWED:
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Solo puedes indicar método y comprobante de pago cuando el pedido está "
                        "«Facturada» o «Pagada»."
                    )
                }
            )
        if self.instance:
            from apps.orders.services.payment_plan_services import order_uses_split_payment

            if order_uses_split_payment(self.instance):
                raise serializers.ValidationError(
                    {
                        "detail": (
                            "Este pedido usa pago por partes. Adjunta el comprobante en cada "
                            "cuota del plan de pagos."
                        )
                    }
                )
        return attrs

    def update(self, instance, validated_data):
        old_receipt = instance.payment_receipt if instance.payment_receipt else None
        has_new = (
            "payment_receipt" in validated_data
            and validated_data.get("payment_receipt") is not None
        )
        instance = super().update(instance, validated_data)
        if has_new and old_receipt:
            new = instance.payment_receipt
            if new and getattr(old_receipt, "name", None) != getattr(new, "name", None):
                old_receipt.delete(save=False)
        if has_new:
            req = self.context.get("request")
            aid = (
                req.user.pk
                if req and getattr(req, "user", None) is not None and req.user.is_authenticated
                else None
            )
            oid = instance.pk

            def _enqueue() -> None:
                from apps.orders.tasks import schedule_send_order_client_activity_admin_emails

                schedule_send_order_client_activity_admin_emails(
                    oid, "payment_receipt", actor_id=aid
                )

            transaction.on_commit(_enqueue)
        return instance


class OrderLinePricingItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    subtotal = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False
    )
    custom_rental_start_enabled = serializers.BooleanField(required=False)
    custom_rental_start_date = serializers.DateField(required=False, allow_null=True)
    first_month_agreed_subtotal = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
        allow_null=True,
    )


class OrderLinePricingUpdateSerializer(serializers.Serializer):
    items = OrderLinePricingItemSerializer(many=True, allow_empty=False)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Indica al menos una línea.")
        return value

    def save(self, **kwargs):
        order = self.context["order"]
        actor = self.context.get("actor")
        from apps.orders.services import update_order_line_pricing

        return update_order_line_pricing(
            order,
            items=self.validated_data["items"],
            actor=actor,
        )


class OrderAdminPatchSerializer(serializers.ModelSerializer):
    """Administradores: estado del pedido y factura digital."""

    class Meta:
        model = Order
        fields = (
            "status",
            "invoice_digital",
        )
        extra_kwargs = {
            "invoice_digital": {"required": False, "allow_null": True},
        }

    def validate_invoice_digital(self, value):
        if value is None:
            return value
        return validate_order_invoice_digital_file(value)

    def validate(self, attrs):
        from apps.orders.utils.validators import order_admin_commercial_editable

        if (
            "invoice_digital" in attrs
            and attrs["invoice_digital"] is not None
            and not order_admin_commercial_editable(self.instance)
        ):
            raise serializers.ValidationError(
                {
                    "invoice_digital": (
                        "Solo puedes adjuntar la factura digital después de aprobar la solicitud."
                    )
                }
            )
        if "invoice_digital" in attrs and attrs.get("invoice_digital") is not None:
            from apps.orders.services.payment_plan_services import order_uses_split_payment

            if order_uses_split_payment(self.instance):
                raise serializers.ValidationError(
                    {
                        "invoice_digital": (
                            "Con pago por partes activo, adjunta la factura en cada cuota "
                            "del plan de pagos."
                        )
                    }
                )
        new_status = attrs.get("status", self.instance.status)
        if (
            new_status == OrderStatus.EXPIRED
            and self.instance.status != OrderStatus.EXPIRED
        ):
            raise serializers.ValidationError(
                {
                    "status": (
                        "El estado «Vencida» lo asigna el sistema cuando la última línea del pedido "
                        "supera su fecha de fin (proceso automático programado). "
                        "No se puede marcar manualmente."
                    )
                }
            )
        if (
            new_status == OrderStatus.INVOICED
            and self.instance.status != OrderStatus.INVOICED
            and self.instance.status == OrderStatus.CLIENT_APPROVED
        ):
            raise serializers.ValidationError(
                {
                    "status": (
                        "Primero aprueba los artes (estado «Arte aprobado») antes de facturar."
                    )
                }
            )
        if (
            new_status == OrderStatus.INVOICED
            and self.instance.status != OrderStatus.INVOICED
            and not self.instance.negotiation_sheet_signed
        ):
            raise serializers.ValidationError(
                {
                    "status": (
                        "El cliente debe subir la hoja de negociación firmada antes de pasar "
                        "el pedido a «Facturada»."
                    )
                }
            )
        if (
            new_status == OrderStatus.INVOICED
            and self.instance.status != OrderStatus.INVOICED
            and self.instance.status == OrderStatus.ART_APPROVED
            and not self.instance.art_attachments.exists()
        ):
            raise serializers.ValidationError(
                {
                    "status": (
                        "Faltan archivos de arte en el pedido; no se puede facturar sin artes cargados."
                    )
                }
            )
        if (
            new_status == OrderStatus.PAID
            and self.instance.status != OrderStatus.PAID
            and self.instance.status == OrderStatus.INVOICED
        ):
            from apps.orders.services.payment_plan_services import (
                first_installment_has_receipt,
                order_uses_split_payment,
            )

            if order_uses_split_payment(self.instance):
                if not first_installment_has_receipt(self.instance):
                    raise serializers.ValidationError(
                        {
                            "status": (
                                "El cliente debe adjuntar el comprobante de la primera cuota "
                                "desde Mis pedidos antes de pasar el pedido a «Pagada»."
                            )
                        }
                    )
            elif not self.instance.payment_receipt:
                raise serializers.ValidationError(
                    {
                        "status": (
                            "El cliente debe adjuntar el comprobante de pago desde Mis pedidos "
                            "antes de pasar el pedido a «Pagada»."
                        )
                    }
                )
        if (
            new_status == OrderStatus.ART_APPROVED
            and self.instance.status != OrderStatus.ART_APPROVED
            and self.instance.status
            in (OrderStatus.CLIENT_APPROVED, OrderStatus.PAID)
            and not self.instance.art_attachments.exists()
        ):
            raise serializers.ValidationError(
                {
                    "status": (
                        "El cliente debe subir al menos un archivo de arte desde Mis pedidos antes "
                        "de pasar el pedido a «Arte aprobado»."
                    )
                }
            )
        if (
            new_status == OrderStatus.ART_APPROVED
            and self.instance.status != OrderStatus.ART_APPROVED
            and self.instance.status == OrderStatus.CLIENT_APPROVED
            and not self.instance.negotiation_sheet_signed
        ):
            raise serializers.ValidationError(
                {
                    "status": (
                        "El cliente debe subir la hoja de negociación firmada antes de aprobar los artes."
                    )
                }
            )
        if (
            new_status == OrderStatus.PERMIT_PENDING
            and self.instance.status != OrderStatus.PERMIT_PENDING
            and self.instance.status == OrderStatus.PAID
            and not OrderInstallationPermit.objects.filter(
                order_id=self.instance.pk
            ).exists()
        ):
            raise serializers.ValidationError(
                {
                    "status": (
                        "El cliente debe enviar la solicitud de permiso de instalación desde Mis "
                        "pedidos antes de pasar el pedido a «Permiso alcaldía»."
                    )
                }
            )
        if (
            new_status == OrderStatus.INSTALLATION
            and self.instance.status != OrderStatus.INSTALLATION
            and self.instance.status == OrderStatus.PERMIT_PENDING
        ):
            try:
                permit = self.instance.installation_permit
            except OrderInstallationPermit.DoesNotExist:
                permit = None
            if not installation_permit_has_municipal_documents(permit):
                raise serializers.ValidationError(
                    {
                        "status": (
                            "La empresa debe subir el permiso emitido por la alcaldía y el "
                            "comprobante del impuesto municipal desde Mis pedidos antes de pasar "
                            "el pedido a «Instalación»."
                        )
                    }
                )
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        import logging

        from apps.orders.utils.document_generation import (
            generate_invoice_pdf_for_order,
            generate_negotiation_and_municipality_pdfs,
        )

        logger = logging.getLogger(__name__)

        prev = instance.status
        instance = super().update(instance, validated_data)
        if validated_data.get("invoice_digital"):
            from apps.orders.utils.document_generation import _delete_field_file

            _delete_field_file(instance, "invoice_pdf")
            instance.save(update_fields=["invoice_pdf", "updated_at"])
        if prev != instance.status:
            request = self.context.get("request")
            actor = request.user if request and request.user.is_authenticated else None
            cancel_note = ""
            if instance.status == OrderStatus.CANCELLED:
                from apps.orders.services.order_hold_services import NOTE_CANCELLED_BY_TEAM

                cancel_note = NOTE_CANCELLED_BY_TEAM
            log_order_status_transition(
                instance,
                prev,
                instance.status,
                actor=actor,
                note=cancel_note,
            )
            from apps.orders.services.order_hold_services import on_order_status_changed

            on_order_status_changed(
                instance,
                prev,
                instance.status,
                actor=actor,
            )
            if (
                instance.status == OrderStatus.CLIENT_APPROVED
                and prev != OrderStatus.CLIENT_APPROVED
            ):
                order_pk = instance.pk

                def enqueue_client_activation() -> None:
                    from apps.orders.tasks import schedule_notify_client_activation_after_approval

                    schedule_notify_client_activation_after_approval(order_pk)

                transaction.on_commit(enqueue_client_activation)
                try:
                    generate_negotiation_and_municipality_pdfs(instance)
                except Exception as exc:
                    logger.exception("Fallo al generar PDFs de negociación: %s", exc)
                    Order.objects.filter(pk=instance.pk).update(status=prev)
                    instance.status = prev
                    last_ev = OrderStatusEvent.objects.filter(order_id=instance.pk).order_by("-id").first()
                    if last_ev and last_ev.to_status == OrderStatus.CLIENT_APPROVED:
                        last_ev.delete()
                    raise serializers.ValidationError(
                        {
                            "status": (
                                "No se pudieron generar los PDFs de negociación. "
                                "Revisa datos del cliente y del centro; inténtalo de nuevo."
                            ),
                            "detail": str(exc),
                        }
                    ) from exc
                instance.refresh_from_db()
            if instance.status == OrderStatus.INVOICED and prev != OrderStatus.INVOICED:
                instance.refresh_from_db()
                if not order_has_external_invoice(instance):
                    try:
                        generate_invoice_pdf_for_order(instance)
                    except Exception as exc:
                        logger.exception("Fallo al generar factura PDF: %s", exc)
                        Order.objects.filter(pk=instance.pk).update(status=prev)
                        instance.status = prev
                        last_ev = OrderStatusEvent.objects.filter(order_id=instance.pk).order_by("-id").first()
                        if last_ev and last_ev.to_status == OrderStatus.INVOICED:
                            last_ev.delete()
                        raise serializers.ValidationError(
                            {
                                "status": (
                                    "No se pudo generar la factura PDF. Corrige los datos e inténtalo de nuevo."
                                ),
                                "detail": str(exc),
                            }
                        ) from exc
                    instance.refresh_from_db()
                else:
                    from apps.orders.utils.document_generation import _delete_field_file

                    _delete_field_file(instance, "invoice_pdf")
                    instance.save(update_fields=["invoice_pdf", "updated_at"])
            if (
                instance.status == OrderStatus.ACTIVE
                and prev == OrderStatus.INSTALLATION
            ):
                from django.utils import timezone as dj_tz

                Order.objects.filter(pk=instance.pk).update(
                    installation_verified_at=dj_tz.now()
                )
                instance.refresh_from_db(fields=["installation_verified_at"])

        return instance


class OrderClientNegotiationSignedSerializer(serializers.ModelSerializer):
    """Subida de la hoja de negociación firmada (cliente)."""

    class Meta:
        model = Order
        fields = ("negotiation_sheet_signed",)
        extra_kwargs = {
            "negotiation_sheet_signed": {"required": True, "allow_null": False},
        }

    def validate_negotiation_sheet_signed(self, value):
        return validate_order_receipt_file(value)

    def validate(self, attrs):
        inst = self.instance
        _validate_negotiation_signed_order_status(inst)
        return attrs

    def update(self, instance, validated_data):
        old = instance.negotiation_sheet_signed if instance.negotiation_sheet_signed else None
        instance = super().update(instance, validated_data)
        new = instance.negotiation_sheet_signed
        if old and new and getattr(old, "name", None) != getattr(new, "name", None):
            old.delete(save=False)
        if "negotiation_sheet_signed" in validated_data:
            req = self.context.get("request")
            aid = (
                req.user.pk
                if req and getattr(req, "user", None) is not None and req.user.is_authenticated
                else None
            )
            oid = instance.pk

            def _enqueue() -> None:
                from apps.orders.tasks import schedule_send_order_client_activity_admin_emails

                schedule_send_order_client_activity_admin_emails(
                    oid, "negotiation_signed", actor_id=aid
                )

            transaction.on_commit(_enqueue)
        return instance


class OrderClientNegotiationDigitalSignSerializer(serializers.Serializer):
    """Firma digital en la web: dibujo PNG incrustado en la hoja de negociación."""

    signature_png = serializers.FileField()

    def validate_signature_png(self, value):
        return validate_negotiation_signature_png(value)

    def validate(self, attrs):
        order = self.context.get("order")
        if order is None:
            raise serializers.ValidationError({"detail": "Pedido no encontrado."})
        _validate_negotiation_signed_order_status(order)
        if not order.negotiation_sheet_pdf or not getattr(
            order.negotiation_sheet_pdf, "name", ""
        ):
            raise serializers.ValidationError(
                {
                    "detail": (
                        "La hoja de negociación aún no está disponible. "
                        "Espera a que el equipo la genere o recarga la página."
                    )
                }
            )
        return attrs

    def save(self):
        order = self.context["order"]
        upload = self.validated_data["signature_png"]
        signature_bytes = upload.read()
        if not signature_bytes:
            raise serializers.ValidationError(
                {"signature_png": "Debes dibujar tu firma en el recuadro."}
            )

        from apps.orders.utils.document_generation import (
            save_negotiation_sheet_signed_with_digital_signature,
        )

        old = (
            order.negotiation_sheet_signed if order.negotiation_sheet_signed else None
        )
        save_negotiation_sheet_signed_with_digital_signature(order, signature_bytes)
        order.refresh_from_db()
        new = order.negotiation_sheet_signed
        if old and new and getattr(old, "name", None) != getattr(new, "name", None):
            old.delete(save=False)

        req = self.context.get("request")
        aid = (
            req.user.pk
            if req and getattr(req, "user", None) is not None and req.user.is_authenticated
            else None
        )
        oid = order.pk

        def _enqueue() -> None:
            from apps.orders.tasks import schedule_send_order_client_activity_admin_emails

            schedule_send_order_client_activity_admin_emails(
                oid, "negotiation_signed", actor_id=aid
            )

        transaction.on_commit(_enqueue)
        return order


class ClientMountingProviderCreateSerializer(serializers.Serializer):
    """Alta de proveedor de montaje desde el cliente (solo centros que figuran en el pedido)."""

    shopping_center = serializers.PrimaryKeyRelatedField(queryset=ShoppingCenter.objects.all())
    company_name = serializers.CharField(max_length=255)

    def validate_company_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Indica el nombre de la empresa.")
        return name

    def validate_shopping_center(self, center):
        order = self.context.get("order")
        if order is None:
            return center
        if center.workspace_id != order.client.workspace_id:
            raise serializers.ValidationError(
                "El centro comercial no corresponde al espacio de trabajo de este pedido."
            )
        return center

    def validate(self, attrs):
        order = self.context.get("order")
        if order is None:
            return attrs
        center = attrs["shopping_center"]
        allowed = set(
            OrderItem.objects.filter(order_id=order.pk).values_list(
                "ad_space__shopping_center_id", flat=True
            ).distinct()
        )
        allowed.discard(None)
        if center.pk not in allowed:
            raise serializers.ValidationError(
                {"shopping_center": "Ese centro no forma parte de las líneas de este pedido."}
            )
        name = attrs["company_name"]
        existing = MountingProvider.objects.filter(
            workspace_id=center.workspace_id,
            company_name__iexact=name,
            is_active=True,
        ).first()
        if existing is not None and existing.shopping_centers.filter(pk=center.pk).exists():
            raise serializers.ValidationError(
                {
                    "company_name": (
                        "Ya existe un proveedor activo con ese nombre en este centro. "
                        "Elígelo de la lista."
                    )
                }
            )
        attrs["_existing_provider"] = existing
        return attrs


class OrderInstallationPermitWriteSerializer(serializers.Serializer):
    mounting_date = serializers.DateField()
    installation_company_name = serializers.CharField(max_length=255)
    staff_members = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    municipal_reference = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )

    def validate_staff_members(self, value):
        from apps.providers.validators import normalize_staff_members

        return normalize_staff_members(value)

    def validate(self, attrs):
        from datetime import timedelta

        order = self.context.get("order")
        if order is None:
            return attrs
        items = list(order.items.all())
        if not items:
            return attrs
        min_start = min(it.start_date for it in items)
        earliest = min_start - timedelta(days=1)
        md = attrs["mounting_date"]
        if md < earliest:
            raise serializers.ValidationError(
                {
                    "mounting_date": (
                        "La fecha de montaje no puede ser anterior al día previo al inicio "
                        f"del contrato ({earliest.strftime('%d/%m/%Y')})."
                    )
                }
            )
        return attrs


class OrderItemWriteSerializer(serializers.Serializer):
    """Solo espacio y fechas; precio y subtotal los fija el servidor."""

    ad_space = serializers.PrimaryKeyRelatedField(
        queryset=AdSpace.objects.select_related("shopping_center").all()
    )
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, data):
        start = data["start_date"]
        end = data["end_date"]
        if end < start:
            raise serializers.ValidationError(
                {"end_date": "La fecha fin debe ser posterior o igual al inicio."}
            )
        ad = data["ad_space"]
        center = ad.shopping_center
        from apps.orders.utils.rental_billing import (
            contract_meets_minimum,
            line_subtotal_for_center,
            min_units_label,
            rental_start_allowed,
        )

        unit = center.rental_billing_unit
        if not contract_meets_minimum(unit, start, end):
            n, label = min_units_label(unit)
            raise serializers.ValidationError(
                {
                    "end_date": (
                        f"El período debe cubrir al menos {n} {label}."
                    )
                }
            )
        if not rental_start_allowed(unit, start):
            raise serializers.ValidationError(
                {
                    "start_date": (
                        "La fecha de inicio no puede ser hoy ni un día pasado. "
                        "Elige una fecha futura válida."
                        if unit == "calendar_day"
                        else (
                            "No puedes reservar desde un mes pasado. "
                            "El mes en curso solo está disponible hasta el día 15."
                        )
                    )
                }
            )
        if not ad_space_allows_marketplace_reservation(ad):
            raise serializers.ValidationError(
                {
                    "ad_space": (
                        f"La toma {ad.code} no admite nuevas reservas "
                        f"(disponibilidad: {ad.get_availability_display()})."
                    )
                }
            )
        monthly = ad.monthly_price_usd
        data["_monthly_price"] = monthly
        data["_subtotal"] = line_subtotal_for_center(monthly, center, start, end)
        return data


class OrderCreateSerializer(OrderReservationInfoWriteMixin, serializers.Serializer):
    client = serializers.PrimaryKeyRelatedField(
        queryset=Client.objects.all(),
        required=False,
        allow_null=True,
    )
    items = OrderItemWriteSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Agrega al menos una toma.")
        from apps.orders.utils.validators import order_request_items_have_internal_overlap

        if order_request_items_have_internal_overlap(value):
            raise serializers.ValidationError(
                "Las fechas de una misma toma no pueden solaparse en el pedido."
            )
        return value

    def validate(self, data):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError("Debes iniciar sesión para crear una orden.")
        if is_platform_staff(request.user):
            raise serializers.ValidationError({"detail": "No se pudo completar la operación."})

        ws = get_workspace_for_request(request)

        if user_is_admin(request.user):
            raise serializers.ValidationError({"detail": "No se pudo completar la operación."})

        ce = get_marketplace_client(request.user)
        if ce is None:
            raise serializers.ValidationError(
                {
                    "detail": "Completa los datos de tu empresa (Mi cuenta) antes de pedir una reserva."
                }
            )
        # Siempre la empresa del perfil; un usuario no puede enviar otro client_id en el cuerpo.
        data["client"] = ce
        for row in data["items"]:
            sc = row["ad_space"].shopping_center
            if not shopping_center_allows_public_catalog(sc):
                raise serializers.ValidationError(
                    {"items": f"La toma {row['ad_space'].code} no está disponible en el marketplace público."}
                )
            if ce.workspace_id != sc.workspace_id:
                raise serializers.ValidationError(
                    {
                        "items": f"La toma {row['ad_space'].code} no pertenece al mismo owner que tu empresa."
                    }
                )

        for row in data["items"]:
            sc = row["ad_space"].shopping_center
            if ws is not None and sc.workspace_id != ws.id:
                raise serializers.ValidationError(
                    {"items": f"La toma {row['ad_space'].code} no pertenece al owner de este sitio."}
                )

        return data

    def create(self, validated_data):
        items_data = validated_data.pop("items")
        client = validated_data.pop("client")
        reservation_info = order_reservation_info_kwargs(validated_data, pop=True)
        order = Order.objects.create(
            client=client,
            status=OrderStatus.DRAFT,
            total_amount=Decimal("0"),
            **reservation_info,
        )
        total = Decimal("0")
        for row in items_data:
            OrderItem.objects.create(
                order=order,
                ad_space=row["ad_space"],
                start_date=row["start_date"],
                end_date=row["end_date"],
                monthly_price=row["_monthly_price"],
                subtotal=row["_subtotal"],
                original_subtotal=row["_subtotal"],
            )
            total += row["_subtotal"]
        order.total_amount = total.quantize(Decimal("0.01"))
        order.save(update_fields=["total_amount"])

        request = self.context.get("request")
        actor = request.user if request and request.user.is_authenticated else None
        log_order_status_transition(
            order,
            "",
            OrderStatus.DRAFT,
            actor=actor,
            note="Orden creada (borrador).",
        )
        return order


class OrderPaymentPlanMonthSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    month = serializers.IntegerField(min_value=1, max_value=12)


class OrderPaymentPlanInstallmentWriteSerializer(serializers.Serializer):
    months = OrderPaymentPlanMonthSerializer(many=True, allow_empty=False)


class OrderPaymentPlanUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    installments = OrderPaymentPlanInstallmentWriteSerializer(
        many=True, required=False, allow_null=True
    )

    def validate(self, attrs):
        if attrs.get("enabled") and not attrs.get("installments"):
            raise serializers.ValidationError(
                {"installments": "Indica al menos una cuota."}
            )
        return attrs

    def save(self, **kwargs):
        order = self.context["order"]
        from apps.orders.services.payment_plan_services import update_order_payment_plan

        return update_order_payment_plan(
            order,
            enabled=self.validated_data["enabled"],
            installments=self.validated_data.get("installments"),
            actor=self.context.get("actor"),
        )


class OrderPaymentInstallmentReceiptSerializer(serializers.Serializer):
    payment_receipt = serializers.FileField()

    def validate_payment_receipt(self, value):
        return validate_order_receipt_file(value)

    def save(self, **kwargs):
        installment = self.context["installment"]
        order = installment.plan.order
        if order.status not in (OrderStatus.INVOICED, OrderStatus.PAID):
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Solo puedes adjuntar comprobante cuando el pedido está "
                        "«Facturada» o «Pagada»."
                    )
                }
            )
        old = installment.payment_receipt if installment.payment_receipt else None
        installment.payment_receipt = self.validated_data["payment_receipt"]
        from apps.orders.services.payment_plan_services import sync_installment_status

        sync_installment_status(installment)
        installment.save(update_fields=["payment_receipt", "status", "updated_at"])
        if old and getattr(old, "name", None) != getattr(
            installment.payment_receipt, "name", None
        ):
            old.delete(save=False)
        req = self.context.get("request")
        aid = (
            req.user.pk
            if req and getattr(req, "user", None) is not None and req.user.is_authenticated
            else None
        )
        oid = order.pk

        def _enqueue() -> None:
            from apps.orders.tasks import schedule_send_order_client_activity_admin_emails

            schedule_send_order_client_activity_admin_emails(
                oid, "payment_receipt", actor_id=aid
            )

        transaction.on_commit(_enqueue)
        return installment
