"""
Parser heurístico de catálogos PDF (bloques «TOMA n») para cualquier workspace/owner.

Los títulos del PDF suelen llevar la marca del operador («{nombre} Valencia», «Centro …»).
Esa marca se infiere del ``workspace`` que pasa el comando de seed, no de un tenant fijo en código.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from django.utils.text import slugify


@dataclass(frozen=True)
class ParsedCatalog:
    center: dict
    ad_spaces: list[dict]
    raw_meta: dict


@dataclass(frozen=True)
class CatalogPdfParseContext:
    """Prefijos de nombre de centro detectables en PDF / nombre de archivo."""

    brand_center_prefixes: tuple[tuple[str, str], ...]

    @property
    def reserved_slug_tokens(self) -> frozenset[str]:
        return frozenset(k for k, _ in self.brand_center_prefixes)

    @classmethod
    def for_workspace(
        cls,
        workspace_slug: str | None = None,
        workspace_name: str | None = None,
        *,
        extra_prefixes: Iterable[tuple[str, str]] | None = None,
    ) -> CatalogPdfParseContext:
        return cls(
            brand_center_prefixes=build_brand_center_prefixes(
                workspace_slug,
                workspace_name,
                extra=extra_prefixes,
            )
        )


_GENERIC_CENTER_PREFIXES: tuple[tuple[str, str], ...] = (("centro", "Centro"),)


def build_brand_center_prefixes(
    workspace_slug: str | None = None,
    workspace_name: str | None = None,
    *,
    extra: Iterable[tuple[str, str]] | None = None,
) -> tuple[tuple[str, str], ...]:
    """
    Palabras iniciales de nombre de centro en PDF (p. ej. slug y nombre comercial del owner).
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(key: str, display: str) -> None:
        k = (key or "").strip().lower()
        if not k or k in seen:
            return
        seen.add(k)
        d = (display or "").strip() or k.title()
        out.append((k, d))

    for key, display in _GENERIC_CENTER_PREFIXES:
        add(key, display)

    slug = (workspace_slug or "").strip().lower()
    name = (workspace_name or "").strip()
    if slug:
        add(slug, name or slug.title())
    if name:
        first = name.split()[0]
        add(first.lower(), first)

    if extra:
        for key, display in extra:
            add(key, display)

    return tuple(out)


def _line_starts_with_brand_center(low: str, ctx: CatalogPdfParseContext) -> bool:
    return any(low.startswith(f"{key} ") for key, _ in ctx.brand_center_prefixes)


def _brand_display_and_rest(
    low: str, raw: str, ctx: CatalogPdfParseContext
) -> tuple[str | None, str]:
    for key, display in ctx.brand_center_prefixes:
        if low.startswith(f"{key} "):
            return display, raw[len(key) + 1 :]
    return None, raw


_RE_TOMA = re.compile(
    r"\bTOMA\s*(?P<idx>\d{1,2})(?P<suf>[A-Z])?\b", re.IGNORECASE
)
_RE_MONEY = re.compile(
    r"(?P<val>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)"
)
_RE_DIM = re.compile(
    r"(?P<w>\d{1,2}(?:[.,]\d{1,2})?)\s*[x×]\s*(?P<h>\d{1,2}(?:[.,]\d{1,2})?)",
    re.IGNORECASE,
)

_RE_CANON = re.compile(
    r"canon\s+mensual\s*:\s*\$?\s*(?P<val>[0-9][0-9\.,]*)",
    re.IGNORECASE,
)
_RE_MEDIDAS = re.compile(r"\bmedid(?:a|as|as\s*área\s*visual|as\s*area\s*visual)\s*:\s*(?P<rest>.+)$", re.IGNORECASE)
_RE_MEDIAS = re.compile(r"\bmedi(?:a|as)\s*:\s*(?P<rest>.+)$", re.IGNORECASE)
_RE_CANTIDAD = re.compile(r"\bcantidad\s*:\s*(?P<val>\d{1,3})\b", re.IGNORECASE)
_RE_UBICACION = re.compile(r"\bubicaci[oó]n\s*:\s*(?P<rest>.+)$", re.IGNORECASE)
_RE_MATERIAL = re.compile(r"\bmaterial\s*:\s*(?P<rest>.+)$", re.IGNORECASE)
_RE_OBSERV = re.compile(r"\bobservaci[oó]n(?:es)?\s*:\s*(?P<rest>.+)$", re.IGNORECASE)
_RE_BOLSILLO = re.compile(r"bolsillo\s+hueco\s+de\s*(?P<cm>\d+(?:[.,]\d+)?)\s*cm", re.IGNORECASE)
_RE_NIVEL = re.compile(r"\bnivel\s+(?P<rest>[A-Za-zÁÉÍÓÚÑñ ]{3,60})", re.IGNORECASE)
_RE_ESP_SPECS = re.compile(r"\bespecificaciones\s+para\s+artes?\s+y\s+producci[oó]n(?:es)?\b", re.IGNORECASE)


