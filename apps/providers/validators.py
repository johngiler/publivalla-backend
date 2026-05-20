"""Validación de personal en sitio para proveedores de montaje."""

from __future__ import annotations

from rest_framework import serializers


def normalize_staff_members(value) -> list[dict[str, str]]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise serializers.ValidationError(
            "El personal en sitio debe ser una lista de personas."
        )
    if not value:
        raise serializers.ValidationError(
            "Indica al menos una persona del personal en sitio (nombre y cédula)."
        )
    out: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            raise serializers.ValidationError(
                "Cada persona debe incluir nombre y cédula."
            )
        fn = (row.get("full_name") or "").strip()
        nid = (row.get("id_number") or "").strip()
        if not fn or not nid:
            raise serializers.ValidationError(
                "Cada persona debe incluir nombre completo y cédula."
            )
        out.append({"full_name": fn, "id_number": nid})
    return out
