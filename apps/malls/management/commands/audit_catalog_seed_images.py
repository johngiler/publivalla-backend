"""
Lista tomas del PDF sin imágenes asociadas (antes o después del seed).

Ejemplo::

    python manage.py audit_catalog_seed_images \\
        --workspace-slug sambil \\
        --pdf /home/git/malls/Sambil\\ Valencia\\ .pdf \\
        --images-dir "/home/git/malls/Sambil Valencia"
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.malls.management.commands.seed_production_catalog import _filter_seed_image_paths
from apps.malls.utils.catalog_pdf_parser import parse_catalog_pdf_to_json_bundle
from apps.malls.utils.catalog_seed_images import collect_images_for_code, load_images_map
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Audita qué códigos de toma del PDF no tienen imágenes en --images-dir."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-slug", type=str, required=True)
        parser.add_argument("--pdf", type=str, required=True)
        parser.add_argument("--images-dir", type=str, required=True)
        parser.add_argument(
            "--center-slug",
            type=str,
            default="",
            help="Opcional: mismo slug que usarás en seed_production_catalog.",
        )
        parser.add_argument(
            "--code-prefix",
            type=str,
            default="",
            help="Opcional: mismo prefijo que usarás en seed.",
        )
        parser.add_argument(
            "--center-name",
            type=str,
            default="",
            help="Nombre visible del centro (obligatorio si el PDF se llama catalog.pdf y no trae marca en el texto).",
        )

    def handle(self, *args, **options):
        slug = (options["workspace_slug"] or "").strip()
        ws = Workspace.objects.filter(slug=slug, is_active=True).first()
        if ws is None:
            raise CommandError(f"No existe workspace activo «{slug}».")

        pdf_path = Path(options["pdf"]).expanduser().resolve()
        if not pdf_path.is_file():
            raise CommandError(f"No existe el PDF: {pdf_path}")

        images_dir = Path(options["images_dir"]).expanduser().resolve()
        if not images_dir.is_dir():
            raise CommandError(f"No existe el directorio: {images_dir}")

        parsed = parse_catalog_pdf_to_json_bundle(
            pdf_path,
            workspace_slug=ws.slug,
            workspace_name=ws.name,
        )
        center_slug = (options.get("center_slug") or "").strip()
        if center_slug:
            parsed.center["slug"] = center_slug
        center_name = (options.get("center_name") or "").strip()
        if center_name:
            parsed.center["name"] = center_name
        code_prefix = (options.get("code_prefix") or "").strip().upper()
        if code_prefix:
            parsed.center["code_prefix"] = code_prefix

        from apps.malls.management.commands.seed_production_catalog import (
            _code_prefix_for_center_slug,
            _rewrite_space_codes,
        )

        cs = str(parsed.center.get("slug") or "")
        prefix = code_prefix or str(parsed.center.get("code_prefix") or "").strip().upper()
        if not prefix:
            prefix = _code_prefix_for_center_slug(cs, str(parsed.center.get("name") or ""))
        parsed.center["code_prefix"] = prefix
        _rewrite_space_codes(parsed.ad_spaces, new_prefix=prefix)

        images_map = load_images_map(images_dir)
        with_images: list[str] = []
        without: list[str] = []

        self.stdout.write(
            self.style.NOTICE(
                f"Centro: {parsed.center.get('name')} (slug={cs}) · prefijo={prefix} · "
                f"tomas={len(parsed.ad_spaces)} · imágenes en {images_dir}"
            )
        )

        for spec in parsed.ad_spaces:
            if not isinstance(spec, dict):
                continue
            code = str(spec.get("code") or "").strip()
            if not code:
                continue
            paths = collect_images_for_code(
                images_dir,
                code,
                spec=spec,
                images_map=images_map,
            )
            paths, skipped = _filter_seed_image_paths(paths)
            if skipped:
                self.stdout.write(
                    self.style.WARNING(f"  {code}: archivos omitidos (corruptos): {', '.join(skipped)}")
                )
            if paths:
                with_images.append(f"{code} ({len(paths)} foto(s))")
            else:
                title = (spec.get("title") or "")[:60]
                without.append(f"{code} — {title}")

        self.stdout.write(self.style.SUCCESS(f"\nCon imágenes ({len(with_images)}):"))
        for line in with_images:
            self.stdout.write(f"  ✓ {line}")

        if without:
            self.stdout.write(self.style.ERROR(f"\nSin imágenes ({len(without)}):"))
            for line in without:
                self.stdout.write(f"  ✗ {line}")
        else:
            self.stdout.write(self.style.SUCCESS("\nTodas las tomas tienen al menos una imagen."))
