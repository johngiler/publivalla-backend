"""Reglas y mensajes de contraseña alineados con AUTH_PASSWORD_VALIDATORS (UI en español)."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError


def translate_password_validation_messages(messages: list[str]) -> list[str]:
    """Mensajes por defecto de Django a español neutro para el marketplace."""
    out: list[str] = []
    for msg in messages:
        m = (msg or "").strip()
        if m == "This password is too common.":
            out.append("Esta contraseña es demasiado común; elige una menos obvia.")
        elif m == "This password is entirely numeric.":
            out.append("La contraseña no puede ser solo números.")
        elif m.startswith("This password is too short."):
            out.append("La contraseña es demasiado corta para lo que exige el sistema.")
        elif "too similar" in m.lower():
            out.append("La contraseña es demasiado parecida a datos personales; elige otra.")
        else:
            out.append(m)
    return out


def marketplace_password_policy_errors(password: str) -> list[str] | None:
    """
    None si pasa las reglas de AUTH_PASSWORD_VALIDATORS.
    Lista de strings en español si no.
    """
    if len(password) < 8:
        return ["La contraseña debe tener al menos 8 caracteres."]
    try:
        validate_password(password)
    except DjangoValidationError as e:
        return translate_password_validation_messages(list(e.messages))
    return None
