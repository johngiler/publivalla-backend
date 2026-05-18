"""Tareas batch de bloqueos de disponibilidad (cron)."""

from __future__ import annotations

from apps.ad_spaces.utils.marketplace_availability import sync_ad_space_commercial_status
from apps.availability.services.availability_block_services import (
    expire_availability_blocks,
    queryset_blocks_pending_expire,
)


def run_expire_availability_blocks_job(*, dry_run: bool = False) -> dict:
    """
    Caduca bloqueos con end_date anterior a hoy y recalcula estado comercial de las tomas.
    """
    qs = queryset_blocks_pending_expire()
    ad_space_ids = list(qs.values_list("ad_space_id", flat=True).distinct())
    pending = qs.count()

    if dry_run:
        return {
            "would_expire": pending,
            "ad_space_ids": ad_space_ids,
        }

    expired = expire_availability_blocks()
    for ad_space_id in ad_space_ids:
        sync_ad_space_commercial_status(ad_space_id, force_calendar=True)

    return {
        "expired": expired,
        "spaces_synced": len(ad_space_ids),
        "ad_space_ids": ad_space_ids,
    }
