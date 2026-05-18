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
from apps.orders.services import default_invoice_number_for_order, log_order_status_transition
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
    order_item_code = serializers.CharField(
        source="order_item.ad_space.code", read_only=True, allow_null=True
    )
    order_item_title = serializers.CharField(
        source="order_item.ad_space.title", read_only=True, allow_null=True
    )

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


class OrderInstallationPermitSerializer(serializers.ModelSerializer):
    request_pdf_url = serializers.SerializerMethodField()

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
        )
        read_only_fields = fields

    def get_request_pdf_url(self, obj):
        f = obj.request_pdf
        if not f:
            return None
        return f.url


class OrderItemSerializer(serializers.ModelSerializer):
    ad_space_code = serializers.CharField(source="ad_space.code", read_only=True)
    ad_space_title = serializers.CharField(source="ad_space.title", read_only=True)
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
            "subtotal",
        )

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
    code = serializers.CharField(read_only=True)
    payment_method_label = serializers.SerializerMethodField()
    payment_receipt_url = serializers.SerializerMethodField()
    negotiation_sheet_pdf_url = serializers.SerializerMethodField()
    municipality_authorization_pdf_url = serializers.SerializerMethodField()
    invoice_pdf_url = serializers.SerializerMethodField()
    installation_permit_request_pdf_url = serializers.SerializerMethodField()
    negotiation_sheet_signed_url = serializers.SerializerMethodField()
    client_company_name = serializers.CharField(
        source="client.company_name", read_only=True
    )
    workspace_slug = serializers.CharField(
        source="client.workspace.slug", read_only=True
    )
    client_detail = OrderClientSnapshotSerializer(source="client", read_only=True)

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
            "total_amount",
            "submitted_at",
            "hold_expires_at",
            "created_at",
            "payment_method",
            "payment_method_label",
            "payment_receipt_url",
            "payment_conditions",
            "negotiation_observations",
            "invoice_number",
            "installation_verified_at",
            "negotiation_sheet_pdf_url",
            "municipality_authorization_pdf_url",
            "invoice_pdf_url",
            "installation_permit_request_pdf_url",
            "negotiation_sheet_signed_url",
            "items",
            "art_attachments",
            "installation_permit",
            "status_timeline",
        )
        read_only_fields = (
            "status",
            "status_label",
            "total_amount",
            "submitted_at",
            "hold_expires_at",
            "created_at",
            "payment_method",
            "payment_method_label",
            "payment_receipt_url",
            "payment_conditions",
            "negotiation_observations",
            "invoice_number",
            "installation_verified_at",
            "negotiation_sheet_pdf_url",
            "municipality_authorization_pdf_url",
            "invoice_pdf_url",
            "installation_permit_request_pdf_url",
            "negotiation_sheet_signed_url",
            "workspace_slug",
            "code",
        )

    def get_status_label(self, obj):
        return _status_label(obj.status)

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

    def get_installation_permit_request_pdf_url(self, obj):
        from django.core.exceptions import ObjectDoesNotExist

        try:
            p = obj.installation_permit
        except ObjectDoesNotExist:
            return None
        return self._file_url(p.request_pdf)

    def get_negotiation_sheet_signed_url(self, obj):
        return self._file_url(obj.negotiation_sheet_signed)

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


