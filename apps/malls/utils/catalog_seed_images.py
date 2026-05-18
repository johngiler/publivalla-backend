"""
Asociación de fotos locales con códigos de toma en ``seed_production_catalog``.

Soporta:
- Archivos planos ``TOMA n`` en la raíz del directorio (convención histórica).
- Subcarpetas con imágenes (p. ej. ``CAND-AB-CINT02-LAT/IMG_*.jpeg``).
- Mapa explícito ``catalog-images-map.json`` en la raíz del directorio de imágenes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_MAP_FILENAMES = ("catalog-images-map.json", "images-map.json")


def load_images_map(images_dir: Path) -> dict[str, str]:
    """Código de toma (mayúsculas) → nombre de subcarpeta relativo."""
    for name in _MAP_FILENAMES:
        path = images_dir / name
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        out: dict[str, str] = {}
        for key, val in raw.items():
            k = str(key or "").strip().upper()
            v = str(val or "").strip()
            if k and v:
                out[k] = v
        return out
    return {}


def _filename_patterns_for_space_code(code: str) -> list[re.Pattern[str]]:
    """
    ``PREFIX-T2A`` → archivos «TOMA 2A …»; ``PREFIX-T1`` → «TOMA 1 …» (no «TOMA 1A» ni «TOMA 10»).
    """
    c = (code or "").strip().upper()
    m = re.match(r"^[\w]+-T(?P<n>\d{1,2})(?P<suf>[A-Z])?$", c)
    if not m:
        return []
    n = m.group("n")
    suf = (m.group("suf") or "").upper()
    if suf:
        return [re.compile(rf"^TOMA\s*{n}{suf}(?:[\s\._\(]|$)", re.IGNORECASE)]
    return [
        re.compile(rf"^TOMA\s*{n}(?![0-9A-Z])(?:[\s\._\(]|$)", re.IGNORECASE),
    ]


def _sort_gallery_paths(paths: list[Path]) -> list[Path]:
    def sort_key(p: Path) -> tuple:
        stem = p.stem
        m = re.match(r"^(?P<base>.+)\((?P<idx>\d+)\)$", stem)
        if m:
            return (m.group("base").strip().lower(), 1, int(m.group("idx")))
        return (stem.lower(), 0, 0)

    return sorted(paths, key=sort_key)


def _images_in_dir(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    found = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
    ]
    return _sort_gallery_paths(found)


def _normalize_match_text(value: str) -> str:
    return (
        (value or "")
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ü", "u")
        .replace("ñ", "n")
    )


def _score_flat_filename_for_spec(filename: str, spec: dict | None) -> int:
    """Prioriza archivos cuyo nombre comparte palabras con título/ubicación de la toma."""
    if not spec:
        return 0
    blob = _normalize_match_text(_location_blob(spec))
    if not blob:
        return 0
    name = _normalize_match_text(filename)
    tokens = [t for t in re.split(r"[^a-z0-9]+", blob) if len(t) >= 4]
    return sum(1 for t in tokens if t in name)


def _collect_flat_toma_files(
    images_dir: Path, code: str, *, spec: dict | None = None
) -> list[Path]:
    patterns = _filename_patterns_for_space_code(code)
    if not patterns:
        return []
    found: list[Path] = []
    for p in images_dir.iterdir():
        if not p.is_file() or p.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        if any(pat.search(p.name) for pat in patterns):
            found.append(p)
    if len(found) <= 1:
        return _sort_gallery_paths(found)
    scored = sorted(
        found,
        key=lambda p: (-_score_flat_filename_for_spec(p.name, spec), p.name.lower()),
    )
    best = _score_flat_filename_for_spec(scored[0].name, spec)
    if best > 0:
        scored = [p for p in scored if _score_flat_filename_for_spec(p.name, spec) > 0]
    return _sort_gallery_paths(scored)


def _toma_suffix_from_code(code: str) -> str | None:
    c = (code or "").strip().upper()
    m = re.search(r"-T(?P<num>\d{1,2})(?P<suf>[A-Z])?$", c)
    if not m:
        return None
    return f"T{m.group('num')}{m.group('suf') or ''}"


def _location_blob(spec: dict | None) -> str:
    if not spec:
        return ""
    parts = [
        spec.get("title"),
        spec.get("location_description"),
        spec.get("level"),
        spec.get("installation_notes"),
    ]
    return " ".join(str(p or "") for p in parts).lower()


def _subdir_match_score(subdir_name: str, code: str, *, spec: dict | None) -> int:
    """Puntuación heurística subcarpeta ↔ toma (mayor = mejor)."""
    sn = subdir_name.upper()
    cu = code.upper()
    score = 0
    if cu in sn or sn.replace("-", "") in cu.replace("-", ""):
        score += 100

    tkey = _toma_suffix_from_code(code)
    if tkey and tkey in sn:
        score += 70

    loc = _location_blob(spec)
    zone_prefixes: list[str] = []
    if loc:
        if "sur" in loc or "ascensor" in loc:
            zone_prefixes.append("SUR")
        if "andré" in loc or "andres" in loc or "bello" in loc:
            zone_prefixes.append("AB")
        if "miranda" in loc:
            zone_prefixes.append("NM")
        if "galería" in loc or "galeria" in loc:
            zone_prefixes.append("NG")
        if "gourmet" in loc:
            zone_prefixes.append("ZG")
        if "norte" in loc and "miranda" not in loc:
            zone_prefixes.append("NP")

    m = re.search(r"-T(?P<num>\d{1,2})(?P<suf>[A-Z])?$", cu)
    if m:
        num = m.group("num")
        for cint in (f"CINT{num}", f"CINT{num.zfill(2)}", f"CINT0{num}"):
            if cint in sn:
                if not zone_prefixes or any(f"-{zp}-" in sn for zp in zone_prefixes):
                    score += 55
                break
    if loc:
        if "ascensor" in loc:
            if "-SUR-" in sn:
                score += 85
            elif "-AB-" in sn:
                score -= 40
        if ("sur" in loc or "ascensor" in loc) and "-SUR-" in sn:
            score += 50
        if ("andré" in loc or "andres" in loc or "bello" in loc) and "-AB-" in sn:
            score += 28
        if "miranda" in loc and "-NM-" in sn:
            score += 50
        if ("galería" in loc or "galeria" in loc) and "-NG-" in sn:
            score += 50
        if "gourmet" in loc and "-ZG" in sn:
            score += 55
        if "oeste" in loc and ("PZA O" in sn or "-PZA O" in sn):
            score += 40
        if "este" in loc and ("PZA E" in sn or "-PZA E" in sn):
            score += 40
        if "norte" in loc and "-NP-" in sn:
            score += 45
        if ("acceso norte" in loc or "vidrio" in loc) and ("ACC" in sn or "PA01" in sn):
            score += 45
        if "estacionamiento" in loc and ("PE" in sn or "-A01" in sn):
            score += 40
        if "lateral" in loc and "LAT" in sn:
            score += 35
        if "central" in loc and "CENTRAL" in sn:
            score += 25

    return score


def _resolve_subdir(
    images_dir: Path,
    code: str,
    *,
    spec: dict | None,
    images_map: dict[str, str],
) -> Path | None:
    mapped = images_map.get(code.upper())
    if mapped:
        candidate = (images_dir / mapped).resolve()
        if candidate.is_dir():
            return candidate
        return None

    subdirs = sorted(
        (p for p in images_dir.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.name.lower(),
    )
    best: Path | None = None
    best_score = 0
    for sub in subdirs:
        score = _subdir_match_score(sub.name, code, spec=spec)
        if score > best_score:
            best_score = score
            best = sub
    if best is None or best_score < 30:
        return None
    return best


def collect_images_for_code(
    images_dir: Path,
    code: str,
    *,
    spec: dict | None = None,
    images_map: dict[str, str] | None = None,
) -> list[Path]:
    """Devuelve rutas de imagen para una toma (planas ``TOMA n`` o subcarpeta)."""
    flat = _collect_flat_toma_files(images_dir, code, spec=spec)
    if flat:
        return flat

    subdirs = [p for p in images_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not subdirs:
        return []

    sub = _resolve_subdir(images_dir, code, spec=spec, images_map=images_map or {})
    if sub is None:
        return []
    return _images_in_dir(sub)
