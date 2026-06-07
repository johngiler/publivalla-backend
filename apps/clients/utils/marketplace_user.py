"""Creación de usuario marketplace vinculado a una empresa (Client)."""

from __future__ import annotations

from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.db.models import Q

from apps.clients.models import Client, ClientBrand, ClientMemberBrand
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


def _normalize_member_email(email: str) -> str:
    return (email or "").strip().lower()


def _username_from_email(email: str) -> str:
    return email[: User._meta.get_field("username").max_length]


def validate_member_brand_ids(client: Client, brand_ids: list[int] | None) -> list[int]:
    """IDs únicos de marcas activas de la empresa; lista vacía si no se indica ninguna."""
    if not brand_ids:
        return []
    unique: list[int] = []
    seen: set[int] = set()
    for raw in brand_ids:
        bid = int(raw)
        if bid in seen:
            continue
        seen.add(bid)
        unique.append(bid)
    found = set(
        ClientBrand.objects.filter(
            client_id=client.pk,
            is_active=True,
            pk__in=unique,
        ).values_list("pk", flat=True)
    )
    if len(found) != len(unique):
        raise MarketplaceUserError(
            "invalid_brands",
            "Alguna marca indicada no pertenece a tu empresa.",
        )
    return unique


def set_member_brand_ids(profile: UserProfile, brand_ids: list[int] | None) -> None:
    if profile.role != UserProfile.Role.CLIENT or profile.client_id is None:
        raise MarketplaceUserError(
            "invalid_profile",
            "No se pudo actualizar las marcas del usuario.",
        )
    ids = validate_member_brand_ids(profile.client, brand_ids)
    ClientMemberBrand.objects.filter(profile=profile).exclude(brand_id__in=ids).delete()
    existing = set(
        ClientMemberBrand.objects.filter(profile=profile).values_list("brand_id", flat=True)
    )
    ClientMemberBrand.objects.bulk_create(
        [
            ClientMemberBrand(profile=profile, brand_id=bid)
            for bid in ids
            if bid not in existing
        ]
    )


def create_marketplace_member_user(
    client: Client,
    *,
    email: str,
    first_name: str = "",
    last_name: str = "",
    brand_ids: list[int] | None = None,
) -> User:
    """
    Crea un usuario cliente marketplace adicional para la misma empresa.
    Sin contraseña utilizable hasta activación por correo.
    """
    normalized = _normalize_member_email(email)
    if not normalized:
        raise MarketplaceUserError("missing_email", "Indica el correo del usuario.")
    if User.objects.filter(Q(username__iexact=normalized) | Q(email__iexact=normalized)).exists():
        raise MarketplaceUserError(
            "email_taken",
            "Ya existe un usuario con este correo.",
        )
    user = User(
        username=_username_from_email(normalized),
        email=normalized,
        first_name=(first_name or "").strip(),
        last_name=(last_name or "").strip(),
    )
    user.set_unusable_password()
    user.save()
    profile = user.profile
    profile.role = UserProfile.Role.CLIENT
    profile.client = client
    profile.workspace = client.workspace
    profile.full_clean()
    profile.save()
    set_member_brand_ids(profile, brand_ids)
    revoke_django_privileges(user)
    return user


def create_marketplace_user_for_client(client: Client) -> User:
    """
    Crea un usuario CLIENT sin contraseña utilizable, vinculado a la empresa.

    Misma lógica que POST ``/api/clients/{id}/generate-user/``.

    No envía correo aquí: el llamador decide la plantilla (p. ej. activación tras
    aprobar pedido vs. alta manual en clientes/usuarios).
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
