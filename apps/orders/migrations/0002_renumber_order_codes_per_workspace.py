# Corrección única: códigos #SLUG-ORDER-000001 por tenant (antes usaban pk global).

import re

from django.db import migrations

_ORDER_REF_PAD = 6


def _format_ref(sequence: int, workspace_slug: str) -> str:
    slug = (workspace_slug or "").strip().upper()
    slug = re.sub(r"[^A-Z0-9_-]", "", slug) or "OWNER"
    slug = slug[:32]
    n = max(0, int(sequence))
    return f"#{slug}-ORDER-{str(n).zfill(_ORDER_REF_PAD)}"


def renumber_order_codes_per_workspace(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Workspace = apps.get_model("workspaces", "Workspace")

    workspace_ids = list(
        Order.objects.filter(client__workspace_id__isnull=False)
        .values_list("client__workspace_id", flat=True)
        .distinct()
    )

    for workspace_id in workspace_ids:
        slug = (
            Workspace.objects.filter(pk=workspace_id).values_list("slug", flat=True).first()
            or ""
        )
        for index, order in enumerate(
            Order.objects.filter(client__workspace_id=workspace_id).order_by("pk").iterator(),
            start=1,
        ):
            ref = _format_ref(index, slug)
            if (order.code or "").strip() != ref:
                Order.objects.filter(pk=order.pk).update(code=ref)

    for index, order in enumerate(
        Order.objects.filter(client__workspace_id__isnull=True).order_by("pk").iterator(),
        start=1,
    ):
        ref = _format_ref(index, "")
        if (order.code or "").strip() != ref:
            Order.objects.filter(pk=order.pk).update(code=ref)


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0001_initial"),
        ("workspaces", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(renumber_order_codes_per_workspace, migrations.RunPython.noop),
    ]
