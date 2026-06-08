"""CLI de gestion review.db : seed des reviewers, listing, révocation.

Bootstrap / disaster-recovery uniquement — la régie quotidienne passe par la
page admin web (cf. 10-admin-dashboard.md). La logique métier vit dans
review_service.reviewers ; ce CLI n'en est qu'une façade.

Usage (depuis ml/, lease NON requis — review.db est indépendant) :
    python -m review_service.manage add-reviewer --token Paolo42 --name Paolo
    python -m review_service.manage list-reviewers
    python -m review_service.manage deactivate --token Paolo42
    python -m review_service.manage reactivate --token Paolo42

Sur le VPS, pointer REVIEW_DB_PATH vers le review.db de prod avant d'appeler.
cf. docs/work-in-progress/collaborative-review/09-vps-deploy.md
"""

from __future__ import annotations

import argparse

from review_service import reviewers
from review_service.db import ReviewDB


def add_reviewer(token: str, name: str) -> int:
    db = ReviewDB()
    try:
        reviewers.create_reviewer(db, token, name)
    except reviewers.ReviewerExists:
        print(f"reviewer token={token} existe déjà — utilise 'reactivate' pour le réactiver.")
        return 1
    print(f"reviewer '{name}' (token={token}) créé.")
    return 0


def deactivate(token: str) -> int:
    db = ReviewDB()
    try:
        reviewers.revoke_reviewer(db, token)
    except reviewers.ReviewerNotFound:
        print(f"reviewer token={token} introuvable.")
        return 1
    print(f"reviewer token={token} désactivé.")
    return 0


def reactivate(token: str) -> int:
    db = ReviewDB()
    try:
        reviewers.reactivate_reviewer(db, token)
    except reviewers.ReviewerNotFound:
        print(f"reviewer token={token} introuvable.")
        return 1
    print(f"reviewer token={token} réactivé.")
    return 0


def list_reviewers() -> int:
    db = ReviewDB()
    rows = reviewers.list_reviewers(db)
    if not rows:
        print("(aucun reviewer)")
        return 0
    for r in rows:
        flag = "" if r["is_active"] else " [INACTIF]"
        seen = r["last_seen_at"] or "jamais"
        print(
            f"  {r['display_name']:<16} token={r['token']:<16} "
            f"vu={seen} total={r['total']} 7j={r['last7']} lease={r['in_flight']}{flag}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m review_service.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add-reviewer", help="crée un reviewer")
    p_add.add_argument("--token", required=True)
    p_add.add_argument("--name", required=True)
    p_deact = sub.add_parser("deactivate", help="désactive un reviewer")
    p_deact.add_argument("--token", required=True)
    p_react = sub.add_parser("reactivate", help="réactive un reviewer désactivé")
    p_react.add_argument("--token", required=True)
    sub.add_parser("list-reviewers", help="liste les reviewers + stats")
    args = parser.parse_args(argv)

    if args.cmd == "add-reviewer":
        return add_reviewer(args.token, args.name)
    if args.cmd == "deactivate":
        return deactivate(args.token)
    if args.cmd == "reactivate":
        return reactivate(args.token)
    if args.cmd == "list-reviewers":
        return list_reviewers()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
