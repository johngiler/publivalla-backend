"""
Importa catálogo (centro + tomas) para **cualquier workspace**: desde PDF o modo demostración.

**Sin ``--pdf``** (o con ``--demo``): genera un centro y tomas ficticios con todos los campos
rellenos, para mostrar el marketplace antes de recibir el PDF real del cliente.

**Con ``--pdf``**: flujo de producción (parseo, ``data/<slug>/catalog/data.json``, BD).

Ejemplos::

    python manage.py seed_production_catalog --workspace-slug acme
    python manage.py seed_production_catalog --workspace-slug acme --demo-toma-count 10
    python manage.py seed_production_catalog --workspace-slug sambil --pdf /ruta/catalogo.pdf
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.common.utils.data_layout import catalog_seed_json_path
from apps.ad_spaces.utils.gallery import sync_cover_from_gallery
from apps.ad_spaces.models import AdSpace, AdSpaceImage, AdSpaceStatus
from apps.malls.utils.catalog_demo_bundle import build_demo_catalog_bundle
from apps.malls.utils.catalog_pdf_parser import (
    CatalogPdfParseContext,
    ParsedCatalog,
    code_prefix_for_center_slug,
    parse_catalog_pdf_to_json_bundle,
    short_center_slug_candidates,
    write_bundle_json,
)
from apps.malls.models import ShoppingCenter
from apps.users.models import UserProfile
from apps.workspaces.models import Workspace
from apps.workspaces.utils.common import get_default_workspace

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _dec(value):
    """Convierte string/number a Decimal; deja None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    if s == "":
        return None
    return Decimal(s)


def _validate_existing(ws: Workspace, *, center_slug: str, space_codes: list[str], force: bool) -> None:
    """
    Validación mínima:
    - `ShoppingCenter.slug` es único por workspace (update_or_create lo resuelve).
    - `AdSpace.code` es único global; si existe y apunta a otro centro del mismo workspace,
      por defecto se bloquea para no “mover” tomas entre centros.
    """
    if not space_codes:
        return
    existing = (
        AdSpace.objects.filter(code__in=space_codes)
        .select_related("shopping_center")
        .only("id", "code", "shopping_center_id", "shopping_center__slug", "shopping_center__workspace_id")
    )
    bad: list[str] = []
    for row in existing:
        sc = getattr(row, "shopping_center", None)
        if sc is None:
            continue
        if sc.workspace_id != ws.pk:
            bad.append(f"{row.code} (workspace distinto: {sc.slug})")
            continue
        if sc.slug != center_slug:
            bad.append(f"{row.code} (ya existe en {sc.slug})")
    if bad and not force:
        raise CommandError(
            "Conflicto: hay códigos de toma ya existentes en otro centro. "
            "Usa --force si estás seguro.\n- " + "\n- ".join(bad)
        )


def _resolve_center_slug_for_apply(
    ws: Workspace, parsed_center: dict, *, parse_ctx: CatalogPdfParseContext
) -> str:
    """
    Evita duplicados si el slug inferido cambió entre importaciones.
    Si existe un centro con el mismo nombre en el workspace, se reutiliza y se renombra el slug
    (si está libre).
    """
    desired = str((parsed_center or {}).get("slug") or "").strip()
    name = str((parsed_center or {}).get("name") or "").strip()
    if not desired:
        return desired
    if not name:
        return desired

    if ShoppingCenter.objects.filter(workspace=ws, slug=desired).exclude(name__iexact=name).exists():
        for cand in short_center_slug_candidates(name, parse_ctx):
            if not ShoppingCenter.objects.filter(workspace=ws, slug=cand).exclude(name__iexact=name).exists():
                desired = cand
                break

    by_slug = ShoppingCenter.objects.filter(workspace=ws, slug=desired).only("id").first()
    if by_slug:
        return desired

    existing = (
        ShoppingCenter.objects.filter(workspace=ws, name__iexact=name)
        .only("id", "slug", "name")
        .first()
    )
    if not existing:
        return desired

    if existing.slug == desired:
        return desired

    # Renombra el slug si está libre
    exists_desired = ShoppingCenter.objects.filter(workspace=ws, slug=desired).exists()
    if not exists_desired:
        ShoppingCenter.objects.filter(pk=existing.pk).update(slug=desired)
        return desired
    # Si está ocupado, usa el slug existente (no duplicar).
    return existing.slug


def _code_prefix_for_center_slug(center_slug: str, center_name: str = "") -> str:
    return code_prefix_for_center_slug(center_slug, center_name)


def _rewrite_space_codes(spaces: list[dict], *, new_prefix: str) -> None:
    """
    Reescribe `code` en cada toma a `<new_prefix>-T...` manteniendo el sufijo `Tn[A-Z]`.
    """
    if not new_prefix:
        return
    for row in spaces:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        m = re.search(r"-T(?P<suf>\d{1,2}[A-Z]?)$", code)
        if not m:
            continue
        row["code"] = f"{new_prefix}-T{m.group('suf')}"


