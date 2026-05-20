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
