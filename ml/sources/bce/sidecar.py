"""Sidecar JSON par image + manifest par run pour BCE.

Le pipeline BCE n'écrit plus aucun ``coin_canonical_images`` ni
``coin_observations`` en eurio.db (cf. discussion "FS as SOT" 2026-05-25).
À la place :

- Chaque image WebP est accompagnée d'un fichier ``.json`` frère
  (``obverse_bce.json`` à côté de ``obverse_bce.webp``) qui porte toute
  la métadonnée BCE (feature, description, image_url, sha256, run_id…).
- Chaque run de pipeline écrit un manifest sous
  ``ml/state/bce_runs/{run_id}.json`` : stats, liste des coins matchés,
  liste des entries BCE non-matchées (utile pour debug + page admin).

Si eurio.db est perdue → re-run BCE pipeline depuis zéro :
- les snapshots HTML BCE sont sur disque (ml/datasets/sources/)
- les images sont re-fetched et re-cropées idempotently
- les sidecars sont ré-écrits
- la DB reste vide (Numista la peuplera de son côté)

Si les fichiers sont perdus mais la DB existe :
- la DB ne sait plus rien des BCE (on n'y écrit plus) → rerun BCE de toute façon

Source of truth = filesystem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ml/ root — pareil que canonical_image_local.py.
_ML_ROOT = Path(__file__).resolve().parents[2]
BCE_RUNS_DIR = _ML_ROOT / "state" / "bce_runs"


def sidecar_path(canonical_webp_path: Path) -> Path:
    """``obverse_bce.webp`` → ``obverse_bce.json`` (frère, même dossier)."""
    return canonical_webp_path.with_suffix(".json")


def write_sidecar(
    canonical_webp_path: Path,
    *,
    eurio_id: str,
    role: str,
    source: str,
    metadata: dict[str, Any],
) -> Path:
    """Écrit le sidecar JSON à côté de l'image WebP canonique.

    ``metadata`` est sérialisée telle quelle : on n'impose pas de schéma
    strict pour rester future-proof (le pipeline BCE y met
    feature/description/image_url/sha256/run_id/fetched_at, un autre
    appelant pourrait y mettre autre chose).
    """
    payload = {
        "eurio_id": eurio_id,
        "role": role,
        "source": source,
        "written_at": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }
    out = sidecar_path(canonical_webp_path)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return out


def read_sidecar(canonical_webp_path: Path) -> dict[str, Any] | None:
    sc = sidecar_path(canonical_webp_path)
    if not sc.is_file():
        return None
    try:
        return json.loads(sc.read_text())
    except json.JSONDecodeError:
        return None


# ── Manifest par run ──────────────────────────────────────────────────────


@dataclass
class RunManifest:
    """Trace d'exécution d'un run BCE — un JSON par run sous ``state/bce_runs/``.

    Contrairement à ``source_runs`` (DB, partagé avec eBay), le manifest
    porte les détails BCE-spécifiques : quelles entries BCE ont matché
    un eurio_id, lesquelles ne matchent pas (debug du matcher), durée
    par étape.
    """

    run_id: str
    started_at: str
    kind: str = "run"   # 'run' | 'dry'
    ended_at: str | None = None
    query: dict[str, Any] = field(default_factory=dict)
    matched: list[dict[str, Any]] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    n_pages_fetched: int = 0
    n_pages_cached: int = 0
    n_downloaded: int = 0
    n_promoted: int = 0
    n_errors: int = 0
    status: str = "running"
    error_summary: str | None = None

    def add_matched(self, *, eurio_id: str, role: str, image_url: str,
                    feature: str, local_path: str) -> None:
        self.matched.append({
            "eurio_id": eurio_id,
            "role": role,
            "image_url": image_url,
            "feature": feature,
            "local_path": local_path,
        })

    def add_unmatched(self, *, country: str, year: int, feature: str,
                      theme_slug: str, reason: str) -> None:
        self.unmatched.append({
            "country": country,
            "year": year,
            "feature": feature,
            "theme_slug": theme_slug,
            "reason": reason,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "query": self.query,
            "n_pages_fetched": self.n_pages_fetched,
            "n_pages_cached": self.n_pages_cached,
            "n_downloaded": self.n_downloaded,
            "n_promoted": self.n_promoted,
            "n_errors": self.n_errors,
            "error_summary": self.error_summary,
            "matched": self.matched,
            "unmatched": self.unmatched,
        }

    def write(self) -> Path:
        BCE_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        out = BCE_RUNS_DIR / f"{self.run_id}.json"
        out.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2))
        return out


def list_run_manifests() -> list[Path]:
    """Tous les manifests de runs BCE, plus récent en premier."""
    if not BCE_RUNS_DIR.is_dir():
        return []
    return sorted(BCE_RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