def _filename_patterns_for_space_code(code: str) -> list[re.Pattern[str]]:
    """Asocia códigos ``<PREFIJO>-Tn`` con nombres de archivo ``TOMA n`` en la carpeta de imágenes."""
    c = (code or "").strip().upper()
    if re.fullmatch(r"[\w]+-T1$", c):
        return [
            re.compile(r"^TOMA\s*1A", re.IGNORECASE),
            re.compile(r"^TOMA\s*1B", re.IGNORECASE),
        ]
    m = re.match(r"^[\w]+-T(?P<n>\d{1,2})(?P<suf>[A-Z])?$", c)
    if not m:
        return []
    n = m.group("n")
    suf = m.group("suf") or ""
    return [re.compile(rf"^TOMA\s*{n}{suf}(?:[\s\._\(]|$)", re.IGNORECASE)]


def _is_readable_image_file(path: Path) -> bool:
    """True si el archivo es una imagen raster legible (Pillow); excluye vacíos y corruptos."""
    from PIL import Image, UnidentifiedImageError

    try:
        if not path.is_file():
            return False
        if path.stat().st_size == 0:
            return False
        with Image.open(path) as im:
            im.verify()
    except (OSError, UnidentifiedImageError, ValueError, SyntaxError):
        return False
    return True


def _filter_seed_image_paths(paths: list[Path]) -> tuple[list[Path], list[str]]:
    """Devuelve rutas válidas y nombres omitidos (no imagen / corrupto / 0 bytes)."""
    valid: list[Path] = []
    skipped: list[str] = []
    for p in paths:
        if _is_readable_image_file(p):
            valid.append(p)
        else:
            skipped.append(p.name)
    return valid, skipped


def _sort_gallery_paths(paths: list[Path]) -> list[Path]:
    """Orden: archivo base sin (n) primero; luego (1), (2), …; después orden alfabético del nombre."""

    def sort_key(p: Path) -> tuple:
        stem = p.stem
        m = re.match(r"^(?P<base>.+)\((?P<idx>\d+)\)$", stem)
        if m:
            return (m.group("base").strip().lower(), 1, int(m.group("idx")))
        return (stem.lower(), 0, 0)

    return sorted(paths, key=sort_key)


def _collect_images_for_code(images_dir: Path, code: str) -> list[Path]:
    """Busca archivos de imagen cuyo nombre coincida con el código de toma (convención ``TOMA n``)."""
    if not images_dir or not images_dir.is_dir():
        return []
    c = (code or "").strip()
    if not c:
        return []
    patterns = _filename_patterns_for_space_code(c)
    if not patterns:
        return []
    found: list[Path] = []
    for p in images_dir.iterdir():
        if not p.is_file() or p.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        if any(pat.search(p.name) for pat in patterns):
            found.append(p)
    return _sort_gallery_paths(found)


def _first_marketplace_admin_for_workspace(ws: Workspace):
    """
    Primer usuario del workspace con rol administrador marketplace (orden: date_joined, id).
    """
    User = get_user_model()
    return (
        User.objects.filter(
            profile__workspace_id=ws.pk,
            profile__role=UserProfile.Role.ADMIN,
        )
        .order_by("date_joined", "id")
        .first()
    )


def _apply_toma_gallery(ad: AdSpace, paths: list[Path]) -> None:
    ad.gallery_images.all().delete()
    for order, img_path in enumerate(paths):
        with img_path.open("rb") as fh:
            AdSpaceImage.objects.create(
                ad_space=ad,
                image=File(fh, name=img_path.name),
                sort_order=order,
            )
    sync_cover_from_gallery(ad)


def _apply_parsed_catalog(
    command: BaseCommand,
    ws: Workspace,
    parsed: ParsedCatalog,
    *,
    parse_ctx: CatalogPdfParseContext,
    options: dict,
    demo_mode: bool,
) -> None:
    """Escribe data.json y aplica centro + tomas en BD."""
    data_json_path = catalog_seed_json_path(ws.slug)
    dry_run = bool(options.get("dry_run"))
    force = bool(options.get("force"))
    center_slug_override = (options.get("center_slug") or "").strip()
    code_prefix_override = (options.get("code_prefix") or "").strip().upper()
    images_raw = (options.get("images_dir") or "").strip()
    allow_missing_images = not bool(options.get("require_images"))

    if center_slug_override:
        parsed.center["slug"] = center_slug_override
    if code_prefix_override:
        parsed.center["code_prefix"] = code_prefix_override

    if dry_run:
        write_bundle_json(parsed, data_json_path)
        command.stdout.write(command.style.SUCCESS(f"Generado data.json: {data_json_path}"))
        command.stdout.write(
            command.style.NOTICE(
                f"Centro: {parsed.center.get('name')} (slug={parsed.center.get('slug')}) · "
                f"Tomas: {len(parsed.ad_spaces)}"
                + (" · modo demo" if demo_mode else "")
            )
        )
        command.stdout.write(command.style.SUCCESS("Dry-run: no se escribieron cambios en BD."))
        return

    feeder = _first_marketplace_admin_for_workspace(ws)
    if feeder is None:
        if demo_mode:
            command.stdout.write(
                command.style.WARNING(
                    "Modo demo: no hay administrador marketplace en el workspace; "
                    "se omite catalog_seed_feeder."
                )
            )
        else:
            raise CommandError(
                "No hay ningún usuario con rol «Administrador marketplace» vinculado a este "
                "workspace. Crea primero ese usuario para el owner y vuelve a ejecutar el comando."
            )

    center_slug = _resolve_center_slug_for_apply(ws, parsed.center, parse_ctx=parse_ctx)
    if not center_slug:
        raise CommandError("No se pudo inferir center.slug (usa --center-slug).")
    parsed.center["slug"] = center_slug
    center_name = str(parsed.center.get("name") or "")
    prefix = code_prefix_override or str(parsed.center.get("code_prefix") or "").strip().upper()
    if not prefix:
        prefix = _code_prefix_for_center_slug(center_slug, center_name)
    parsed.center["code_prefix"] = prefix
    _rewrite_space_codes(parsed.ad_spaces, new_prefix=prefix)

    write_bundle_json(parsed, data_json_path)
    command.stdout.write(command.style.SUCCESS(f"Generado data.json: {data_json_path}"))
    command.stdout.write(
        command.style.NOTICE(
            f"Centro: {parsed.center.get('name')} (slug={parsed.center.get('slug')}) · "
            f"Tomas: {len(parsed.ad_spaces)}"
            + (" · modo demo" if demo_mode else "")
        )
    )
    space_codes = [
        str(x.get("code") or "").strip()
        for x in parsed.ad_spaces
        if isinstance(x, dict)
    ]
    space_codes = [c for c in space_codes if c]
    _validate_existing(ws, center_slug=center_slug, space_codes=space_codes, force=force)

    images_dir = Path(images_raw).expanduser().resolve() if images_raw else None
    if images_dir is not None and not images_dir.is_dir():
        raise CommandError(f"No existe el directorio de imágenes: {images_dir}")

    with transaction.atomic():
        c = parsed.center
        defaults = {k: v for k, v in c.items() if k not in ("slug", "catalog_pdf_path", "code_prefix")}
        defaults.setdefault("country", "Venezuela")
        defaults.setdefault("on_homepage", True)
        defaults.setdefault("marketplace_catalog_enabled", True)
        defaults.setdefault("is_active", True)
        center, created = ShoppingCenter.objects.update_or_create(
            workspace=ws,
            slug=center_slug,
            defaults=defaults,
        )
        verb = "Creado" if created else "Actualizado"
        command.stdout.write(command.style.SUCCESS(f"{verb} centro {center.slug}: {center.name}"))

        created_n = updated_n = 0
        for spec in parsed.ad_spaces:
            if not isinstance(spec, dict):
                continue
            code = str(spec.get("code") or "").strip()
            if not code:
                continue
            defaults = {k: v for k, v in spec.items() if k != "code"}
            defaults["shopping_center"] = center
            defaults["status"] = AdSpaceStatus.AVAILABLE
            defaults["is_active"] = True
            for dk in ("monthly_price_usd", "width", "height", "hem_pocket_top_cm"):
                if dk in defaults:
                    defaults[dk] = _dec(defaults[dk])
            for k in (
                "description",
                "material",
                "location_description",
                "level",
                "venue_zone",
                "production_specs",
                "installation_notes",
            ):
                if k in defaults and (defaults[k] is None or str(defaults[k]).strip() == ""):
                    defaults.pop(k, None)
            if defaults.get("type") in ("", None):
                defaults.pop("type", None)
            if "monthly_price_usd" not in defaults or defaults.get("monthly_price_usd") is None:
                raise CommandError(f"{code}: falta Canon mensual (monthly_price_usd).")
            ad, was_created = AdSpace.objects.update_or_create(code=code, defaults=defaults)
            created_n += 1 if was_created else 0
            updated_n += 0 if was_created else 1

            paths: list[Path] = []
            if images_dir is not None:
                paths = _collect_images_for_code(images_dir, code)
            paths, skipped_img = _filter_seed_image_paths(paths)
            for name in skipped_img:
                command.stdout.write(command.style.WARNING(f"{code}: omitido «{name}» (no imagen válida)."))
            if paths:
                _apply_toma_gallery(ad, paths)
            elif not allow_missing_images and images_dir is not None:
                raise CommandError(
                    f"{code}: no se encontraron imágenes válidas en {images_dir} y está activo --require-images."
                )

        now = timezone.now()
        centers_map = dict(ws.catalog_seeded_centers or {})
        centers_map[str(center.slug)] = now.isoformat()
        audit_updates: dict = {
            "catalog_seeded_at": now,
            "catalog_seeded_centers": centers_map,
        }
        if feeder is not None and ws.catalog_seed_feeder_id is None:
            audit_updates["catalog_seed_feeder_id"] = feeder.pk
        Workspace.objects.filter(pk=ws.pk).update(**audit_updates)

    command.stdout.write(
        command.style.SUCCESS(
            f"Catálogo listo: {center_slug} · tomas={len(space_codes)} · creadas={created_n} · actualizadas={updated_n}."
        )
    )


