"""Caducidad y vigencia de bloqueos de disponibilidad (fechas ocupadas en calendario)."""

from __future__ import annotations

from django.utils import timezone

from apps.availability.models import AvailabilityBlock, AvailabilityBlockType


def _calendar_ref_date():
    return timezone.localdate()


def queryset_blocks_pending_expire(*, ad_space_id: int | None = None):
    """Bloqueos vigentes cuya fecha fin ya pasó (pendientes de caducar)."""
    ref = _calendar_ref_date()
    qs = AvailabilityBlock.objects.filter(
        is_active=True,
        end_date__lt=ref,
    ).exclude(type=AvailabilityBlockType.EXPIRED)
    if ad_space_id is not None:
        qs = qs.filter(ad_space_id=ad_space_id)
    return qs


def expire_availability_blocks(*, ad_space_id: int | None = None) -> int:
    """
    Marca como caducados los bloqueos cuya fecha fin ya pasó.
    No afectan catálogo ni reservas tras caducar.
    """
    return queryset_blocks_pending_expire(ad_space_id=ad_space_id).update(
        is_active=False,
        type=AvailabilityBlockType.EXPIRED,
    )


def calendar_blocking_availability_blocks(ad_space_id: int, *, ref=None):
    """Bloqueos que ocupan calendario: activos, tipo ocupado, fin ≥ hoy."""
    ref = ref if ref is not None else _calendar_ref_date()
    return AvailabilityBlock.objects.filter(
        ad_space_id=ad_space_id,
        is_active=True,
        type=AvailabilityBlockType.OCCUPIED,
        end_date__gte=ref,
    )


def ad_space_has_vigente_availability_block(ad_space_id: int, *, ref=None) -> bool:
    """Hay bloqueo de disponibilidad vigente (no caducado ni desactivado)."""
    return calendar_blocking_availability_blocks(ad_space_id, ref=ref).exists()


def normalize_block_type_on_save(
    *,
    is_active: bool,
    end_date,
    type_value: str | None = None,
) -> str:
    """Al guardar: solo «ocupado» (vigente) o «caducado»."""
    ref = _calendar_ref_date()
    if not is_active or (end_date is not None and end_date < ref):
        return AvailabilityBlockType.EXPIRED
    return AvailabilityBlockType.OCCUPIED
