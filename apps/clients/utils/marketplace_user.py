"""Creación de usuario marketplace vinculado a una empresa (Client)."""

from __future__ import annotations

from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.clients.models import Client
from apps.users.models import UserProfile
from apps.users.serializers import revoke_django_privileges
from apps.users.utils.password_setup_tokens import build_user_password_setup_token
from apps.workspaces.tenant import spa_public_base_url

User = get_user_model()


def client_has_marketplace_user(client: Client) -> bool:
    return UserProfile.objects.filter(
        client=client,
        role=UserProfile.Role.CLIENT,
    ).exists()


class MarketplaceUserError(Exception):
    """Fallo al crear usuario marketplace para un cliente."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def create_marketplace_user_for_client(client: Client) -> User:
    """
    Crea un usuario CLIENT sin contraseña utilizable, vinculado a la empresa.

    Misma lógica que POST ``/api/clients/{id}/generate-user/``.
    """
    if client_has_marketplace_user(client):
        raise MarketplaceUserError(
            "already_linked",
            "Esta empresa ya tiene al menos un usuario vinculado.",
        )
    email = (client.email or "").strip().lower()
    if not email:
        raise MarketplaceUserError(
            "missing_email",
            "La empresa no tiene correo.",
        )
    if User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists():
        raise MarketplaceUserError(
            "email_taken",
            "Ya existe un usuario con este correo.",
        )
    username = email[: User._meta.get_field("username").max_length]
    user = User(username=username, email=email)
    user.set_unusable_password()
    user.save()
    profile = user.profile
    profile.role = UserProfile.Role.CLIENT
    profile.client = client
    profile.workspace = client.workspace
    profile.full_clean()
    profile.save()
    revoke_django_privileges(user)
    return user


def build_client_registration_link_parts(
    *, client: Client, user: User
) -> tuple[str, str, str]:
    """
    Devuelve ``(email, token, registration_query)`` para ``/registro?{registration_query}``.
    """
    email = (user.email or user.username or client.email or "").strip().lower()
    token = build_user_password_setup_token(user.pk)
    registration_query = (
        f"token={quote(token, safe='')}&email={quote(email, safe='')}"
    )
    return email, token, registration_query


def build_client_password_setup_url(*, client: Client, user: User) -> str:
    """Enlace público ``/registro?token=…&email=…`` para definir la primera contraseña."""
    ws = getattr(client, "workspace", None)
    _, _, q = build_client_registration_link_parts(client=client, user=user)
    return f"{spa_public_base_url(ws)}/registro?{q}"
