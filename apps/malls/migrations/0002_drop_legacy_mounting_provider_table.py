# Migra datos de la tabla legacy (modelo en malls 0001 antiguo) hacia providers.MountingProvider.

from __future__ import annotations

from django.db import migrations


def _migrate_legacy_mounting_providers(apps, schema_editor):
    connection = schema_editor.connection
    tables = connection.introspection.table_names()
    legacy = "malls_shoppingcentermountingprovider"
    if legacy not in tables:
        return

    MountingProvider = apps.get_model("providers", "MountingProvider")
    ShoppingCenter = apps.get_model("malls", "ShoppingCenter")

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT shopping_center_id, company_name, contact_name, phone, email, rif,
                   notes, sort_order, is_active, created_at, updated_at
            FROM {legacy}
            ORDER BY id
            """
        )
        rows = cursor.fetchall()

    for row in rows:
        (
            center_id,
            company_name,
            contact_name,
            phone,
            email,
            rif,
            notes,
            sort_order,
            is_active,
            created_at,
            updated_at,
        ) = row
        try:
            center = ShoppingCenter.objects.select_related("workspace").get(pk=center_id)
        except ShoppingCenter.DoesNotExist:
            continue
        provider, _created = MountingProvider.objects.get_or_create(
            workspace_id=center.workspace_id,
            company_name=company_name,
            defaults={
                "contact_name": contact_name or "",
                "phone": phone or "",
                "email": email or "",
                "rif": rif or "",
                "notes": notes or "",
                "sort_order": sort_order or 0,
                "is_active": bool(is_active),
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )
        if not provider.shopping_centers.filter(pk=center_id).exists():
            provider.shopping_centers.add(center_id)


class Migration(migrations.Migration):

    dependencies = [
        ("malls", "0001_initial"),
        ("providers", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_migrate_legacy_mounting_providers, migrations.RunPython.noop),
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS malls_shoppingcentermountingprovider CASCADE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
