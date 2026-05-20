"""Validación compartida de datos de empresa cliente."""

from __future__ import annotations

from rest_framework import serializers


def normalize_client_rif_required(value) -> str:
    """RIF obligatorio al registrar o completar ficha de empresa."""
    s = (value or "").strip() if value is not None else ""
    if not s:
        raise serializers.ValidationError("Indica el RIF de la empresa.")
    if len(s) > 32:
        raise serializers.ValidationError("El RIF no puede superar 32 caracteres.")
    return s


def _require_non_blank(value, *, message: str, max_length: int) -> str:
    s = (value or "").strip() if value is not None else ""
    if not s:
        raise serializers.ValidationError(message)
    if len(s) > max_length:
        raise serializers.ValidationError(
            f"El texto no puede superar {max_length} caracteres."
        )
    return s


def normalize_representative_name(value) -> str:
    return _require_non_blank(
        value,
        message="Indica el nombre del representante legal.",
        max_length=255,
    )


def normalize_representative_id_number(value) -> str:
    return _require_non_blank(
        value,
        message="Indica la cédula del representante legal.",
        max_length=32,
    )


def normalize_client_representative_fields(
    *,
    representative_name,
    representative_id_number,
) -> tuple[str, str]:
    return (
        normalize_representative_name(representative_name),
        normalize_representative_id_number(representative_id_number),
    )


def client_has_representative_fields(client) -> bool:
    """True si la ficha tiene representante legal completo."""
    if client is None:
        return False
    try:
        normalize_client_representative_fields(
            representative_name=getattr(client, "representative_name", None),
            representative_id_number=getattr(
                client, "representative_id_number", None
            ),
        )
    except serializers.ValidationError:
        return False
    return True
