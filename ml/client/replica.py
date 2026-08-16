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
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from client import http as _http

logger = logging.getLogger(__name__)

_ML_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REPLICA = _ML_ROOT / "state" / "eurio.replica.db"
_REPLICA_LOCK = "replica.lock"  # verrou partagé thread-serveur ↔ timer systemd

# stderr ssh bénin : `StrictHostKeyChecking=accept-new` écrit UNE ligne de
# warning au 1er contact d'un host (avant que le known_hosts stable soit peuplé).
# Tout le RESTE reste significatif — y compris un refus forced-command produisant
# rc=0 (no-op silencieux : réplique périmée sans erreur).
_BENIGN_STDERR_RE = re.compile(
    r"^\s*Warning: Permanently added .* to the list of known hosts\.\s*$"
)


def _significant_stderr(stderr: str) -> str:
    """Lignes stderr NON bénignes (chaîne vide = rien d'anormal)."""
    sig = [ln for ln in stderr.splitlines() if ln.strip() and not _BENIGN_STDERR_RE.match(ln)]
    return "\n".join(sig)

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
    # known_hosts stable et local au repo : accept-new mémorise la clé host au
    # 1er contact (pas de prompt interactif possible sous BatchMode), puis les
    # pulls suivants sont silencieux — plus de warning host-key sur stderr.
    known_hosts = state_dir / ".replica_known_hosts"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'exec ssh -i "{_RSYNC_KEY}" -o IdentitiesOnly=yes -o BatchMode=yes '
        f'-o StrictHostKeyChecking=accept-new -o "UserKnownHostsFile={known_hosts}" '
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

    # Verrou partagé thread-serveur ↔ timer systemd (même fichier lock) : un seul
    # sqlite3_rsync à la fois, sinon collision (BUSY) sur la réplique. Non
    # bloquant : lock tenu → on SKIP (l'autre pull rafraîchit la vue). SURTOUT
    # pas d'exception ici, sinon pull_replica_auto retomberait sur un download
    # API complet (106 Mo) alors qu'un pull incrémental est déjà en cours.
    lock_fd = open(dest.parent / _REPLICA_LOCK, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.info("réplique : pull déjà en cours (lock tenu) — skip")
        lock_fd.close()
        return dest
    try:
        wrapper = _write_ssh_wrapper(dest.parent)
        cmd = [
            "sqlite3_rsync",
            "--ssh", str(wrapper),
            "--exe", "sqlite3_rsync",  # résolu côté VPS par le forced command
            f"{_RSYNC_SSH_HOST}:{_RSYNC_ORIGIN}",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        # ⚠️ sqlite3_rsync peut sortir rc=0 alors que le bout distant a REFUSÉ
        # (forced command) → no-op silencieux, réplique périmée sans erreur
        # (observé : PC). Un run sain n'écrit RIEN de significatif sur stderr
        # (aucun -v n'est passé) → on échoue sur rc≠0 OU stderr significatif,
        # mais on tolère le warning host-key bénin de accept-new (1er contact),
        # sinon le tout premier pull échouerait à tort.
        significant = _significant_stderr(proc.stderr)
        if proc.returncode != 0 or significant:
            raise RuntimeError(
                f"sqlite3_rsync a échoué (rc={proc.returncode}): "
                f"{significant or proc.stdout.strip()}"
            )
        conn = sqlite3.connect(f"file:{dest}?mode=ro", uri=True)
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            conn.close()
        if check != "ok":
            raise RuntimeError(f"Réplique corrompue post-rsync (quick_check: {check})")
        return dest
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _safe_write_sync_receipt(dest: Path, mode: str) -> None:
    """Enveloppe inconditionnelle : voir la docstring ci-dessous."""
    try:
        _write_sync_receipt(dest, mode)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reçu de synchro non écrit (%s: %s)", exc.__class__.__name__, exc)


def _write_sync_receipt(dest: Path, mode: str) -> None:
    """Note à côté de la réplique quand elle a été synchronisée, et contre quoi.

    Sans ce reçu, la seule mesure de fraîcheur disponible est le mtime du
    fichier — et il ment : un pull rsync qui n'a **rien** à transférer ne le
    touche pas, donc une réplique parfaitement à jour paraît vieille.

    **On n'y met délibérément pas le sha du canonique.** C'était l'idée
    première — comparer l'annonce du serveur au dernier pull à son annonce
    actuelle pour dire « le canonique a bougé depuis ». Mesuré : ce sha change
    en moins de 75 s même sans aucune écriture métier, parce que
    ``pat_tokens.last_used_at`` est mis à jour **à chaque requête
    authentifiée** — y compris celle qui va chercher le sha. Le marqueur est
    auto-invalidant : le mesurer change ce qu'il mesure, et le verdict aurait
    été « en retard » en permanence. Il coûtait en prime un ``VACUUM INTO`` de
    155 Mo au VPS à chaque pull.

    La fraîcheur métier se mesure ailleurs, sur un agrégat qui ne bouge que
    quand la donnée bouge (cf. ``scripts.freshness``).

    Best-effort de bout en bout : un reçu manquant dégrade le diagnostic, il ne
    doit jamais faire échouer un pull qui a réussi. La garde est au **niveau de
    la fonction entière**, pas seulement autour des I/O : une faute de frappe
    dans la construction du reçu a fait échouer un pull par ailleurs réussi —
    un diagnostic ne doit pas pouvoir casser ce qu'il diagnostique.
    """
    receipt = {
        "pulled_at": time.time(),
        "pulled_at_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "transport": mode,
        "size_bytes": dest.stat().st_size if dest.exists() else None,
    }
    try:
        path = dest.with_suffix(dest.suffix + ".sync.json")
        path.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("reçu de synchro non écrit (%s)", exc)


def pull_replica_auto(dest: Path | None = None) -> tuple[Path, str]:
    """Transport préféré (rsync incrémental) avec fallback API transparent.

    Retourne ``(chemin, mode_utilisé)``. C'est le point d'entrée des timers
    (launchd/systemd) et du CLI par défaut."""
    if rsync_available():
        try:
            path = pull_replica_rsync(dest)
            _safe_write_sync_receipt(path, "rsync")
            return path, "rsync"
        except Exception as exc:  # noqa: BLE001 — fallback assumé
            logger.warning("pull rsync échoué (%s) — fallback API", exc)
    path = pull_replica(dest)
    _safe_write_sync_receipt(path, "api")
    return path, "api"


def pull_replica(dest: Path | None = None, *, transport=None, force: bool = False) -> Path:
    """Télécharge une réplique read-only de eurio.db depuis le VPS + vérifie le SHA.

    ``transport`` injectable (tests) — objet exposant ``sha()`` et ``download(dest)``.
    Retourne le chemin de la réplique. ``force`` est conservé pour compat CLI (no-op
    désormais : Direction A n'a plus d'ops locales pending à perdre — les writes
    transitent directement au VPS via ``POST /ingest/*``).

    Intégrité : l'en-tête ``X-Eurio-DB-Sha256`` du download EST le sha du fichier
    exactement servi (self-consistant, cf. ``serving.db_routes``) → c'est
    l'autorité, immunisée au rebuild du snapshot serveur (TTL) entre deux
    requêtes. Un désaccord en-tête↔contenu = transfert tronqué → 1 retry.
    ``GET /db/replica/sha`` n'est plus qu'un filet pour les serveurs sans en-tête.
    """
    dest = Path(dest) if dest else _DEFAULT_REPLICA
    dest.parent.mkdir(parents=True, exist_ok=True)
    transport = transport or _ApiTransport()

    _drop_sidecars(dest)
    tmp = dest.with_suffix(".db.replica-tmp")
    header_sha = ""
    got = ""
    for _attempt in range(2):
        header_sha = transport.download(tmp) or ""
        got = _sha256(tmp)
        if not header_sha or header_sha == got:
            break  # pas d'en-tête (vieux serveur) OU transfert cohérent
        logger.warning(
            "réplique : en-tête sha %s ≠ contenu %s — transfert corrompu, retry",
            header_sha, got,
        )
        tmp.unlink(missing_ok=True)
    else:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Intégrité réplique : en-tête {header_sha} ≠ contenu {got} après retry."
        )

    if not header_sha:
        # Serveur sans en-tête : /sha comme autorité dégradée (course TTL possible).
        expected_sha = transport.sha()
        if not expected_sha:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                "Ni en-tête X-Eurio-DB-Sha256 ni GET /db/replica/sha — "
                "canonique indisponible ?"
            )
        if got != expected_sha:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"Intégrité réplique : sha {got} ≠ attendu {expected_sha}."
            )

    tmp.replace(dest)
    _drop_sidecars(dest)
    return dest


