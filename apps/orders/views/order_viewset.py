import logging
import mimetypes
import os
import re

from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import FileResponse, HttpResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.ad_spaces.models import AdSpaceImage
from apps.providers.models import MountingProvider
from apps.providers.serializers import MountingProviderSerializer
from apps.orders.models import Order, OrderArtAttachment, OrderInstallationPermit, OrderItem, OrderStatus
from apps.orders.serializers import (
    ClientMountingProviderCreateSerializer,
    OrderAdminPatchSerializer,
    OrderClientNegotiationSignedSerializer,
    OrderClientPaymentPatchSerializer,
    OrderCreateSerializer,
    OrderInstallationPermitWriteSerializer,
    OrderSerializer,
)
from apps.orders.utils.pdf_documents import build_installation_permit_request_pdf_bytes
from apps.orders.services import log_order_status_transition, submit_draft_order
from apps.users.utils import get_marketplace_client, user_is_admin
from apps.workspaces.tenant import get_workspace_for_request

logger = logging.getLogger(__name__)


def _build_order_list_search_q(search: str) -> Q:
    """
    Búsqueda en listado de pedidos (admin y «Mis pedidos»): cliente, referencia del pedido,
    id numérico, código o título de espacio publicitario en las líneas.
    """
    raw = search.strip()
    code_compact = re.sub(r"\s+", "", raw)
    q = (
        Q(client__company_name__icontains=raw)
        | Q(code__icontains=raw)
        | Q(items__ad_space__title__icontains=raw)
        | Q(items__ad_space__code__icontains=raw)
    )
    if code_compact and code_compact != raw:
        q |= Q(items__ad_space__code__icontains=code_compact)
    norm = re.sub(r"\s+", "", raw).upper()
    if norm.isdigit():
        try:
            q |= Q(pk=int(norm))
        except (ValueError, OverflowError):
            pass
    m = re.search(r"-ORDER-(\d+)$", norm)
    if m:
        try:
            q |= Q(pk=int(m.group(1)))
        except (ValueError, OverflowError):
            pass
    return q


# Compat. con nombre anterior (autoreload puede dejar bytecode con la referencia vieja).
_build_order_admin_list_search_q = _build_order_list_search_q


# Estados entre envío y activación (no incluye borrador ni activa/vencida/cancel/rechazo).
_ORDER_PIPELINE_STATUSES = (
    OrderStatus.SUBMITTED,
    OrderStatus.CLIENT_APPROVED,
    OrderStatus.ART_APPROVED,
    OrderStatus.INVOICED,
    OrderStatus.PAID,
    OrderStatus.PERMIT_PENDING,
    OrderStatus.INSTALLATION,
)


def _client_orders_summary_for_list(*, client) -> dict:
    """
    Conteos globales del cliente para la cabecera de «Mis pedidos» (sin depender de filtros de página).

    Los borradores no entran: el cliente gestiona el carrito antes de enviar; «Mis pedidos» es pedidos ya enviados.
    """
    base = Order.objects.filter(client=client).exclude(status=OrderStatus.DRAFT)

    return {
        "order_counts": {
            "total": base.count(),
            "active": base.filter(status=OrderStatus.ACTIVE).count(),
            "expired": base.filter(status=OrderStatus.EXPIRED).count(),
            "pipeline": base.filter(status__in=_ORDER_PIPELINE_STATUSES).count(),
            "cancelled": base.filter(status=OrderStatus.CANCELLED).count(),
        },
    }


class OrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = (
            Order.objects.select_related("client", "client__workspace")
            .prefetch_related(
                Prefetch(
                    "items",
                    queryset=OrderItem.objects.select_related(
                        "ad_space__shopping_center",
                    ).prefetch_related(
                        Prefetch(
                            "ad_space__gallery_images",
                            queryset=AdSpaceImage.objects.order_by("sort_order", "id"),
                        ),
                    ),
                ),
                Prefetch(
                    "art_attachments",
                    queryset=OrderArtAttachment.objects.select_related(
                        "order_item__ad_space",
                    ).order_by("created_at", "id"),
                ),
                "status_events__actor",
            )
            .select_related("installation_permit")
            .all()
            .order_by("-created_at", "-id")
        )
        ws = get_workspace_for_request(self.request)
        if user_is_admin(self.request.user):
            if ws is not None:
                qs = qs.filter(client__workspace=ws)
            else:
                return qs.none()
        else:
            client = get_marketplace_client(self.request.user)
            if client is None:
                return qs.none()
            qs = qs.filter(client=client)
            # Solo el listado «Mis pedidos» oculta borradores; checkout debe poder POST …/submit/ sobre el borrador.
            if self.action == "list":
                qs = qs.exclude(status=OrderStatus.DRAFT)
        if self.action in ("list", "export_report"):
            st = self.request.query_params.get("status")
            if st and st != "all":
                qs = qs.filter(status=st)
            exclude_raw = self.request.query_params.get("exclude_status", "").strip()
            if exclude_raw:
                excluded = [s.strip() for s in exclude_raw.split(",") if s.strip()]
                if excluded:
                    qs = qs.exclude(status__in=excluded)
            search = self.request.query_params.get("search", "").strip()
            if search:
                qs = qs.filter(_build_order_list_search_q(search)).distinct()
        return qs

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        if self.action == "update":
            return OrderAdminPatchSerializer
        return OrderSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if response.status_code != status.HTTP_200_OK:
            return response
        if user_is_admin(request.user):
            return response
        client = get_marketplace_client(request.user)
        if client is None:
            return response
        payload = response.data
        if isinstance(payload, dict) and "results" in payload:
            payload["summary"] = _client_orders_summary_for_list(client=client)
        return response

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        return Response(
            OrderSerializer(order, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        ctx = self.get_serializer_context()
        if user_is_admin(request.user):
            ser = OrderAdminPatchSerializer(
                instance, data=request.data, partial=True, context=ctx
            )
        else:
            client = get_marketplace_client(request.user)
            if client is None or instance.client_id != client.pk:
                return Response(
                    {"detail": "No tienes permiso para modificar este pedido."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if request.query_params.get("scope") == "negotiation_signed":
                ser = OrderClientNegotiationSignedSerializer(
                    instance, data=request.data, partial=True, context=ctx
                )
            else:
                ser = OrderClientPaymentPatchSerializer(
                    instance, data=request.data, partial=True, context=ctx
                )
        ser.is_valid(raise_exception=True)
        ser.save()
        instance.refresh_from_db()
        return Response(OrderSerializer(instance, context=ctx).data)

    def update(self, request, *args, **kwargs):
        if not user_is_admin(request.user):
            return Response(
                {"detail": "No tienes permiso para esta acción."},
                status=status.HTTP_403_FORBIDDEN,
            )
        instance = self.get_object()
        ser = OrderAdminPatchSerializer(instance, data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        instance.refresh_from_db()
        return Response(
            OrderSerializer(instance, context=self.get_serializer_context()).data
        )

    def destroy(self, request, *args, **kwargs):
        if not user_is_admin(request.user):
            return Response(
                {"detail": "No tienes permiso para esta acción."},
                status=status.HTTP_403_FORBIDDEN,
            )
        instance = self.get_object()
        if instance.status != OrderStatus.DRAFT:
            return Response(
                {
                    "detail": "Solo se pueden eliminar pedidos en borrador.",
                    "code": "order_not_draft",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="export-report")
    def export_report(self, request):
        """
        Descarga .xlsx con pedidos y líneas (mismos filtros que el listado: búsqueda y estado).
        Solo administración del workspace.
        """
        if not user_is_admin(request.user):
            return Response(
                {"detail": "No tienes permiso para esta acción."},
                status=status.HTTP_403_FORBIDDEN,
            )
        qs = self.filter_queryset(self.get_queryset())
        from apps.orders.utils.excel_report import orders_report_excel_bytes

        payload = orders_report_excel_bytes(qs)
        filename = "reporte_pedidos.xlsx"
        resp = HttpResponse(
            payload,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        resp["Content-Length"] = str(len(payload))
        return resp

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        from rest_framework import serializers as drf_serializers

        order = self.get_object()
        try:
            submit_draft_order(
                order,
                actor=request.user if request.user.is_authenticated else None,
            )
        except drf_serializers.ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data)

    def _pdf_file_response(self, order, field: str, filename: str):
        f = getattr(order, field, None)
        if not f or not getattr(f, "name", ""):
            return Response(
                {"detail": "Este documento aún no está disponible."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            handle = f.open("rb")
        except FileNotFoundError:
            return Response(
                {"detail": "El archivo no está en el servidor."},
                status=status.HTTP_404_NOT_FOUND,
            )
        resp = FileResponse(handle, content_type="application/pdf", as_attachment=True, filename=filename)
        return resp

    def _ensure_order_access(self, request, order: Order) -> bool:
        if user_is_admin(request.user):
            return True
        client = get_marketplace_client(request.user)
        return client is not None and order.client_id == client.pk

    @action(detail=True, methods=["get"], url_path="download-negotiation-sheet")
    def download_negotiation_sheet(self, request, pk=None):
        order = self.get_object()
        if not self._ensure_order_access(request, order):
            return Response(
                {"detail": "No tienes permiso para descargar este documento."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ref = (order.code or str(order.pk)).replace("#", "").replace("/", "-")
        return self._pdf_file_response(order, "negotiation_sheet_pdf", f"hoja-negociacion-{ref}.pdf")

    @action(detail=True, methods=["get"], url_path="download-negotiation-sheet-signed")
    def download_negotiation_sheet_signed(self, request, pk=None):
        """Archivo subido por el cliente (PDF o imagen); sirve con JWT para vista previa en admin."""
        order = self.get_object()
        if not self._ensure_order_access(request, order):
            return Response(
                {"detail": "No tienes permiso para descargar este documento."},
                status=status.HTTP_403_FORBIDDEN,
            )
        f = order.negotiation_sheet_signed
        if not f or not getattr(f, "name", ""):
            return Response(
                {"detail": "La empresa aún no ha subido la hoja firmada."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            handle = f.open("rb")
        except FileNotFoundError:
            return Response(
                {"detail": "El archivo no está en el servidor."},
                status=status.HTTP_404_NOT_FOUND,
            )
        ref = (order.code or str(order.pk)).replace("#", "").replace("/", "-")
        basename = os.path.basename(f.name) or f"hoja-firmada-{ref}"
        ctype, _ = mimetypes.guess_type(f.name)
        if not ctype:
            ctype = "application/octet-stream"
        return FileResponse(
            handle,
            content_type=ctype,
            as_attachment=True,
            filename=basename,
        )

    @action(detail=True, methods=["get"], url_path="download-municipality-letter")
    def download_municipality_letter(self, request, pk=None):
        order = self.get_object()
        if not self._ensure_order_access(request, order):
            return Response(
                {"detail": "No tienes permiso para descargar este documento."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ref = (order.code or str(order.pk)).replace("#", "").replace("/", "-")
        return self._pdf_file_response(order, "municipality_authorization_pdf", f"carta-municipio-{ref}.pdf")

    @action(detail=True, methods=["get"], url_path="download-invoice")
    def download_invoice(self, request, pk=None):
        order = self.get_object()
        if not self._ensure_order_access(request, order):
            return Response(
                {"detail": "No tienes permiso para descargar este documento."},
                status=status.HTTP_403_FORBIDDEN,
            )
        ref = (order.code or str(order.pk)).replace("#", "").replace("/", "-")
        return self._pdf_file_response(order, "invoice_pdf", f"factura-{ref}.pdf")

    @action(detail=True, methods=["get"], url_path="download-installation-permit-request")
    def download_installation_permit_request(self, request, pk=None):
        order = self.get_object()
        if not self._ensure_order_access(request, order):
            return Response(
                {"detail": "No tienes permiso para descargar este documento."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            p = order.installation_permit
        except ObjectDoesNotExist:
            return Response(
                {"detail": "No hay solicitud de permiso de instalación para este pedido."},
                status=status.HTTP_404_NOT_FOUND,
            )
        f = p.request_pdf
        if not f or not getattr(f, "name", ""):
            return Response(
                {"detail": "El PDF de la solicitud aún no está disponible."},
                status=status.HTTP_404_NOT_FOUND,
            )
        ref = (order.code or str(order.pk)).replace("#", "").replace("/", "-")
        try:
            handle = f.open("rb")
        except FileNotFoundError:
            return Response(
                {"detail": "El archivo no está en el servidor."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return FileResponse(
            handle,
            content_type="application/pdf",
            as_attachment=True,
            filename=f"solicitud-permiso-instalacion-{ref}.pdf",
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="upload-art",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_art(self, request, pk=None):
        from rest_framework import serializers as drf_serializers

        from apps.orders.serializers import validate_order_receipt_file

        order = self.get_object()
        if user_is_admin(request.user):
            return Response(
                {"detail": "Los artes los sube la empresa desde su cuenta."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None or order.client_id != client.pk:
            return Response(
                {"detail": "Solo la cuenta de la empresa dueña puede subir artes."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if order.status != OrderStatus.PAID:
            return Response(
                {
                    "detail": "Solo puedes subir artes cuando el pedido está «Pagada».",
                    "code": "order_not_paid_for_art",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        f = request.FILES.get("file")
        if not f:
            return Response({"detail": "Adjunta un archivo en el campo «file»."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_order_receipt_file(f)
        except drf_serializers.ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        items = list(order.items.select_related("ad_space").order_by("id"))
        if not items:
            return Response(
                {"detail": "El pedido no tiene líneas; no se pueden adjuntar artes."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw_item = (request.POST.get("order_item") or "").strip()
        chosen = None
        if len(items) == 1:
            chosen = items[0]
            if raw_item:
                try:
                    want_id = int(raw_item)
                except (TypeError, ValueError):
                    return Response(
                        {"detail": "El identificador de línea (order_item) no es válido."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if want_id != chosen.pk:
                    return Response(
                        {"detail": "La línea indicada no corresponde a este pedido."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        else:
            if not raw_item:
                return Response(
                    {
                        "detail": "Este pedido tiene varias tomas. Indica la línea en el campo «order_item» (id de la línea).",
                        "code": "order_item_required_for_art",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                want_id = int(raw_item)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "El identificador de línea (order_item) no es válido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            chosen = next((it for it in items if it.pk == want_id), None)
            if chosen is None:
                return Response(
                    {"detail": "La línea no pertenece a este pedido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        OrderArtAttachment.objects.create(order=order, order_item=chosen, file=f)
        oid = order.pk
        aid = (
            request.user.pk
            if request.user.is_authenticated
            else None
        )

        def _enqueue_art_notice() -> None:
            from apps.orders.tasks import schedule_send_order_client_activity_admin_emails

            schedule_send_order_client_activity_admin_emails(
                oid, "art_upload", actor_id=aid
            )

        transaction.on_commit(_enqueue_art_notice)
        # Nueva consulta: el `order` de get_object() puede tener prefetch de
        # art_attachments cacheado vacío; el serializador debe listar el archivo nuevo.
        order = self.get_queryset().get(pk=order.pk)
        ctx = self.get_serializer_context()
        return Response(
            OrderSerializer(order, context=ctx).data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"art-attachments/(?P<attachment_id>[0-9]+)",
    )
    def delete_art_attachment(self, request, pk=None, attachment_id=None):
        order = self.get_object()
        if user_is_admin(request.user):
            return Response(
                {"detail": "Los artes los gestiona la empresa desde su cuenta."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None or order.client_id != client.pk:
            return Response(
                {"detail": "Solo la cuenta de la empresa dueña puede eliminar artes."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if order.status != OrderStatus.PAID:
            return Response(
                {
                    "detail": "Solo puedes eliminar artes cuando el pedido está «Pagada».",
                    "code": "order_not_paid_for_art_delete",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            aid = int(attachment_id)
        except (TypeError, ValueError):
            return Response({"detail": "Identificador inválido."}, status=status.HTTP_400_BAD_REQUEST)
        att = OrderArtAttachment.objects.filter(pk=aid, order_id=order.pk).first()
        if not att:
            return Response(
                {"detail": "No se encontró el archivo adjunto."},
                status=status.HTTP_404_NOT_FOUND,
            )
        att.delete()
        order = self.get_queryset().get(pk=order.pk)
        ctx = self.get_serializer_context()
        return Response(OrderSerializer(order, context=ctx).data)

    @action(detail=True, methods=["get", "post"], url_path="mounting-providers")
    def order_mounting_providers(self, request, pk=None):
        """
        Lista proveedores de montaje activos de los centros que aparecen en las líneas del pedido.
        POST: el cliente registra un proveedor nuevo en uno de esos centros (misma validación que en admin).
        """
        order = self.get_object()
        if not self._ensure_order_access(request, order):
            return Response(
                {"detail": "No tienes permiso para este pedido."},
                status=status.HTTP_403_FORBIDDEN,
            )

        center_ids = list(
            OrderItem.objects.filter(order_id=order.pk)
            .values_list("ad_space__shopping_center_id", flat=True)
            .distinct()
        )
        center_ids = [cid for cid in center_ids if cid is not None]

        if request.method == "GET":
            if not center_ids:
                return Response([])
            qs = (
                MountingProvider.objects.filter(
                    shopping_centers__in=center_ids,
                    is_active=True,
                )
                .prefetch_related("shopping_centers")
                .order_by("sort_order", "id")
                .distinct()
            )
            data = MountingProviderSerializer(
                qs, many=True, context=self.get_serializer_context()
            ).data
            return Response(data)

        if user_is_admin(request.user):
            return Response(
                {
                    "detail": "Para crear proveedores de montaje usa el panel de administración "
                    "(Proveedores de montaje)."
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None or order.client_id != client.pk:
            return Response(
                {"detail": "Solo la cuenta de la empresa dueña puede registrar proveedores desde el pedido."},
                status=status.HTTP_403_FORBIDDEN,
            )

        ser = ClientMountingProviderCreateSerializer(
            data=request.data,
            context={"order": order, "request": request},
        )
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        center = vd["shopping_center"]
        existing = vd.get("_existing_provider")
        if existing is not None:
            existing.shopping_centers.add(center)
            created = existing
        else:
            created = MountingProvider.objects.create(
                workspace_id=center.workspace_id,
                company_name=vd["company_name"],
                sort_order=0,
            )
            created.shopping_centers.add(center)
        out = MountingProviderSerializer(
            created, context=self.get_serializer_context()
        ).data
        return Response(out, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="installation-permit")
    def installation_permit_submit(self, request, pk=None):
        order = self.get_object()
        if user_is_admin(request.user):
            return Response(
                {"detail": "Este envío lo realiza la empresa."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client = get_marketplace_client(request.user)
        if client is None or order.client_id != client.pk:
            return Response(
                {"detail": "No tienes permiso para este pedido."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if order.status != OrderStatus.ART_APPROVED:
            return Response(
                {
                    "detail": "Solo puedes enviar la solicitud de permiso cuando el pedido está «Arte aprobado».",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if OrderInstallationPermit.objects.filter(order_id=order.pk).exists():
            return Response(
                {"detail": "Ya existe una solicitud de permiso para este pedido."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = OrderInstallationPermitWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        perm = OrderInstallationPermit.objects.create(
            order=order,
            mounting_date=data["mounting_date"],
            installation_company_name=data["installation_company_name"],
            staff_members=data["staff_members"],
            notes=data.get("notes") or "",
            municipal_reference=data.get("municipal_reference") or "",
        )
        try:
            pdf_bytes = build_installation_permit_request_pdf_bytes(order=order, permit=perm)
            perm.request_pdf.save(
                f"solicitud_permiso_instalacion_{order.pk}.pdf",
                ContentFile(pdf_bytes),
                save=True,
            )
        except Exception as exc:
            logger.exception(
                "PDF solicitud permiso instalación pedido %s: %s",
                order.pk,
                exc,
            )
        prev = order.status
        order.status = OrderStatus.PERMIT_PENDING
        order.save(update_fields=["status", "updated_at"])
        log_order_status_transition(
            order,
            prev,
            order.status,
            actor=request.user if request.user.is_authenticated else None,
            note="Cliente envió datos de solicitud de permiso de instalación.",
        )
        order.refresh_from_db()
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data)
