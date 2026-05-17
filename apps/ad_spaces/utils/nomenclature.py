"""
Nomenclatura de códigos de toma: prefijo único + «-T» + número + sufijo de letras opcional.
El prefijo no tiene que coincidir con datos del centro comercial (cada toma tiene su propio código).
Ejemplos: SCC-T1, ACME-T2, MI-VALLA-T1A.
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError

_TOMA_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]*-T[0-9]+[A-Z]*$")


def normalize_toma_code(code: str) -> str:
    return (code or "").strip().upper()


def validate_toma_code(code: str) -> str:
    """
    Devuelve el código normalizado (mayúsculas) o lanza ValidationError.
    """
    normalized = normalize_toma_code(code)
    if not normalized:
        raise ValidationError("Indica el código de la toma.")
    if len(normalized) > 32:
        raise ValidationError("El código no puede superar 32 caracteres.")
    if not _TOMA_CODE_RE.fullmatch(normalized):
        raise ValidationError(
            "El código debe tener un prefijo (letras, números, guiones o guiones bajos), "
            "luego «-T», un número y, si aplica, letras finales (ej. SCC-T1, SLC-T1A)."
        )
    return normalized
