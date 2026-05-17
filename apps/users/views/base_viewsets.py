from rest_framework import viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from apps.users.permissions import IsAdminRole


class AdminModelViewSet(viewsets.ModelViewSet):
    """CRUD restringido al rol administrador (panel)."""

    permission_classes = [IsAdminRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