def start_autopull_thread(
    dest: Path | None = None, *, interval_s: int | None = None, stop_event=None,
):
    """Rafraîchit la réplique en tâche de fond (thread daemon), toutes les
    ``interval_s`` secondes (défaut ``EURIO_REPLICA_AUTOPULL_INTERVAL`` ou 120).

    Démarré par le serveur ML local (``serving/server.py``) : tant que tu
    travailles (serveur :8042 up), la réplique reste fraîche sans commande.
    Choisi plutôt qu'un agent launchd sur macOS : TCC interdit à launchd de
    LIRE ~/Documents (le repo), alors que le serveur hérite des droits du
    terminal. Sur le PC NixOS, le timer systemd user double ce thread (couvre
    les périodes serveur éteint).

    Gates : ``EURIO_REPLICA_AUTOPULL=0`` désactive ; sans transport rsync
    (binaire/clé absents) on ne démarre PAS (un GET /db/replica complet toutes
    les 2 min serait un gâchis — le fallback API reste réservé aux pulls
    manuels). Retourne le Thread démarré, ou None si gated. ``stop_event``
    (threading.Event) injectable pour les tests."""
    import threading

    if os.environ.get("EURIO_REPLICA_AUTOPULL", "").strip() == "0":
        logger.info("réplique autopull désactivé (EURIO_REPLICA_AUTOPULL=0)")
        return None
    if not rsync_available():
        logger.info(
            "réplique autopull non démarré : transport rsync indisponible "
            "(sqlite3_rsync ou %s manquant)", _RSYNC_KEY,
        )
        return None
    interval = interval_s or int(
        os.environ.get("EURIO_REPLICA_AUTOPULL_INTERVAL", "120")
    )
    stop = stop_event or threading.Event()

    def _loop() -> None:
        while not stop.is_set():
            try:
                pull_replica_rsync(dest)
                stamp = (Path(dest) if dest else _DEFAULT_REPLICA).parent
                (stamp / ".replica-last-pull").touch()
            except Exception as exc:  # noqa: BLE001 — le thread ne meurt jamais
                logger.warning("réplique autopull : pull échoué (%s)", exc)
            stop.wait(interval)

    t = threading.Thread(target=_loop, name="eurio-replica-autopull", daemon=True)
    t.stop_event = stop  # exposé pour les tests / arrêt propre
    t.start()
    logger.info("réplique autopull démarré (rsync, toutes les %ds)", interval)
    return t


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
    parser.add_argument(
        "--status", action="store_true",
        help="n'effectue AUCUN pull : affiche l'âge de la réplique locale "
             "(fraîcheur) et sort 0 si elle existe, 1 sinon.",
    )
    args = parser.parse_args(argv)

    if args.status:
        import time as _time

        dest = Path(args.dest) if args.dest else _DEFAULT_REPLICA
        if not dest.exists():
            print(f"réplique absente : {dest}")
            return 1
        age = int(_time.time() - dest.stat().st_mtime)
        n = _count_coins(dest)
        coins = f"{n} coins" if n is not None else "coins illisibles"
        stamp = dest.parent / ".replica-last-pull"
        checked = (
            f", dernier pull réussi il y a {int(_time.time() - stamp.stat().st_mtime)}s"
            if stamp.exists() else ""
        )
        print(f"réplique {dest} — dernier changement il y a {age}s ({coins}{checked})")
        return 0

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