class Command(BaseCommand):
    help = (
        "Importa catálogo (centro + tomas) desde PDF o genera datos demo si no hay PDF."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--pdf",
            type=str,
            default="",
            help="Ruta al PDF de catálogo. Si se omite, se usa catálogo demo ficticio.",
        )
        parser.add_argument(
            "--demo",
            action="store_true",
            help="Fuerza catálogo demo aunque exista otro flujo (equivale a no pasar --pdf).",
        )
        parser.add_argument(
            "--demo-toma-count",
            type=int,
            default=12,
            help="Tomas a crear en modo demo (mín. 4, máx. 24; por defecto 12).",
        )
        parser.add_argument(
            "--images-dir",
            type=str,
            default="",
            help="Carpeta con imágenes (opcional). Si faltan, se crean tomas sin galería/portada.",
        )
        parser.add_argument(
            "--require-images",
            action="store_true",
            help="Falla si faltan imágenes (modo estricto). Por defecto, crea/actualiza tomas aunque no haya fotos.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parsea el PDF y genera data.json, pero no escribe en BD.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Importa aunque existan códigos de toma en otro centro del mismo workspace (con conflicto).",
        )
        parser.add_argument(
            "--workspace-slug",
            type=str,
            default="",
            help="Slug del owner/tenant destino (obligatorio en producción). Por defecto: DEFAULT_WORKSPACE_SLUG o primer workspace activo.",
        )
        parser.add_argument(
            "--center-slug",
            type=str,
            default="",
            help="Fuerza el slug del centro comercial (si el parser infiere otro).",
        )
        parser.add_argument(
            "--code-prefix",
            type=str,
            default="",
            help="Fuerza el prefijo de códigos de toma (p. ej. SCC); por defecto se infiere del slug del centro.",
        )

    def handle(self, *args, **options):
        slug_opt = (options.get("workspace_slug") or "").strip()
        if slug_opt:
            ws = Workspace.objects.filter(slug=slug_opt, is_active=True).first()
            if ws is None:
                raise CommandError(f"No existe workspace activo con slug «{slug_opt}».")
        else:
            ws = get_default_workspace()
            if not ws:
                raise CommandError(
                    "No hay workspace activo. Define DEFAULT_WORKSPACE_SLUG, usa --workspace-slug o crea un workspace."
                )

        parse_ctx = CatalogPdfParseContext.for_workspace(ws.slug, ws.name)

        pdf_raw = (options.get("pdf") or "").strip()
        demo_flag = bool(options.get("demo"))
        if demo_flag and pdf_raw:
            raise CommandError("No combines --demo con --pdf; usa uno u otro.")

        use_demo = demo_flag or not pdf_raw

        if use_demo:
            toma_count = int(options.get("demo_toma_count") or 8)
            parsed = build_demo_catalog_bundle(
                ws,
                center_slug=(options.get("center_slug") or "").strip(),
                code_prefix=(options.get("code_prefix") or "").strip().upper(),
                toma_count=toma_count,
            )
            self.stdout.write(
                self.style.NOTICE(
                    f"Modo demo: catálogo ficticio para «{ws.slug}» ({len(parsed.ad_spaces)} tomas)."
                )
            )
        else:
            pdf_path = Path(pdf_raw).expanduser().resolve()
            if not pdf_path.is_file():
                raise CommandError(f"No existe el PDF: {pdf_path}")
            try:
                parsed = parse_catalog_pdf_to_json_bundle(
                    pdf_path,
                    workspace_slug=ws.slug,
                    workspace_name=ws.name,
                )
            except Exception as exc:
                raise CommandError(f"No se pudo parsear el PDF: {exc}") from exc

        _apply_parsed_catalog(
            self,
            ws,
            parsed,
            parse_ctx=parse_ctx,
            options=options,
            demo_mode=use_demo,
        )
