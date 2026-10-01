from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import AdminNotification
from apps.orders.services.admin_notifications import serialize_admin_notification
from apps.users.permissions import IsAdminRole


class AdminNotificationListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        qs = AdminNotification.objects.filter(recipient=request.user)
        unread_count = qs.filter(read_at__isnull=True).count()
        rows = qs.order_by("-created_at", "-id")[:40]
        return Response(
            {
                "unread_count": unread_count,
                "results": [serialize_admin_notification(row) for row in rows],
            }
        )


class AdminNotificationReadView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        qs = AdminNotification.objects.filter(
            recipient=request.user,
            read_at__isnull=True,
        )
        if request.data.get("all") is True:
            updated = qs.update(read_at=timezone.now())
            return Response({"updated": updated})
        raw_id = request.data.get("id")
        try:
            note_id = int(raw_id)
        except (TypeError, ValueError):
            return Response({"detail": "Indica el aviso."}, status=400)
        updated = qs.filter(pk=note_id).update(read_at=timezone.now())
        return Response({"updated": updated})
