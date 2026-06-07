"""Lease cross-machine de ``eurio.db`` via MinIO (refacto ML chunk 6).

La copie canonique de ``eurio.db`` vit dans le bucket MinIO ``eurio-db``. Une
seule machine à la fois détient un verrou (objet ``eurio.db.lock``, créé
atomiquement via ``PutObject(IfNoneMatch='*')``). Workflow séquentiel
Mac→PC→Mac :

    go-task ml:db:acquire    # pose le verrou + pull la DB
    …travail local en sqlite3 (zéro perte de compat)…
    go-task ml:db:release    # push la DB + retire le verrou

Le driver ``store/connection.py`` reste du ``sqlite3`` pur — le lease est une
couche opérationnelle au-dessus, jamais dans le chemin de requête. Les tests
(DB jetables) n'ont jamais besoin du lease.

Doctrine (cf. AskUserQuestion chunk 6) : **manuel** (pas d'acquire/release auto
au boot ; le startup API ne fait qu'avertir) et **steal manuel** (un verrou ne
se libère jamais tout seul — ``db:steal --force`` après un crash).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BUCKET = os.environ.get("EURIO_DB_BUCKET", "eurio-db")
DB_KEY = "eurio.db"
LOCK_KEY = "eurio.db.lock"
SHA_KEY = "eurio.db.sha256"

_ML_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ML_ROOT / "state" / "eurio.db"
_MARKER = _ML_ROOT / "state" / ".eurio.db.lease"


def _s3():
    """Client boto3 partagé avec la couche images (mêmes creds ``MINIO_*``)."""
    from storage import _client  # noqa: PLC0415

    return _client()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _identity() -> dict:
    return {"holder_host": socket.gethostname(), "pid": os.getpid()}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_not_found(exc) -> bool:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    return code in ("NoSuchKey", "404", "NoSuchBucket")


def _is_precondition_failed(exc) -> bool:
    resp = getattr(exc, "response", {})
    code = resp.get("Error", {}).get("Code", "")
    status = resp.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in ("PreconditionFailed", "412") or status == 412


def _get_json(client, key: str) -> dict | None:
    from botocore.exceptions import ClientError  # noqa: PLC0415

    try:
        obj = client.get_object(Bucket=BUCKET, Key=key)
    except ClientError as exc:
        if _is_not_found(exc):
            return None
        raise
    return json.loads(obj["Body"].read())


def _get_text(client, key: str) -> str | None:
    from botocore.exceptions import ClientError  # noqa: PLC0415

    try:
        obj = client.get_object(Bucket=BUCKET, Key=key)
    except ClientError as exc:
        if _is_not_found(exc):
            return None
        raise
    return obj["Body"].read().decode().strip()


def _read_marker() -> dict | None:
    if not _MARKER.exists():
        return None
    try:
        return json.loads(_MARKER.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _i_hold(lock: dict | None) -> bool:
    """Vrai si le verrou distant ET le marqueur local désignent cette machine."""
    marker = _read_marker()
    me = socket.gethostname()
    return bool(
        lock
        and marker
        and lock.get("holder_host") == me
        and marker.get("holder_host") == me
    )


def _wal_checkpoint(db: Path) -> None:
    """Replie le WAL dans le fichier principal pour ne pousser qu'un fichier."""
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def _drop_sidecars(db: Path) -> None:
    """Supprime -wal/-shm : un WAL périmé réappliqué sur une DB fraîchement
    pull-ée corromprait la base. À appeler avant/après remplacement du fichier."""
    for suffix in ("-wal", "-shm"):
        sidecar = db.with_name(db.name + suffix)
        if sidecar.exists():
            sidecar.unlink()


# ─── Commandes ────────────────────────────────────────────────────────────


def status() -> int:
    client = _s3()
    lock = _get_json(client, LOCK_KEY)
    remote_sha = _get_text(client, SHA_KEY)
    local_sha = _sha256(_DB_PATH) if _DB_PATH.exists() else None
    me = socket.gethostname()

    if lock is None:
        print(f"verrou : LIBRE  (bucket {BUCKET})")
    else:
        held_by_me = " ← CETTE MACHINE" if lock.get("holder_host") == me else ""
        print(
            f"verrou : TENU par {lock.get('holder_host')} "
            f"(pid {lock.get('pid')}, depuis {lock.get('acquired_at')})"
            f"{held_by_me}"
        )
        if lock.get("note"):
            print(f"  note : {lock['note']}")
    print(f"sha distant : {remote_sha or '∅'}")
    print(f"sha local   : {local_sha or '∅ (pas de eurio.db local)'}")
    if remote_sha and local_sha:
        print("  → " + ("À JOUR" if remote_sha == local_sha else "DIVERGENT"))
    print(f"je tiens le lease : {'oui' if _i_hold(lock) else 'non'}")
    return 0


def acquire(note: str | None = None) -> int:
    from botocore.exceptions import ClientError  # noqa: PLC0415

    client = _s3()
    lock = _get_json(client, LOCK_KEY)
    if _i_hold(lock):
        print("Déjà détenu par cette machine — rien à faire (travail en cours).")
        return 0

    payload = {**_identity(), "acquired_at": _now(), "note": note}
    try:
        client.put_object(
            Bucket=BUCKET,
            Key=LOCK_KEY,
            Body=json.dumps(payload).encode(),
            IfNoneMatch="*",  # création atomique : échoue si le verrou existe
        )
    except ClientError as exc:
        if _is_precondition_failed(exc):
            held = _get_json(client, LOCK_KEY) or {}
            print(
                f"REFUSÉ : verrou tenu par {held.get('holder_host')} "
                f"(pid {held.get('pid')}, depuis {held.get('acquired_at')}).",
                file=sys.stderr,
            )
            print("  → attends sa libération, ou `go-task ml:db:steal -- --force` "
                  "si la machine a crashé.", file=sys.stderr)
            return 2
        raise

    # Verrou posé : pull la DB (skip si déjà identique au distant).
    remote_sha = _get_text(client, SHA_KEY)
    local_sha = _sha256(_DB_PATH) if _DB_PATH.exists() else None
    if remote_sha is None:
        print("Verrou posé. Aucune DB distante (seed initial requis côté VPS) — "
              "le eurio.db local fera foi au prochain release.")
    elif remote_sha == local_sha:
        print("Verrou posé. eurio.db local déjà à jour (sha identique) — pas de pull.")
    else:
        print(f"Verrou posé. Pull eurio.db ({BUCKET}/{DB_KEY})…")
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _drop_sidecars(_DB_PATH)
        tmp = _DB_PATH.with_suffix(".db.pull-tmp")
        client.download_file(BUCKET, DB_KEY, str(tmp))
        got = _sha256(tmp)
        if got != remote_sha:
            tmp.unlink(missing_ok=True)
            print(f"ÉCHEC intégrité : sha pull {got} ≠ attendu {remote_sha}. "
                  "Verrou conservé, DB locale intacte.", file=sys.stderr)
            return 3
        tmp.replace(_DB_PATH)
        _drop_sidecars(_DB_PATH)
        print(f"  OK ({got[:12]}…).")

    _MARKER.write_text(json.dumps({**_identity(), "acquired_at": payload["acquired_at"]}))
    print("Lease acquis. `go-task ml:db:release` une fois terminé.")
    return 0


def release() -> int:
    client = _s3()
    lock = _get_json(client, LOCK_KEY)
    if not _i_hold(lock):
        holder = (lock or {}).get("holder_host", "personne")
        print(f"REFUSÉ : cette machine ne tient pas le lease (tenu par {holder}). "
              "Rien poussé.", file=sys.stderr)
        return 2
    if not _DB_PATH.exists():
        print(f"REFUSÉ : {_DB_PATH} introuvable — rien à pousser.", file=sys.stderr)
        return 3

    print("Checkpoint WAL…")
    _wal_checkpoint(_DB_PATH)
    sha = _sha256(_DB_PATH)
    print(f"Push eurio.db ({sha[:12]}…) → {BUCKET}/{DB_KEY}…")
    client.upload_file(str(_DB_PATH), BUCKET, DB_KEY)
    client.put_object(Bucket=BUCKET, Key=SHA_KEY, Body=sha.encode())
    client.delete_object(Bucket=BUCKET, Key=LOCK_KEY)
    _MARKER.unlink(missing_ok=True)
    print("Lease relâché. La DB distante fait désormais foi.")
    return 0


def steal(force: bool = False) -> int:
    client = _s3()
    lock = _get_json(client, LOCK_KEY)
    if lock is None:
        print("Aucun verrou à voler (déjà libre).")
        return 0
    print(f"Verrou tenu par {lock.get('holder_host')} (pid {lock.get('pid')}, "
          f"depuis {lock.get('acquired_at')}).")
    if not force:
        print("Refus sans --force. Vérifie que la machine a bien crashé "
              "(travail distant non poussé = PERDU), puis relance avec --force.",
              file=sys.stderr)
        return 2
    client.delete_object(Bucket=BUCKET, Key=LOCK_KEY)
    print("Verrou supprimé. Le prochain `db:acquire` repartira du dernier push distant.")
    return 0


def startup_warnings() -> list[str]:
    """Avertissements best-effort pour le boot de l'API (jamais bloquant).

    Doctrine manuelle : on n'acquiert/relâche rien ici, on **prévient** juste si
    un autre tient le verrou ou si la copie locale diverge du distant. Toute
    erreur (MinIO injoignable, creds absents en CI/headless) → liste vide,
    silencieusement : pas de bruit quand on bosse hors-ligne.
    """
    try:
        client = _s3()
        lock = _get_json(client, LOCK_KEY)
        remote_sha = _get_text(client, SHA_KEY)
    except Exception:  # noqa: BLE001
        return []
    local_sha = _sha256(_DB_PATH) if _DB_PATH.exists() else None
    me = socket.gethostname()
    warnings: list[str] = []
    if lock and lock.get("holder_host") != me:
        warnings.append(
            f"eurio.db : verrou tenu par {lock.get('holder_host')} depuis "
            f"{lock.get('acquired_at')} — tes écritures locales ne seront pas "
            "synchronisées (lease manuel)."
        )
    if (
        remote_sha
        and local_sha
        and remote_sha != local_sha
        and not _i_hold(lock)
    ):
        warnings.append(
            "eurio.db : la copie locale diverge du distant et tu ne tiens pas le "
            "lease — `go-task ml:db:status` puis `ml:db:acquire` pour resynchroniser."
        )
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m store.lease", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="qui tient le verrou, sha local vs distant")
    p_acq = sub.add_parser("acquire", help="pose le verrou + pull la DB")
    p_acq.add_argument("--note", default=None, help="note libre (ex. 'training PC')")
    sub.add_parser("release", help="push la DB + retire le verrou")
    p_steal = sub.add_parser("steal", help="supprime un verrou périmé (crash)")
    p_steal.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        return status()
    if args.cmd == "acquire":
        return acquire(note=args.note)
    if args.cmd == "release":
        return release()
    if args.cmd == "steal":
        return steal(force=args.force)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
