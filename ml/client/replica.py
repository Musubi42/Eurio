"""Réplique read-only de eurio.db pour le calcul (Modèle B, chunk C3).

Le calcul lourd (scraping/crop/dino/dataset) lit une **copie locale** du canonique
pour garder la vitesse (dedup, prepare) sans round-trips HTTP. On tire l'objet
``eurio-db/eurio.db`` depuis MinIO **sans poser de lease** (lecture seule pure) et
on vérifie son SHA. Aucune écriture ne passe par là : les résultats remontent par
run-batch (``client.runbatch.push_run``).

NB : sous Modèle A la copie MinIO est le canonique ; après le cutover (C8) elle
devient le backup que le serveur pousse. Si on veut une réplique strictement
fraîche post-cutover, on ajoutera un ``GET /db/snapshot`` côté serveur (online
backup) — pour l'instant la copie MinIO suffit (l'ingest dédup par clé naturelle).
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from store import lease as _lease

_DEFAULT_REPLICA = _lease._ML_ROOT / "state" / "eurio.replica.db"


def pull_replica(dest: Path | None = None, *, client=None) -> Path:
    """Télécharge une réplique read-only de eurio.db depuis MinIO + vérifie le SHA.

    ``client`` injectable (tests). Retourne le chemin de la réplique. Lève si le
    SHA téléchargé ne correspond pas au SHA distant, ou si aucune DB distante.
    """
    dest = Path(dest) if dest else _DEFAULT_REPLICA
    dest.parent.mkdir(parents=True, exist_ok=True)
    client = client or _lease._s3()

    remote_sha = _lease._get_text(client, _lease.SHA_KEY)
    if remote_sha is None:
        raise RuntimeError(
            "Aucune DB distante dans MinIO (bucket eurio-db) — rien à répliquer."
        )
    _lease._drop_sidecars(dest)
    tmp = dest.with_suffix(".db.replica-tmp")
    client.download_file(_lease.BUCKET, _lease.DB_KEY, str(tmp))
    got = _lease._sha256(tmp)
    if got != remote_sha:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Intégrité réplique : sha {got} ≠ attendu {remote_sha}.")
    tmp.replace(dest)
    _lease._drop_sidecars(dest)
    return dest


def _count_coins(db: Path) -> int | None:
    """Compte les lignes de ``coins`` dans la réplique (confirmation post-pull)."""
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT count(*) FROM coins").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m client.replica", description=__doc__
    )
    parser.add_argument(
        "--dest",
        default=None,
        help=f"chemin de la réplique (défaut : {_DEFAULT_REPLICA})",
    )
    args = parser.parse_args(argv)

    dest = pull_replica(Path(args.dest) if args.dest else None)
    n = _count_coins(dest)
    coins = f"{n} coins" if n is not None else "coins illisibles"
    print(f"réplique read-only → {dest} ({coins})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
