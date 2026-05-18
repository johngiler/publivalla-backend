"""
Crea 10 proveedores de montaje de demostración en un centro comercial.

Los nombres de empresa siguen el patrón «DEMO Montaje 01» … «DEMO Montaje 10» para poder
localizarlos con ``--reset``.

Uso::

    python manage.py provider_demo_data
    python manage.py provider_demo_data --workspace-slug acme
    python manage.py provider_demo_data --shopping-center-id 1
    python manage.py provider_demo_data --shopping-center-slug scc
    python manage.py provider_demo_data --reset

Requisitos: workspace existente y al menos un centro comercial en ese workspace (si no pasas
``--shopping-center-id`` / ``--shopping-center-slug``, se usa el primero por ``listing_order``).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.malls.models import ShoppingCenter
from apps.providers.models import MountingProvider
from apps.workspaces.models import Workspace

SEED_TAG = "provider_demo_data"
COMPANY_PREFIX = "DEMO Montaje"

DEMO_ROWS = [
    {
        "suffix": "01",
        "contact_name": "María González",
        "phone": "+58 212 555-1001",
        "email": "demo.montaje01@example.invalid",
        "rif": "J-40100001-1",
    },
    {
        "suffix": "02",
        "contact_name": "Carlos Pérez",
        "phone": "+58 414 555-1002",
        "email": "demo.montaje02@example.invalid",
        "rif": "J-40100002-2",
    },
    {
        "suffix": "03",
        "contact_name": "Ana Rivas",
        "phone": "+58 424 555-1003",
        "email": "demo.montaje03@example.invalid",
        "rif": "J-40100003-3",
    },
    {
        "suffix": "04",
        "contact_name": "Luis Herrera",
        "phone": "+58 212 555-1004",
        "email": "demo.montaje04@example.invalid",
        "rif": "J-40100004-4",
    },
    {
        "suffix": "05",
        "contact_name": "Patricia Díaz",
        "phone": "+58 414 555-1005",
        "email": "demo.montaje05@example.invalid",
        "rif": "J-40100005-5",
    },
    {
        "suffix": "06",
        "contact_name": "Ricardo Mejías",
        "phone": "+58 424 555-1006",
        "email": "demo.montaje06@example.invalid",
        "rif": "J-40100006-6",
    },
    {
        "suffix": "07",
        "contact_name": "Daniela Oropeza",
        "phone": "+58 212 555-1007",
        "email": "demo.montaje07@example.invalid",
        "rif": "J-40100007-7",
    },
    {
        "suffix": "08",
        "contact_name": "Héctor Manrique",
        "phone": "+58 414 555-1008",
        "email": "demo.montaje08@example.invalid",
        "rif": "J-40100008-8",
    },
    {
        "suffix": "09",
        "contact_name": "Valentina Soto",
        "phone": "+58 424 555-1009",
        "email": "demo.montaje09@example.invalid",
        "rif": "J-40100009-9",
    },
    {
        "suffix": "10",
        "contact_name": "Andrés Villegas",
        "phone": "+58 212 555-1010",
        "email": "demo.montaje10@example.invalid",
        "rif": "J-40100010-0",
    },
]


def _resolve_center(ws: Workspace, center_id: int | None, center_slug: str | None) -> ShoppingCenter:
    qs = ShoppingCenter.objects.filter(workspace=ws)
    if center_id is not None:
        try:
            return qs.get(pk=center_id)
        except ShoppingCenter.DoesNotExist as e:
            raise CommandError(
                f"No existe el centro id={center_id} en el workspace «{ws.slug}»."
            ) from e
    if center_slug:
        slug = center_slug.strip()
        try:
            return qs.get(slug=slug)
        except ShoppingCenter.DoesNotExist as e:
            raise CommandError(
                f"No existe el centro slug={slug!r} en el workspace «{ws.slug}»."
            ) from e
    center = qs.order_by("listing_order", "id").first()
    if center is None:
        raise CommandError(
            f"El workspace «{ws.slug}» no tiene centros comerciales. Crea uno antes o indica "
            "--shopping-center-id / --shopping-center-slug."
        )
    return center


class Command(BaseCommand):
    help = "Crea 10 proveedores de montaje DEMO en un centro (idempotente por nombre)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace-slug",
            type=str,
            default="acme",
            help="Slug del workspace (default: acme).",
        )
        parser.add_argument(
            "--shopping-center-id",
            type=int,
            default=None,
            help="ID del centro donde crear los proveedores (opcional).",
        )
        parser.add_argument(
            "--shopping-center-slug",
            type=str,
            default=None,
            help="Slug del centro dentro del workspace (opcional).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=f"Elimina en el workspace los proveedores DEMO cuyo nombre empieza por «{COMPANY_PREFIX} ».",
        )

    def handle(self, *args, **options):
        slug = (options["workspace_slug"] or "").strip()
        if not slug:
            raise CommandError("Indica un --workspace-slug válido.")

        ws = Workspace.objects.filter(slug=slug).first()
        if ws is None:
            raise CommandError(f"No existe el workspace con slug «{slug}».")

        center = _resolve_center(
            ws,
            options.get("shopping_center_id"),
            (options.get("shopping_center_slug") or "").strip() or None,
        )

        with transaction.atomic():
            if options["reset"]:
                demo_qs = MountingProvider.objects.filter(
                    workspace=ws,
                    company_name__startswith=f"{COMPANY_PREFIX} ",
                )
                deleted = demo_qs.count()
                demo_qs.delete()
                self.stdout.write(
                    self.style.WARNING(
                        f"Eliminados {deleted} proveedor(es) DEMO del workspace «{ws.slug}»."
                    )
                )

            created_n = 0
            skipped_n = 0
            for i, row in enumerate(DEMO_ROWS):
                company_name = f"{COMPANY_PREFIX} {row['suffix']}"
                notes = (
                    f"Datos de demostración ({SEED_TAG}). "
                    "Puedes borrarlos con: python manage.py provider_demo_data --reset …"
                )
                provider, created = MountingProvider.objects.get_or_create(
                    workspace=ws,
                    company_name=company_name,
                    defaults={
                        "contact_name": row["contact_name"],
                        "phone": row["phone"],
                        "email": row["email"],
                        "rif": row["rif"],
                        "notes": notes,
                        "sort_order": i,
                        "is_active": True,
                    },
                )
                already_linked = provider.shopping_centers.filter(pk=center.pk).exists()
                if not already_linked:
                    provider.shopping_centers.add(center)
                if created:
                    created_n += 1
                    self.stdout.write(self.style.SUCCESS(f"Creado: {company_name}"))
                elif not already_linked:
                    created_n += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"Vinculado a {center.slug!r}: {company_name}")
                    )
                else:
                    skipped_n += 1
                    self.stdout.write(f"Ya existía (omitido): {company_name}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Centro: {center.name} (id={center.pk}, slug={center.slug!r}). "
                f"Creados: {created_n}, omitidos: {skipped_n}."
            )
        )
