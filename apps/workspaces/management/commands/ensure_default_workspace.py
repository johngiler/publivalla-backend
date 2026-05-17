"""
Crea o completa el workspace placeholder (por defecto ``acme``) tras una instalación vacía.

Uso::

    python manage.py migrate
    python manage.py ensure_default_workspace
    python manage.py ensure_default_workspace --slug acme
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.workspaces.services.default_workspace import (
    ensure_default_workspace,
    expected_placeholder_slug,
    resolve_placeholder_slug,
)


class Command(BaseCommand):
    help = (
        "Asegura que exista el workspace placeholder (DEFAULT_WORKSPACE_SLUG, p. ej. acme) "
        "con branding mínimo para desarrollo e instalación desde cero."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug",
            default="",
            help="Slug del workspace (por defecto: DEFAULT_WORKSPACE_SLUG o acme).",
        )
        parser.add_argument(
            "--no-fill-missing",
            action="store_true",
            help="Si el workspace ya existe, no rellenar campos de texto vacíos.",
        )

    def handle(self, *args, **options):
        slug = resolve_placeholder_slug(options.get("slug") or None)
        fill_missing = not bool(options.get("no_fill_missing"))

        ws, created = ensure_default_workspace(slug, fill_missing=fill_missing)

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Workspace creado: slug="{ws.slug}", name="{ws.name}".'
                )
            )
        else:
            self.stdout.write(
                f'Workspace ya existía: slug="{ws.slug}", name="{ws.name}".'
            )
            if fill_missing:
                self.stdout.write("Campos vacíos completados con valores placeholder.")

        configured = expected_placeholder_slug()
        if slug != configured:
            self.stdout.write(
                self.style.WARNING(
                    f'Nota: DEFAULT_WORKSPACE_SLUG en settings es "{configured}".'
                )
            )
