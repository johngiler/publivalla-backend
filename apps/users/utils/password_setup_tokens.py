"""Token firmado para definir la primera contraseña (usuario creado sin clave)."""

from django.core import signing

USER_PASSWORD_SETUP_SALT = "publivalla-user-pw-setup-v1"


def build_user_password_setup_token(user_id: int) -> str:
    signer = signing.TimestampSigner(salt=USER_PASSWORD_SETUP_SALT)
    return signer.sign(str(user_id))


def parse_user_password_setup_token(token: str, *, max_age: int = 14 * 86400) -> int:
    signer = signing.TimestampSigner(salt=USER_PASSWORD_SETUP_SALT)
    value = signer.unsign(token, max_age=max_age)
    return int(value)
