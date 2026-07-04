"""Réplique read-only de eurio.db pour le calcul (Modèle B — R2 : tirée DU VPS).

Le calcul lourd (scraping/crop/dino/dataset) lit une **copie locale** du canonique
pour garder la vitesse (dedup, prepare) sans round-trips HTTP. Aucune écriture ne
passe par là : les résultats remontent par run-batch
(``client.runbatch.push_run`` → ``POST /ingest/run``).

Deux transports, choisis automatiquement (``--mode auto``, le défaut) :

1. **rsync (préféré)** — ``sqlite3_rsync`` (outil officiel SQLite, fourni par le
   devShell via flake.nix) synchronise la réplique **au niveau page** depuis le
   canonique VPS, base VIVANTE des deux côtés. Ne transfère que les pages qui
   ont changé (~4 Ko / 3 s quand rien n'a bougé, vs 106 Mo en pull complet).
   Transport ssh avec la clé DÉDIÉE ``~/.ssh/eurio_replica`` (sans passphrase,
   utilisable par les timers), restreinte côté VPS par forced command
   (``~/bin/eurio-replica-cmd`` : seul sqlite3_rsync sur le seul eurio.db).
   La réplique reste en WAL — on ne supprime JAMAIS ses sidecars -wal/-shm
   (ils portent des transactions committées).

2. **api (fallback)** — ``GET /db/replica`` + vérif sha (snapshot ``VACUUM
   INTO`` cohérent, cf. ``serving.db_routes``). Utilisé quand sqlite3_rsync ou
   la clé dédiée manquent (machine pas encore provisionnée), ou sur échec rsync.

Cf. docs/work-in-progress/local-sync/replica-auto-sync.md.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from client import http as _http

logger = logging.getLogger(__name__)

_ML_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REPLICA = _ML_ROOT / "state" / "eurio.replica.db"

_REPLICA_PATH = "/db/replica"
_REPLICA_SHA_PATH = "/db/replica/sha"

# Transport rsync — overridables par env, défauts = topologie actuelle.
# Le host est un alias ssh (présent sur Mac ET PC) : hostname/port/user restent
# dans ~/.ssh/config, pas dans le repo. La clé dédiée est passée par-dessus
# l'alias (IdentitiesOnly) → la clé interactive à passphrase n'est pas requise.
_RSYNC_SSH_HOST = os.environ.get("EURIO_REPLICA_SSH_HOST", "serverOimNixDontpanic")
_RSYNC_ORIGIN = os.environ.get(
    "EURIO_REPLICA_ORIGIN", "/opt/eurio/infra/eurio-api/data/eurio.db"
)
_RSYNC_KEY = Path(
    os.environ.get("EURIO_REPLICA_SSH_KEY", "~/.ssh/eurio_replica")
).expanduser()


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


def _write_ssh_wrapper(state_dir: Path) -> Path:
    """Écrit le wrapper ssh du transport rsync (``--ssh`` de sqlite3_rsync ne
    prend qu'un exécutable sans arguments). Idempotent, régénéré à chaque pull."""
    wrapper = state_dir / ".replica_ssh.sh"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'exec ssh -i "{_RSYNC_KEY}" -o IdentitiesOnly=yes -o BatchMode=yes '
        '-o ClearAllForwardings=yes "$@"\n'
    )
    wrapper.chmod(0o755)
    return wrapper


def rsync_available() -> bool:
    """Le transport rsync est utilisable : binaire présent + clé dédiée posée."""
    return shutil.which("sqlite3_rsync") is not None and _RSYNC_KEY.exists()


def pull_replica_rsync(dest: Path | None = None) -> Path:
    """Synchronise la réplique au niveau page depuis le canonique VPS (live).

    Lève ``RuntimeError`` si sqlite3_rsync échoue ou si la réplique résultante
    ne passe pas ``PRAGMA quick_check`` (l'appelant peut retomber sur l'API).
    NE PAS supprimer les sidecars -wal/-shm : la réplique est en WAL, ils
    portent des transactions committées."""
    dest = Path(dest) if dest else _DEFAULT_REPLICA
    dest.parent.mkdir(parents=True, exist_ok=True)
    wrapper = _write_ssh_wrapper(dest.parent)
    cmd = [
        "sqlite3_rsync",
        "--ssh", str(wrapper),
        "--exe", "sqlite3_rsync",  # résolu côté VPS par le forced command
        f"{_RSYNC_SSH_HOST}:{_RSYNC_ORIGIN}",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(
            f"sqlite3_rsync a échoué (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    conn = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
    try:
        check = conn.execute("PRAGMA quick_check").fetchone()[0]
    finally:
        conn.close()
    if check != "ok":
        raise RuntimeError(f"Réplique corrompue post-rsync (quick_check: {check})")
    return dest


def pull_replica_auto(dest: Path | None = None) -> tuple[Path, str]:
    """Transport préféré (rsync incrémental) avec fallback API transparent.

    Retourne ``(chemin, mode_utilisé)``. C'est le point d'entrée des timers
    (launchd/systemd) et du CLI par défaut."""
    if rsync_available():
        try:
            return pull_replica_rsync(dest), "rsync"
        except Exception as exc:  # noqa: BLE001 — fallback assumé
            logger.warning("pull rsync échoué (%s) — fallback API", exc)
    return pull_replica(dest), "api"


def pull_replica(dest: Path | None = None, *, transport=None, force: bool = False) -> Path:
    """Télécharge une réplique read-only de eurio.db depuis le VPS + vérifie le SHA.

    ``transport`` injectable (tests) — objet exposant ``sha()`` et ``download(dest)``.
    Retourne le chemin de la réplique. Lève si le SHA téléchargé ne correspond pas
    au SHA annoncé par le serveur. ``force`` est conservé pour compat CLI (no-op
    désormais : Direction A n'a plus d'ops locales pending à perdre — les writes
    transitent directement au VPS via ``POST /ingest/*``).
    """
    dest = Path(dest) if dest else _DEFAULT_REPLICA
    dest.parent.mkdir(parents=True, exist_ok=True)
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
        help="conservé pour compat CLI — no-op (Direction A n'a plus d'ops locales pending)",
    )
    parser.add_argument(
        "--mode", choices=("auto", "rsync", "api"), default="auto",
        help="transport : rsync incrémental (sqlite3_rsync + clé dédiée), api "
             "(GET /db/replica complet), ou auto = rsync si disponible sinon api "
             "(défaut).",
    )
    args = parser.parse_args(argv)

    dest_arg = Path(args.dest) if args.dest else None
    if args.mode == "rsync":
        dest, mode = pull_replica_rsync(dest_arg), "rsync"
    elif args.mode == "api":
        dest, mode = pull_replica(dest_arg, force=args.force), "api"
    else:
        dest, mode = pull_replica_auto(dest_arg)
    n = _count_coins(dest)
    coins = f"{n} coins" if n is not None else "coins illisibles"
    print(f"réplique read-only → {dest} ({coins}, transport {mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
