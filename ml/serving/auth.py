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


def _grant_owner(email: str) -> int:
    """Break-glass : grant le rôle ``owner`` à un user (auth-redesign C3).

    Trouve l'user par email dans le miroir local. **Ne crée pas** un user
    inexistant — il faut d'abord se logger une fois via OIDC pour que le user
    apparaisse dans le miroir. Sinon : l'opérateur passe par l'UI Authentik
    pour mettre le user dans le groupe ``eurio-owner``, puis re-login.

    Écrit dans ``auth_audit`` (event ``grant_owner.cli``).
    """
    import json as _json
    import time as _time

    db_path = _DEFAULT_DB
    if not db_path.exists():
        # On peut être appelé côté VPS où le path canonique est différent.
        import os as _os
        db_path = Path(_os.environ.get("EURIO_DB_PATH", str(_DEFAULT_DB)))
    if not db_path.exists():
        print(f"ERREUR : DB introuvable à {db_path}", file=__import__("sys").stderr)
        return 2
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT id, name FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            print(
                f"ERREUR : user avec email '{email}' inconnu du miroir local.\n"
                f"  → met l'user dans le groupe 'eurio-owner' côté Authentik et fais un\n"
                f"    premier login OIDC (https://eurio-api.musubi.dev/auth/oidc/login)\n"
                f"    puis relance cette commande.",
                file=__import__("sys").stderr,
            )
            return 3
        user_id, name = row
        conn.execute(
            "INSERT OR IGNORE INTO user_roles(user_id, role) VALUES (?, 'owner')",
            (user_id,),
        )
        now_ms = int(_time.time() * 1000)
        conn.execute(
            "INSERT INTO auth_audit(ts, actor_id, event, target, meta_json) "
            "VALUES (?, NULL, 'grant_owner.cli', ?, ?)",
            (
                now_ms,
                user_id,
                _json.dumps(
                    {"invoked_by": "docker exec", "email": email},
                    separators=(",", ":"),
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"OK : '{name}' ({email}) → grant owner.")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    from store import Store

    parser = argparse.ArgumentParser(prog="python -m serving.auth", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add-token", help="[LEGACY] crée un token machine (deprecated — usage PAT via API)")
    p_add.add_argument("--name", required=True)
    p_rev = sub.add_parser("revoke", help="[LEGACY] révoque le(s) token(s) d'un nom")
    p_rev.add_argument("--name", required=True)
    sub.add_parser("list", help="[LEGACY] liste les tokens (sans le secret)")
    p_grant = sub.add_parser(
        "grant-owner",
        help="break-glass : grant le rôle owner à un user (auth-redesign C3)",
    )
    p_grant.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "grant-owner":
        return _grant_owner(args.email)

    store = Store(_DEFAULT_DB)
    conn = store._connection()  # noqa: SLF001
    if args.cmd == "add-token":
        print(
            "AVERTISSEMENT : `add-token` est deprecated. Crée un PAT via "
            "POST /me/tokens (panel ou curl avec ton cookie OIDC).",
            file=__import__("sys").stderr,
        )
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
