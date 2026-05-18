# Migra auditoría de catálogo SCC/SLC (Sambil) a campos genéricos por tenant.

from __future__ import annotations

from django.db import migrations, models


def _forward(apps, schema_editor):
    Workspace = apps.get_model("workspaces", "Workspace")
    for ws in Workspace.objects.all().iterator():
        centers: dict[str, str] = {}
        scc = getattr(ws, "catalog_scc_seeded_at", None)
        slc = getattr(ws, "catalog_slc_seeded_at", None)
        if scc:
            centers["scc"] = scc.isoformat()
        if slc:
            centers["slc"] = slc.isoformat()
        if not centers:
            continue
        last = max(scc, slc) if scc and slc else (scc or slc)
        Workspace.objects.filter(pk=ws.pk).update(
            catalog_seeded_at=last,
            catalog_seeded_centers=centers,
        )


def _backward(apps, schema_editor):
    Workspace = apps.get_model("workspaces", "Workspace")
    for ws in Workspace.objects.all().iterator():
        centers = getattr(ws, "catalog_seeded_centers", None) or {}
        if not isinstance(centers, dict):
            continue
        from django.utils.dateparse import parse_datetime

        updates: dict = {}
        if "scc" in centers:
            dt = parse_datetime(str(centers["scc"]))
            if dt:
                updates["catalog_scc_seeded_at"] = dt
        if "slc" in centers:
            dt = parse_datetime(str(centers["slc"]))
            if dt:
                updates["catalog_slc_seeded_at"] = dt
        if updates:
            Workspace.objects.filter(pk=ws.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="catalog_seeded_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="Última importación de catálogo con seed_production_catalog en este workspace.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="workspace",
            name="catalog_seeded_centers",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Mapa slug de centro → fecha ISO de la última carga (p. ej. {"demo": "2026-05-18T12:00:00+00:00"}).',
            ),
        ),
        migrations.RunPython(_forward, _backward),
        migrations.RemoveField(
            model_name="workspace",
            name="catalog_scc_seeded_at",
        ),
        migrations.RemoveField(
            model_name="workspace",
            name="catalog_slc_seeded_at",
        ),
    ]