class OrderAdminPatchSerializer(serializers.ModelSerializer):
    """Administradores: estado, textos de negociación y referencia de factura."""

    class Meta:
        model = Order
        fields = (
            "status",
            "payment_conditions",
            "negotiation_observations",
            "invoice_number",
        )

    def validate(self, attrs):
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
            new_status == OrderStatus.PAID
            and self.instance.status != OrderStatus.PAID
            and self.instance.status == OrderStatus.INVOICED
            and not self.instance.payment_receipt
        ):
            raise serializers.ValidationError(
                {
                    "status": (
                        "El cliente debe adjuntar el comprobante de pago desde Mis pedidos antes "
                        "de pasar el pedido a «Pagada»."
                    )
                }
            )
        if (
            new_status == OrderStatus.ART_APPROVED
            and self.instance.status != OrderStatus.ART_APPROVED
            and self.instance.status == OrderStatus.PAID
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
            new_status == OrderStatus.PERMIT_PENDING
            and self.instance.status != OrderStatus.PERMIT_PENDING
            and self.instance.status == OrderStatus.ART_APPROVED
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
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        import logging

        from apps.orders.utils.document_generation import (
            generate_invoice_pdf_for_order,
            generate_negotiation_and_municipality_pdfs,
            regenerate_negotiation_sheet_pdf_for_order,
        )

        logger = logging.getLogger(__name__)
        old_pc = instance.payment_conditions
        old_no = instance.negotiation_observations
        old_inv = instance.invoice_number

        prev = instance.status
        new_status = validated_data.get("status", instance.status)
        if new_status == OrderStatus.INVOICED and prev != OrderStatus.INVOICED:
            inv = validated_data.get("invoice_number", instance.invoice_number)
            if inv is None:
                inv = ""
            else:
                inv = str(inv).strip()
            if not inv:
                validated_data["invoice_number"] = default_invoice_number_for_order(instance)
            else:
                validated_data["invoice_number"] = inv[:64]
        instance = super().update(instance, validated_data)
        if prev != instance.status:
            request = self.context.get("request")
            actor = request.user if request and request.user.is_authenticated else None
            log_order_status_transition(
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
            if (
                instance.status == OrderStatus.ACTIVE
                and prev == OrderStatus.INSTALLATION
            ):
                from django.utils import timezone as dj_tz

                Order.objects.filter(pk=instance.pk).update(
                    installation_verified_at=dj_tz.now()
                )
                instance.refresh_from_db(fields=["installation_verified_at"])
        elif prev == instance.status:
            ne_changed = (instance.payment_conditions or "") != (old_pc or "") or (
                instance.negotiation_observations or ""
            ) != (old_no or "")
            inv_changed = (str(instance.invoice_number or "").strip() != str(old_inv or "").strip())
            if ne_changed and bool(getattr(instance.negotiation_sheet_pdf, "name", "")):
                try:
                    regenerate_negotiation_sheet_pdf_for_order(instance)
                except Exception as exc:
                    logger.exception("Fallo al regenerar PDF de negociación: %s", exc)
                    raise serializers.ValidationError(
                        {
                            "detail": (
                                "No se pudo regenerar la hoja de negociación con los nuevos textos. "
                                "Revisa los datos e inténtalo de nuevo."
                            ),
                            "code": "negotiation_pdf_regen_failed",
                        }
                    ) from exc
                instance.refresh_from_db()
            if inv_changed and bool(getattr(instance.invoice_pdf, "name", "")):
                try:
                    generate_invoice_pdf_for_order(instance)
                except Exception as exc:
                    logger.exception("Fallo al regenerar factura PDF: %s", exc)
                    raise serializers.ValidationError(
                        {
                            "detail": (
                                "No se pudo regenerar el PDF de factura con el nuevo número. "
                                "Revisa los datos e inténtalo de nuevo."
                            ),
                            "code": "invoice_pdf_regen_failed",
                        }
                    ) from exc
                instance.refresh_from_db()

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
        if inst.status not in (OrderStatus.CLIENT_APPROVED, OrderStatus.INVOICED, OrderStatus.PAID):
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Solo puedes subir o actualizar la hoja firmada cuando el pedido está en "
                        "«Solicitud aprobada», «Facturada» o «Pagada» (por ejemplo, si el equipo actualizó el PDF de "
                        "negociación y necesitas firmar de nuevo)."
                    )
                }
            )
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
        for row in value:
            if not isinstance(row, dict):
                raise serializers.ValidationError("Cada miembro debe ser un objeto con nombre y cédula.")
            fn = (row.get("full_name") or "").strip()
            nid = (row.get("id_number") or "").strip()
            if not fn or not nid:
                raise serializers.ValidationError(
                    "Cada persona debe incluir full_name e id_number (cédula)."
                )
        return value


class OrderItemWriteSerializer(serializers.Serializer):
    """Solo espacio y fechas; precio y subtotal los fija el servidor."""

    ad_space = serializers.PrimaryKeyRelatedField(queryset=AdSpace.objects.all())
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, data):
        start = data["start_date"]
        end = data["end_date"]
        if end < start:
            raise serializers.ValidationError(
                {"end_date": "La fecha fin debe ser posterior o igual al inicio."}
            )
        if not contract_meets_min_months(start, end):
            m = MIN_RESERVATION_CALENDAR_MONTHS
            raise serializers.ValidationError(
                {
                    "end_date": (
                        f"El contrato debe cubrir al menos {m} "
                        f"{'mes' if m == 1 else 'meses'} de calendario."
                    )
                }
            )
        ad = data["ad_space"]
        if not ad_space_allows_marketplace_reservation(ad):
            raise serializers.ValidationError(
                {
                    "ad_space": (
                        f"La toma {ad.code} no admite nuevas reservas "
                        f"(estado: {ad.get_status_display()})."
                    )
                }
            )
        monthly = data["ad_space"].monthly_price_usd
        data["_monthly_price"] = monthly
        data["_subtotal"] = line_subtotal(monthly, start, end)
        return data


class OrderCreateSerializer(serializers.Serializer):
    client = serializers.PrimaryKeyRelatedField(
        queryset=Client.objects.all(),
        required=False,
        allow_null=True,
    )
    items = OrderItemWriteSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Agrega al menos una toma.")
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
        order = Order.objects.create(
            client=client,
            status=OrderStatus.DRAFT,
            total_amount=Decimal("0"),
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
