"""Seed du canonique au boot du serveur (Modèle B, chunk C4).

Le serveur eurio-api est le **writer unique** de ``eurio.db``, mais le fichier doit
exister avant que ``Store`` ne l'ouvre (sinon il bootstrappe un schéma VIDE). Au
premier démarrage on tire donc la dernière copie depuis MinIO (``eurio-db/eurio.db``,
SHA vérifié), puis le serveur en devient propriétaire (écritures locales sur le
volume ; le backup périodique vers MinIO est le chunk C8).

Idempotent : si le fichier existe déjà localement → on n'écrase RIEN (le local fait
foi côté serveur). Lancé par l'entrypoint AVANT uvicorn.

    python -m serving.bootstrap_canonical   # EURIO_DB_PATH = cible
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_canonical(path: Path) -> str:
    """Garantit la présence de ``eurio.db`` à ``path``. Retourne un statut texte."""
    if path.exists():
        return f"présent localement ({path}) — le serveur en est propriétaire, pas de pull."

    from store import lease  # réutilise le client S3 + helpers du lease

    path.parent.mkdir(parents=True, exist_ok=True)
    client = lease._s3()  # noqa: SLF001
    remote_sha = lease._get_text(client, lease.SHA_KEY)  # noqa: SLF001
    if remote_sha is None:
        return (
            "AUCUNE DB distante dans MinIO (bucket eurio-db) — démarrage sur un schéma "
            "VIDE. Seed le canonique d'abord (push depuis le Mac via ml:db:release)."
        )
    lease._drop_sidecars(path)  # noqa: SLF001
    tmp = path.with_suffix(".db.seed-tmp")
    client.download_file(lease.BUCKET, lease.DB_KEY, str(tmp))
    got = lease._sha256(tmp)  # noqa: SLF001
    if got != remote_sha:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Intégrité seed : sha {got} ≠ attendu {remote_sha}.")
    tmp.replace(path)
    lease._drop_sidecars(path)  # noqa: SLF001
    return f"seedé depuis MinIO ({got[:12]}…) → {path}"


def main() -> int:
    path = Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))
    status = ensure_canonical(path)
    print(f"[bootstrap_canonical] {status}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
