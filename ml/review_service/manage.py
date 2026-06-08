"""CLI de gestion review.db : seed des reviewers, listing.

Usage (depuis ml/, lease NON requis — review.db est indépendant) :
    python -m review_service.manage add-reviewer --token Paolo42 --name Paolo
    python -m review_service.manage list-reviewers
    python -m review_service.manage deactivate --token Paolo42

Sur le VPS, pointer REVIEW_DB_PATH vers le review.db de prod avant d'appeler.
cf. docs/work-in-progress/collaborative-review/09-vps-deploy.md
"""

from __future__ import annotations

import argparse

from review_service.db import ReviewDB, now_iso


def add_reviewer(token: str, name: str) -> int:
    db = ReviewDB()
    with db.writing() as conn:
        conn.execute(
            "INSERT INTO reviewers (token, display_name, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(token) DO UPDATE SET display_name = excluded.display_name, "
            "is_active = 1",
            (token, name, now_iso()),
        )
    print(f"reviewer '{name}' (token={token}) ajouté/activé.")
    return 0


def deactivate(token: str) -> int:
    db = ReviewDB()
    with db.writing() as conn:
        conn.execute("UPDATE reviewers SET is_active = 0 WHERE token = ?", (token,))
    print(f"reviewer token={token} désactivé.")
    return 0


def list_reviewers() -> int:
    db = ReviewDB()
    rows = db.connection().execute(
        "SELECT token, display_name, is_active, last_seen_at FROM reviewers ORDER BY display_name"
    ).fetchall()
    if not rows:
        print("(aucun reviewer)")
        return 0
    for r in rows:
        flag = "" if r["is_active"] else " [INACTIF]"
        seen = r["last_seen_at"] or "jamais"
        print(f"  {r['display_name']:<16} token={r['token']:<16} vu={seen}{flag}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m review_service.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add-reviewer", help="ajoute/réactive un reviewer")
    p_add.add_argument("--token", required=True)
    p_add.add_argument("--name", required=True)
    p_deact = sub.add_parser("deactivate", help="désactive un reviewer")
    p_deact.add_argument("--token", required=True)
    sub.add_parser("list-reviewers", help="liste les reviewers")
    args = parser.parse_args(argv)

    if args.cmd == "add-reviewer":
        return add_reviewer(args.token, args.name)
    if args.cmd == "deactivate":
        return deactivate(args.token)
    if args.cmd == "list-reviewers":
        return list_reviewers()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