def _clean_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _collapse_spaced_caps(s: str) -> str:
    if not s:
        return ""

    tokens = [t for t in s.split() if t]
    if not tokens:
        return s
    single = sum(1 for t in tokens if len(t) == 1 and t.isalpha())
    if single >= 6 and single / max(1, len(tokens)) >= 0.5:
        return "".join(tokens)

    def repl(m: re.Match) -> str:
        return m.group(0).replace(" ", "")

    out = s
    out = re.sub(r"(?:\b[A-ZÁÉÍÓÚÑ]\b\s+){5,}\b[A-ZÁÉÍÓÚÑ]\b", repl, out)
    return out


def _is_specs_header(line: str) -> bool:
    raw = (line or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if low.startswith("especificaciones"):
        return True
    compact = re.sub(r"\\s+", "", raw).lower()
    return "especificacionesparaartesyproduccion" in compact or "especificacionesparaartesyproducciones" in compact


def _extract_first_dim(text: str) -> tuple[Decimal | None, Decimal | None]:
    md = _RE_DIM.search(text or "")
    if not md:
        return None, None
    return _to_decimal(md.group("w")), _to_decimal(md.group("h"))


def _infer_double_sided(*parts: str) -> bool | None:
    blob = " ".join(p for p in parts if p).lower()
    if not blob.strip():
        return None
    if "una cara" in blob or "una sola cara" in blob:
        return False
    if "doble cara" in blob or "ambas caras" in blob or "ambos lados" in blob:
        return True
    return None


def _infer_type(title_blob: str, *, w: Decimal | None, h: Decimal | None) -> str | None:
    t = (title_blob or "").lower()
    if "ascensor" in t:
        return "elevator"
    if "gigantograf" in t or "valla" in t:
        if w is not None and h is not None:
            if w >= h:
                return "valla_horizontal"
            return "valla_vertical"
        return "billboard"
    if "antepecho" in t:
        return "banner"
    if "vidrio" in t or "vidrios" in t:
        return "other"
    if "triángulo" in t or "triangulos" in t or "triángulos" in t:
        return "other"
    if "pendon" in t or "pendones" in t:
        if "balc" in t:
            return "pendon_balcon"
        if "columna" in t:
            return "pendon_columna"
        if "pasillo" in t:
            return "pendon_pasillo"
        if "plaza" in t:
            return "pendon_plaza"
        if "atrio" in t or "colgante" in t or "techo" in t:
            return "pendon_atrio"
        return "banner"
    if "banner" in t:
        return "banner"
    return None


def _base_title_for_type(type_value: str | None, raw_title_blob: str) -> str:
    blob = (raw_title_blob or "").lower()
    tv = (type_value or "").strip()
    if "gigantograf" in blob:
        return "Gigantografía"
    if "antepecho" in blob:
        return "Antepecho"
    if "vidrio" in blob or "vidrios" in blob:
        return "Vidrios"
    if "triángulo" in blob or "triangulos" in blob or "triángulos" in blob:
        return "Triángulos"

    if tv == "pendon_pasillo":
        return "Pendones pasillo"
    if tv == "pendon_columna":
        return "Pendones columna"
    if tv == "pendon_balcon":
        return "Pendones balcón"
    if tv == "pendon_atrio":
        return "Pendones atrio"
    if tv == "pendon_plaza":
        return "Pendones plaza"
    if tv == "banner":
        return "Pendones"
    if tv == "elevator":
        return "Ascensor"
    if tv == "valla_vertical":
        return "Valla vertical"
    if tv == "valla_horizontal":
        return "Valla horizontal"
    if tv == "billboard":
        return "Valla"
    return "Toma"


def _titlecase_spanish(s: str) -> str:
    raw = _clean_space(s)
    if not raw:
        return ""
    if raw.upper() == raw and any(c.isalpha() for c in raw):
        raw = raw.lower()
    return raw[0].upper() + raw[1:]


def _compose_title(existing: str, *, base: str, location: str) -> str:
    base_clean = _clean_space(base) or "Toma"
    loc = _clean_space(location).rstrip(".")
    if not loc:
        return (existing or base_clean)[:255]

    low = loc.lower()
    if base_clean.lower().startswith("pendones pasillo") and low.startswith("pasillo"):
        loc = re.sub(r"^pasillo(\s+de)?\s+", "", loc, flags=re.IGNORECASE)
    if base_clean.lower().startswith("pendones columna") and low.startswith("columnas"):
        loc = re.sub(r"^columnas?\s+", "", loc, flags=re.IGNORECASE)
    if base_clean.lower().startswith("pendones balcón") and ("balcón" in low or "balcon" in low):
        loc = re.sub(r"^balc[oó]n(\s+del)?\s+", "", loc, flags=re.IGNORECASE)

    if " a " in loc.lower() and any(k in loc.lower() for k in ("plaza", "entrada", "zona", "playa")):
        loc = re.sub(r"\s+a\s+", " – ", loc, count=1, flags=re.IGNORECASE)

    loc = _titlecase_spanish(loc)
    composed = f"{base_clean} {loc}".strip()

    cur = _clean_space(existing)
    if cur:
        cur_low = cur.lower()
        generic = cur_low in ("pendones", "gigantografía", "gigantografia", "toma") or len(cur.split()) <= 2
        if not generic:
            return cur[:255]
    return composed[:255]


def _to_decimal(value: str) -> Decimal | None:
    s = (value or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        s = re.sub(r"[.,]", "", s)
    if s.count(",") and s.count("."):
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        if "," in s and "." not in s:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return Decimal(s)
    except Exception:
        return None


_GENERIC_CATALOG_PDF_STEMS = frozenset({"catalog", "catalogo", "catalogue", "data", "seed"})


def _center_slug_from_pdf_path(pdf_path: Path) -> str | None:
    """
    Si el PDF tiene un nombre genérico (p. ej. ``catalog.pdf`` en ``.../scr/catalog.pdf``),
    usa el directorio padre como slug del centro.
    """
    stem = pdf_path.stem.strip().lower()
    if stem not in _GENERIC_CATALOG_PDF_STEMS:
        return None
    parent_name = pdf_path.parent.name.strip()
    if not parent_name or parent_name.lower() in {"images", "malls", "data", "catalog"}:
        return None
    slug = slugify(parent_name)[:80]
    return slug or None


def _guess_center_name(text: str, pdf_name: str, ctx: CatalogPdfParseContext) -> str:
    def _normalize_center_name(raw: str) -> str:
        s = _clean_space(raw)
        if not s:
            return ""
        low = s.lower()
        brand_display, rest_raw = _brand_display_and_rest(low, s, ctx)
        if brand_display is not None:
            prefix = brand_display
            rest = rest_raw
        elif low.startswith("centro "):
            prefix = "Centro"
            rest = s[len("centro ") :]
        else:
            return s[:200]

        rest = _clean_space(rest)
        if not rest:
            return prefix

        words = [w for w in re.split(r"\s+", rest) if w]
        small = {"la", "el", "los", "las", "de", "del", "y", "a", "en"}
        norm_words: list[str] = []
        for i, w in enumerate(words):
            wl = w.lower()
            if i > 0 and wl in small:
                norm_words.append(wl)
            else:
                norm_words.append(wl[:1].upper() + wl[1:])
        return f"{prefix} {' '.join(norm_words)}"[:200]

    stem = Path(pdf_name).stem.replace("_", " ").strip()
    stem_low = stem.lower()
    stem_is_generic = stem_low in _GENERIC_CATALOG_PDF_STEMS

    if not stem_is_generic and (
        _line_starts_with_brand_center(stem_low, ctx) or stem_low.startswith("centro ")
    ):
        return _normalize_center_name(stem)

    t = (text or "").strip()
    head = "\n".join(t.splitlines()[:60])
    for line in head.splitlines():
        l = line.strip()
        if not l:
            continue
        low = l.lower()
        if _line_starts_with_brand_center(low, ctx) or low.startswith("centro "):
            return _normalize_center_name(l)

    if stem_is_generic:
        return ""
    return _normalize_center_name(stem) or stem[:200]


def _guess_center_city(name: str) -> str:
    n = (name or "").lower()
    for city in ("caracas", "valencia", "barquisimeto", "maracaibo"):
        if city in n:
            return city.title()
    return ""


def code_prefix_for_center_slug(center_slug: str, center_name: str = "") -> str:
    """
    Prefijo para códigos de toma ``XXX-Tn`` a partir del slug del centro (hasta 3 letras).
    """
    slug = (center_slug or "").strip().upper()
    if slug:
        clean = re.sub(r"[^A-Z0-9]", "", slug)[:3]
        if clean:
            return clean
    parts = re.split(r"[\s\-]+", (center_name or "").strip())
    letters = "".join(p[0] for p in parts if p)[:3].upper()
    return letters or "CC"


def _guess_code_prefix(center_slug: str, center_name: str, ctx: CatalogPdfParseContext) -> str:
    parts = [
        p
        for p in (center_slug or "").split("-")
        if p and p.lower() not in ctx.reserved_slug_tokens
    ]
    if parts:
        base = parts[0][:3].upper()
    else:
        base = (center_slug or "")[:3].upper()
    base = re.sub(r"[^A-Z0-9]", "", base)
    if base:
        return base if len(base) >= 3 else code_prefix_for_center_slug(center_slug, center_name)
    return code_prefix_for_center_slug(center_slug, center_name)


def short_center_slug_candidates(
    center_name: str,
    ctx: CatalogPdfParseContext | None = None,
) -> list[str]:
    """
    Slugs cortos (3 letras) cuando el nombre del centro lleva la marca del operador.
    Alineado con la heurística del panel admin (prefijo ``s`` + iniciales).
    """
    if ctx is None:
        ctx = CatalogPdfParseContext.for_workspace()

    n = (center_name or "").strip()
    low = n.lower()
    if not n:
        return []

    rest = None
    for key, _display in ctx.brand_center_prefixes:
        if key == "centro":
            continue
        m = re.match(rf"^{re.escape(key)}\s+(?P<rest>.+)$", low, flags=re.IGNORECASE)
        if m:
            rest = m.group("rest").strip()
            break
    if not rest:
        return []

    tokens = [t for t in re.split(r"\s+", rest) if t]
    if not tokens:
        return []
    base = re.sub(r"[^a-z0-9]", "", tokens[0].lower())
    if not base:
        return []

    vowels = set("aeiouáéíóú")
    consonants = [ch for ch in base[1:] if ch.isalnum() and ch not in vowels]
    out: list[str] = []
    first = base[0]
    if consonants:
        for c in consonants:
            cand = re.sub(r"[^a-z0-9]", "", (f"s{first}{c}").lower())
            if len(cand) == 3:
                out.append(cand)
    if not out:
        a = base[0:1]
        b = base[1:2] or base[0:1]
        out.append(re.sub(r"[^a-z0-9]", "", f"s{a}{b}".lower())[:3])
    seen = set()
    uniq = []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _short_brand_slug(center_name: str, ctx: CatalogPdfParseContext) -> str | None:
    cands = short_center_slug_candidates(center_name, ctx)
    return cands[0] if cands else None


def _normalize_center(center_name: str, ctx: CatalogPdfParseContext) -> dict:
    slug = _short_brand_slug(center_name, ctx) or (slugify(center_name)[:80] or "center")
    city = _guess_center_city(center_name)
    name_clean = (center_name or "").strip()
    city_clean = (city or "").strip()
    if name_clean and city_clean:
        auto_desc = f"Centro comercial {name_clean} ({city_clean})."
    elif name_clean:
        auto_desc = f"Centro comercial {name_clean}."
    else:
        auto_desc = "Centro comercial."
    return {
        "slug": slug,
        "name": center_name,
        "city": city,
        "address": "",
        "country": "Venezuela",
        "description": auto_desc,
        "lessor_legal_name": "",
        "lessor_rif": "",
        "municipal_authority_line": "",
        "municipal_permit_notice": "",
        "advertising_regulations": "",
        "authorization_letter_city": city or "Caracas",
        "is_active": True,
        "code_prefix": "",
    }


def _split_into_toma_chunks(full_text: str) -> list[str]:
    matches = list(_RE_TOMA.finditer(full_text or ""))
    if not matches:
        return []
    chunks: list[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        chunk = (full_text[start:end] or "").strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def _parse_toma_chunk(chunk: str, *, code_prefix: str) -> dict | None:
    m = _RE_TOMA.search(chunk or "")
    if not m:
        return None
    idx = m.group("idx")
    suf = (m.group("suf") or "").upper()
    code = f"{code_prefix}-T{idx}{suf}".strip()

    raw_lines = [ln.strip() for ln in (chunk or "").splitlines() if ln.strip()]
    header_line = raw_lines[0] if raw_lines else ""

    header_title = ""
    hm = re.match(r"^TOMA\s*\d{1,2}[A-Z]?\s*:\s*(?P<t>.+)$", header_line, flags=re.IGNORECASE)
    if hm:
        header_title = _clean_space(hm.group("t"))[:255]

    title_lines: list[str] = []
    ubicacion = ""
    canon = None
    cantidad = None
    medidas_line = ""
    material = ""
    observ_lines: list[str] = []
    specs_lines: list[str] = []
    in_specs = False

    for ln in raw_lines[1:]:
        ln = _collapse_spaced_caps(ln)
        if _is_specs_header(ln) or _RE_ESP_SPECS.search(ln):
            in_specs = True
            continue
        if in_specs:
            specs_lines.append(ln)
        mo = _RE_OBSERV.search(ln)
        if mo:
            observ_lines.append(_clean_space(mo.group("rest")))
            continue
        mu = _RE_UBICACION.search(ln)
        if mu and not ubicacion:
            ubicacion = _clean_space(mu.group("rest"))
            continue
        mc = _RE_CANON.search(ln)
        if mc and canon is None:
            canon = _to_decimal(mc.group("val"))
            continue
        mq = _RE_CANTIDAD.search(ln)
        if mq and cantidad is None:
            try:
                cantidad = int(mq.group("val"))
            except Exception:
                cantidad = None
            continue
        mm = _RE_MATERIAL.search(ln)
        if mm and not material:
            material = _clean_space(mm.group("rest"))[:255]
            continue
        md = _RE_MEDIDAS.search(ln) or _RE_MEDIAS.search(ln)
        if md and not medidas_line:
            medidas_line = _clean_space(md.group("rest"))
            continue

        if not title_lines:
            low = ln.lower()
            if any(
                k in low
                for k in (
                    "medidas:",
                    "medias:",
                    "cantidad:",
                    "ubicación:",
                    "canon mensual",
                    "material:",
                    "observación",
                    "observaciones",
                )
            ):
                pass
            else:
                title_lines.append(_clean_space(ln)[:255])
                continue

        if in_specs:
            specs_lines.append(ln)

    w, h = _extract_first_dim(medidas_line)
    if w is None or h is None:
        w2, h2 = _extract_first_dim(chunk)
        w = w or w2
        h = h or h2

    level = ""
    lvl_src = " ".join([ubicacion] + observ_lines)
    lm = _RE_NIVEL.search(lvl_src)
    if lm:
        level = _clean_space(lm.group("rest"))[:64]

    hem_cm = None
    bm = _RE_BOLSILLO.search(" ".join(observ_lines + specs_lines))
    if bm:
        hem_cm = _to_decimal(bm.group("cm"))

    double_sided = _infer_double_sided(header_line, " ".join(observ_lines), " ".join(specs_lines))
    if double_sided is None:
        double_sided = False

    raw_title = header_title or (title_lines[0] if title_lines else "") or ""
    inferred_type = _infer_type(
        " ".join([header_line, raw_title] + title_lines + [ubicacion]), w=w, h=h
    )

    base_title = _base_title_for_type(
        inferred_type,
        " ".join([header_line, raw_title, " ".join(title_lines), ubicacion]),
    )
    title = _compose_title(raw_title, base=base_title, location=ubicacion) or f"Toma {idx}{suf}".strip()
    title = title[:255]

    cleaned_specs: list[str] = []
    for ln in specs_lines:
        ln = _collapse_spaced_caps(ln)
        if _is_specs_header(ln) or _RE_ESP_SPECS.search(ln):
            continue
        if ln.strip():
            cleaned_specs.append(_clean_space(ln))
    production_specs = "\n".join(cleaned_specs).strip()

    installation_notes = "\n".join([l for l in observ_lines if l]).strip()

    desc_parts: list[str] = []
    if w is not None and h is not None:
        desc_parts.append(f"Medidas {w} × {h} m.")
    if cantidad is not None:
        desc_parts.append(f"Cantidad {cantidad}.")
    if ubicacion:
        desc_parts.append(f"Ubicación: {ubicacion}.")
    if double_sided:
        desc_parts.append("Elementos doble cara.")
    description = " ".join(desc_parts).strip()

    if canon is None:
        return None

    return {
        "code": code,
        "type": inferred_type,
        "title": title,
        "description": description,
        "width": str(w) if w is not None else None,
        "height": str(h) if h is not None else None,
        "quantity": cantidad if cantidad is not None else 1,
        "material": material,
        "location_description": ubicacion,
        "level": level,
        "monthly_price_usd": str(canon) if canon is not None else None,
        "status": "available",
        "venue_zone": "",
        "double_sided": bool(double_sided),
        "production_specs": production_specs,
        "installation_notes": installation_notes,
        "hem_pocket_top_cm": str(hem_cm) if hem_cm is not None else None,
    }


def parse_catalog_pdf_to_json_bundle(
    pdf_path: Path,
    *,
    workspace_slug: str | None = None,
    workspace_name: str | None = None,
) -> ParsedCatalog:
    """
    Lee un PDF de catálogo y devuelve centro + tomas normalizados.

    ``workspace_slug`` / ``workspace_name`` alimentan la detección de marca en títulos del PDF.
    """
    from pypdf import PdfReader

    ctx = CatalogPdfParseContext.for_workspace(workspace_slug, workspace_name)

    p = Path(pdf_path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))

    reader = PdfReader(str(p))
    pages_text: list[str] = []
    for page in reader.pages:
        try:
            pages_text.append(page.extract_text() or "")
        except Exception:
            pages_text.append("")
    full_text = "\n".join(pages_text)

    center_name = _guess_center_name(full_text, p.name, ctx)
    center = _normalize_center(center_name, ctx)
    path_slug = _center_slug_from_pdf_path(p)
    if path_slug:
        center["slug"] = path_slug
    center["catalog_pdf_path"] = str(p)
    center["code_prefix"] = _guess_code_prefix(center["slug"], center_name, ctx)

    chunks = _split_into_toma_chunks(full_text)
    ad_spaces: list[dict] = []
    seen: set[str] = set()
    for ch in chunks:
        row = _parse_toma_chunk(ch, code_prefix=center["code_prefix"])
        if not row:
            continue
        code = row["code"]
        if code in seen:
            continue
        seen.add(code)
        ad_spaces.append(row)

    raw_meta = {
        "pdf_path": str(p),
        "pages": len(reader.pages),
        "tomas_detected": len(ad_spaces),
        "workspace_slug": (workspace_slug or "").strip().lower(),
    }
    return ParsedCatalog(center=center, ad_spaces=ad_spaces, raw_meta=raw_meta)


def write_bundle_json(bundle: ParsedCatalog, out_path: Path) -> None:
    o = {
        "center": bundle.center,
        "ad_spaces": bundle.ad_spaces,
        "_meta": bundle.raw_meta,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(o, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
