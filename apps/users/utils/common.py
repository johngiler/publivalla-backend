from apps.users.models import UserProfile


def is_platform_staff(user) -> bool:
    """
    Operación Publivalla (Django admin): is_staff o is_superuser.
    No usan JWT del marketplace ni el panel del frontend.
    """
    return bool(
        user
        and user.is_authenticated
        and (getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))
    )


def get_user_profile(user):
    """
    Perfil de marketplace. None para staff/superuser o si no existe la fila UserProfile.
    """
    if not user or not user.is_authenticated or is_platform_staff(user):
        return None
    try:
        return user.profile
    except UserProfile.DoesNotExist:
        return None


def get_marketplace_client(user):
    """
    Empresa (Client) asociada al usuario vía UserProfile.client (como mucho una por usuario).
    Solo aplica a usuarios con rol cliente marketplace. Los borradores y envíos de pedido usan
    siempre este cliente, no hay selección entre varias empresas por usuario.
    """
    if not user or not user.is_authenticated or is_platform_staff(user):
        return None
    p = get_user_profile(user)
    if not p or p.role != UserProfile.Role.CLIENT:
        return None
    return p.client


def get_user_role(user) -> str | None:
    """
    Rol para JWT y `/api/auth/me/`.
    Staff de plataforma devuelve 'staff' (no debe obtener token; defensa en capas).
    """
    if not user or not user.is_authenticated:
        return None
    if is_platform_staff(user):
        return "staff"
    profile = get_user_profile(user)
    if profile is None:
        return UserProfile.Role.CLIENT
    return profile.role


def user_is_admin(user) -> bool:
    """Administrador de un owner (panel frontend). Excluye staff de Django."""
    if not user or not user.is_authenticated or is_platform_staff(user):
        return False
    profile = get_user_profile(user)
    return profile is not None and profile.role == UserProfile.Role.ADMIN
