"""Cache de vignettes à durée de vie limitée, paramétré par sa racine.

Extrait de ``serving/benchmark_routes.py`` (le triptyque ``_thumbnail_path`` /
``_ensure_thumbnail`` / ``cleanup_expired_thumbnails``) le jour où un deuxième
appelant en a eu besoin (``scan_corpus_routes``). Le copier aurait été de la
dette : deux TTL à faire dériver, deux gardes de traversée à maintenir, et un
seul des deux nettoyé au boot.

Deux briques, aucune dépendance à un domaine métier :

``safe_child(root, relative)``
    Résout ``relative`` **sous** ``root`` et refuse tout ce qui s'en échappe
    (``..``, chemin absolu, symlink sortant) par un ``HTTPException(400)``.

``ThumbnailCache``
    Vignettes JPEG content-addressed par la **clé logique** (le chemin relatif
    de la source, pas son contenu) : régénérées quand la source est plus
    récente, évincées après ``ttl_seconds``.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

DEFAULT_TTL_SECONDS = 24 * 3600
DEFAULT_SIZE = (256, 256)
DEFAULT_QUALITY = 80


def safe_child(root: Path, relative: str) -> Path:
    """Chemin sous ``root``, ou ``HTTPException(400)``.

    Le refus est **explicite avant résolution** (``..``, chemin absolu) *et*
    **vérifié après** (``relative_to``) : le premier attrape la traversée
    lisible, le second celle qui passe par un symlink.
    """
    if relative.startswith("/") or ".." in relative.replace("\\", "/").split("/"):
        raise HTTPException(status_code=400, detail="Chemin invalide")
    root = Path(root).resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Chemin hors racine") from None
    return target


class ThumbnailCache:
    """Vignettes sur disque sous ``root``, évincées après ``ttl_seconds``."""

    def __init__(
        self,
        root: Path | str,
        *,
        size: tuple[int, int] = DEFAULT_SIZE,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        quality: int = DEFAULT_QUALITY,
    ) -> None:
        self.root = Path(root)
        self.size = size
        self.ttl_seconds = ttl_seconds
        self.quality = quality

    def path_for(self, key: str) -> Path:
        """Emplacement de la vignette pour la clé logique ``key``."""
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        return self.root / f"{digest}.jpg"

    def ensure(self, key: str, src: Path) -> Path:
        """Rend la vignette de ``src``, la (re)générant si besoin.

        ``404`` si la source a disparu, ``500`` si Pillow ne sait pas la lire —
        les deux cas se distinguent, un « thumbnail error » fourre-tout ne
        dirait pas lequel on a.
        """
        src = Path(src)
        if not src.exists():
            raise HTTPException(status_code=404, detail="Image introuvable")
        dst = self.path_for(key)
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            return dst
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(src) as im:
                im = im.convert("RGB")
                im.thumbnail(self.size, Image.LANCZOS)
                im.save(dst, "JPEG", quality=self.quality)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=f"Thumbnail error: {exc}"
            ) from exc
        return dst

    def cleanup_expired(self) -> int:
        """Évince les vignettes plus vieilles que le TTL. Rend le nombre supprimé."""
        if not self.root.exists():
            return 0
        cutoff = time.time() - self.ttl_seconds
        removed = 0
        for entry in self.root.iterdir():
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                try:
                    entry.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed
