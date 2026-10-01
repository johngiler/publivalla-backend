"""WebSocket de la campanita. El token va en la query porque el navegador no manda Authorization."""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.orders.services.admin_notifications import admin_notify_group
from apps.users.utils import user_is_admin


class AdminNotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = await self._authorized_user()
        if user is None:
            await self.close(code=4401)
            return
        self.user = user
        self.group = admin_notify_group(user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def notification_created(self, event):
        await self.send_json(event.get("notification") or {})

    @database_sync_to_async
    def _authorized_user(self):
        from django.contrib.auth import get_user_model

        params = parse_qs((self.scope.get("query_string") or b"").decode())
        raw = (params.get("token") or [""])[0].strip()
        if not raw:
            return None
        try:
            token = AccessToken(raw)
            user_id = token.get("user_id")
        except TokenError:
            return None
        User = get_user_model()
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None or not user_is_admin(user):
            return None
        return user
