"""Réplique read-only de eurio.db pour le calcul (Modèle B — R2 : tirée DU VPS).

Le calcul lourd (scraping/crop/dino/dataset) lit une **copie locale** du canonique
pour garder la vitesse (dedup, prepare) sans round-trips HTTP. On tire la réplique
**directement du writer unique** via l'API VPS (``GET /db/replica`` + son sha), on
vérifie l'intégrité, et c'est tout — **plus de détour MinIO** (le bucket `eurio-db`
+ le lease Model A sont retirés en R2 ; MinIO ne garde que les images). Aucune
écriture ne passe par là : les résultats remontent par run-batch
(``client.runbatch.push_run`` → ``POST /ingest/run``).

Le serveur sert un snapshot **cohérent** (``VACUUM INTO`` sous WAL, cf.
``serving.db_routes``) — la réplique reflète l'état frais du canonique au pull.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path

from client import http as _http

_ML_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REPLICA = _ML_ROOT / "state" / "eurio.replica.db"

_REPLICA_PATH = "/db/replica"
_REPLICA_SHA_PATH = "/db/replica/sha"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _drop_sidecars(db: Path) -> None:
    """Supprime -wal/-shm : un WAL périmé réappliqué sur une DB fraîchement
    pull-ée corromprait la base. À appeler avant/après remplacement du fichier."""
    for suffix in ("-wal", "-shm"):
        sidecar = db.with_name(db.name + suffix)
        if sidecar.exists():
            sidecar.unlink()


class _ApiTransport:
    """Transport HTTP par défaut : tire la réplique de l'API VPS (PAT bearer)."""

    def sha(self) -> str | None:
        return _http.get_json(_REPLICA_SHA_PATH).get("sha")

    def download(self, dest: Path) -> str | None:
        # Retourne le sha annoncé par l'en-tête (X-Eurio-DB-Sha256) s'il est présent.
        return _http.download(_REPLICA_PATH, dest) or None


def _pending_ops(db: Path) -> int:
    """Ops locales non poussées (sync_outbox pending) — 0 si table/DB absente."""
    if not db.exists():
        return 0
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM sync_outbox WHERE status='pending'"
            ).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def pull_replica(dest: Path | None = None, *, transport=None, force: bool = False) -> Path:
    """Télécharge une réplique read-only de eurio.db depuis le VPS + vérifie le SHA.

    ``transport`` injectable (tests) — objet exposant ``sha()`` et ``download(dest)``.
    Retourne le chemin de la réplique. Lève si le SHA téléchargé ne correspond pas
    au SHA annoncé par le serveur, OU si le fichier cible contient des events de
    sync non poussés (l'écraser les perdrait — ``go-task ml:db:sync`` d'abord ;
    ``force=True`` outrepasse en connaissance de cause).
    """
    dest = Path(dest) if dest else _DEFAULT_REPLICA
    dest.parent.mkdir(parents=True, exist_ok=True)
    pending = _pending_ops(dest)
    if pending and not force:
        raise RuntimeError(
            f"{dest} contient {pending} op(s) de sync non poussée(s) — les écraser "
            "les perdrait. Lance `go-task ml:db:sync` d'abord (ou --force)."
        )
    transport = transport or _ApiTransport()

    expected_sha = transport.sha()
    if not expected_sha:
        raise RuntimeError(
            "Le serveur n'a pas renvoyé de sha de réplique (GET /db/replica/sha) — "
            "canonique indisponible ?"
        )
    _drop_sidecars(dest)
    tmp = dest.with_suffix(".db.replica-tmp")
    header_sha = transport.download(tmp)
    got = _sha256(tmp)
    # Vérif contre le sha du endpoint /sha (source d'autorité) ET, si fourni,
    # contre l'en-tête du download (cohérence du même snapshot servi).
    if got != expected_sha or (header_sha and header_sha != got):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Intégrité réplique : sha {got} ≠ attendu {expected_sha}"
            + (f" (en-tête download {header_sha})" if header_sha else "")
            + "."
        )
    tmp.replace(dest)
    _drop_sidecars(dest)
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
    parser.add_argument(
        "--force", action="store_true",
        help="écrase même si des ops de sync locales ne sont pas poussées",
    )
    args = parser.parse_args(argv)

    dest = pull_replica(Path(args.dest) if args.dest else None, force=args.force)
    n = _count_coins(dest)
    coins = f"{n} coins" if n is not None else "coins illisibles"
    print(f"réplique read-only → {dest} ({coins})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
