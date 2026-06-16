"""Auth bearer de l'eurio-api (Modèle B, chunk C2).

L'API serveur est le **writer unique** du canonique ; comme l'IP du dev change
(connexions depuis chez des amis, etc.), on n'authentifie pas par IP mais par un
**token bearer applicatif** (table ``api_tokens``, SHA-256 stocké, jamais le clair).
Traefik ne fait que le TLS/routage.

Activation par env ``EURIO_API_AUTH_REQUIRED`` (le local reste **ouvert** par
défaut → aucune friction sur le Mac ; le serveur la met à ``1``). Ce n'est pas un
« dual-mode » du modèle de données, juste la config d'auth dev↔prod.

Gestion des tokens (CLI) :
    python -m serving.auth add-token --name pc     # imprime le token UNE fois
    python -m serving.auth list
    python -m serving.auth revoke --name pc
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from pathlib import Path

from fastapi import Header, HTTPException

_ML_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _ML_ROOT / "state" / "eurio.db"

_store = None  # lié par server.py via bind() ; la CLI ouvre son propre Store.


def bind(store) -> None:
    """Associe le Store partagé (appelé par ``server.py`` au boot)."""
    global _store
    _store = store


def auth_required() -> bool:
    return os.environ.get("EURIO_API_AUTH_REQUIRED", "").lower() in (
        "1", "true", "yes", "on",
    )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ─── Dépendance FastAPI ──────────────────────────────────────────────────────


def require_token(
    authorization: str | None = Header(default=None),
    x_token: str | None = Header(default=None),
) -> str | None:
    """No-op si l'auth est désactivée ; sinon exige un token valide.

    Accepte ``Authorization: Bearer <t>`` ou ``X-Token: <t>``. Retourne le nom du
    token (utile pour l'audit) ou ``None`` (auth off).
    """
    if not auth_required():
        return None
    presented: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    elif x_token:
        presented = x_token.strip()
    if not presented:
        raise HTTPException(status_code=401, detail="token requis")
    if _store is None:
        raise HTTPException(status_code=500, detail="auth non câblée (bind manquant)")
    row = _store._connection().execute(  # noqa: SLF001
        "SELECT name FROM api_tokens WHERE token_sha=? AND revoked_at IS NULL",
        (hash_token(presented),),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="token invalide ou révoqué")
    return row["name"]


# ─── Gestion des tokens ──────────────────────────────────────────────────────


def add_token(conn: sqlite3.Connection, name: str) -> str:
    """Crée un token pour ``name``, stocke son SHA, retourne le secret EN CLAIR
    (à copier immédiatement — il n'est jamais ré-affichable)."""
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO api_tokens (token_sha, name) VALUES (?, ?)",
        (hash_token(token), name),
    )
    return token


def revoke_token(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute(
        "UPDATE api_tokens SET revoked_at=datetime('now') "
        "WHERE name=? AND revoked_at IS NULL",
        (name,),
    )
    return cur.rowcount


def list_tokens(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT name, created_at, revoked_at FROM api_tokens ORDER BY created_at"
    ).fetchall()
    return [dict(r) for r in rows]


def main(argv: list[str] | None = None) -> int:
    import argparse

    from store import Store

    parser = argparse.ArgumentParser(prog="python -m serving.auth", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add-token", help="crée un token (imprimé une fois)")
    p_add.add_argument("--name", required=True)
    p_rev = sub.add_parser("revoke", help="révoque le(s) token(s) d'un nom")
    p_rev.add_argument("--name", required=True)
    sub.add_parser("list", help="liste les tokens (sans le secret)")
    args = parser.parse_args(argv)

    store = Store(_DEFAULT_DB)
    conn = store._connection()  # noqa: SLF001
    if args.cmd == "add-token":
        token = add_token(conn, args.name)
        print(f"Token pour '{args.name}' (copie-le MAINTENANT, non ré-affichable) :")
        print(token)
        return 0
    if args.cmd == "revoke":
        n = revoke_token(conn, args.name)
        print(f"{n} token(s) révoqué(s) pour '{args.name}'.")
        return 0
    if args.cmd == "list":
        for t in list_tokens(conn):
            state = "RÉVOQUÉ" if t["revoked_at"] else "actif"
            print(f"  {t['name']:<16} {state:<8} créé {t['created_at']}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
