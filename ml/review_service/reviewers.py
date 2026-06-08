"""Logique métier reviewers — partagée par le CLI (manage.py) et les routes
HTTP (/admin/reviewers).

Pure DB, aucune dépendance FastAPI : create / revoke / reactivate / list (+stats).
Le token est À LA FOIS l'identité et le mot de passe (cf. 04-auth.md). La
révocation est un soft-delete (`is_active=0`) — JAMAIS de DELETE : les
`decisions` référencent `reviewer_token` en FK.
cf. docs/work-in-progress/collaborative-review/10-admin-dashboard.md
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from review_service.db import ReviewDB, now_iso


class ReviewerExists(Exception):
    """Le token est déjà pris (collision de PK)."""


class ReviewerNotFound(Exception):
    """Aucun reviewer pour ce token."""


def _seven_days_ago_iso() -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=7)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def create_reviewer(db: ReviewDB, token: str, name: str) -> dict:
    """Crée un reviewer actif. Rejette une collision de token (pas d'upsert)."""
    token = token.strip()
    name = name.strip()
    if not token:
        raise ValueError("token requis")
    if not name:
        raise ValueError("name requis")
    with db.writing() as conn:
        existing = conn.execute(
            "SELECT token FROM reviewers WHERE token = ?", (token,)
        ).fetchone()
        if existing is not None:
            raise ReviewerExists(token)
        conn.execute(
            "INSERT INTO reviewers (token, display_name, created_at) VALUES (?, ?, ?)",
            (token, name, now_iso()),
        )
    return {"token": token, "display_name": name}


def revoke_reviewer(db: ReviewDB, token: str) -> None:
    """Soft-delete : is_active=0. L'ami ne peut plus se logger, ses décisions restent."""
    with db.writing() as conn:
        cur = conn.execute(
            "UPDATE reviewers SET is_active = 0 WHERE token = ?", (token,)
        )
        if cur.rowcount == 0:
            raise ReviewerNotFound(token)


def reactivate_reviewer(db: ReviewDB, token: str) -> None:
    with db.writing() as conn:
        cur = conn.execute(
            "UPDATE reviewers SET is_active = 1 WHERE token = ?", (token,)
        )
        if cur.rowcount == 0:
            raise ReviewerNotFound(token)


def list_reviewers(db: ReviewDB) -> list[dict]:
    """Liste + stats agrégées par reviewer. Actifs récents en haut, fantômes en bas."""
    rows = db.connection().execute(
        """
        SELECT
          r.token, r.display_name, r.is_active, r.created_at, r.last_seen_at,
          (SELECT count(*) FROM decisions d WHERE d.reviewer_token = r.token)
            AS total,
          (SELECT count(*) FROM decisions d
            WHERE d.reviewer_token = r.token AND d.decided_at >= ?)
            AS last7,
          (SELECT count(*) FROM review_items i
            WHERE i.claimed_by = r.token AND i.status = 'claimed')
            AS in_flight
          FROM reviewers r
         ORDER BY (r.last_seen_at IS NULL), r.last_seen_at DESC, r.display_name
        """,
        (_seven_days_ago_iso(),),
    ).fetchall()
    return [
        {
            "token": r["token"],
            "display_name": r["display_name"],
            "is_active": bool(r["is_active"]),
            "created_at": r["created_at"],
            "last_seen_at": r["last_seen_at"],
            "total": r["total"],
            "last7": r["last7"],
            "in_flight": r["in_flight"],
        }
        for r in rows
    ]
