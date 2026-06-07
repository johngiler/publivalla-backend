"""Token firmado para restablecer contraseña (usuario con clave ya definida)."""

from django.core import signing

USER_PASSWORD_RESET_SALT = "publivalla-user-pw-reset-v1"
DEFAULT_PASSWORD_RESET_MAX_AGE = 24 * 3600


def build_user_password_reset_token(user_id: int) -> str:
    signer = signing.TimestampSigner(salt=USER_PASSWORD_RESET_SALT)
    return signer.sign(str(user_id))


def parse_user_password_reset_token(
    token: str,
    *,
    max_age: int = DEFAULT_PASSWORD_RESET_MAX_AGE,
) -> int:
    signer = signing.TimestampSigner(salt=USER_PASSWORD_RESET_SALT)
    value = signer.unsign(token, max_age=max_age)
    return int(value)
