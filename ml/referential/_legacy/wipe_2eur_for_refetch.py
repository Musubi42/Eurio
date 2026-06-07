"""Wipe greenfield 2€ pour le refetch Numista propre.

Voir docs/research/numista-clean-refetch-kickoff.md §7.1 et
docs/research/numista-clean-refetch-progress.md.

DESTRUCTIF. `--dry-run` par défaut. `--apply` requiert confirmation explicite.

Stratégie : DELETE FROM coins WHERE face_value = 2.0. La cascade FK supprime
automatiquement variants / mint_releases / source_refs / market_prices /
embeddings / confusion_map / source_observations. Les FK RESTRICT
(user_collections) et NO ACTION (set_members) sont pré-vérifiées : si la query
retourne > 0 rows on STOP.

Storage Supabase `coin-images/{eurio_id}/*` n'est pas FK-tied : avec
`--wipe-storage` on supprime aussi les dossiers correspondants. Sinon les
images restent en orphelines (innocuous, seront overwrite au refetch).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from serving.supabase_client import SupabaseClient, load_env  # noqa: E402


SNAPSHOT_PATH = ML_DIR / "datasets" / "wipe_2eur_dryrun.json"


def get_counts(sb: SupabaseClient) -> dict:
    """Compute the dependency counts that will be wiped."""
    rest_base = sb.rest_base
    # We use a single SQL via PostgREST's rpc would require a function — we
    # fall back to N HEAD-count requests. Cheap, the table is small.
    def cnt(table: str, params: dict) -> int:
        return sb.count(table, params=params)

    # Fetch 2€ eurio_ids
    coins_2eur = sb.query(
        "coins",
        params={
            "select": "eurio_id,country,is_commemorative,needs_review",
            "face_value": "eq.2.0",
        },
    )
    eurio_ids = [c["eurio_id"] for c in coins_2eur]
    # PostgREST in.(…) syntax has URL-length limits ~ 4k chars. With 616 ids
    # this is borderline. We chunk the in() filter.
    def cnt_with_in(table: str, col: str, ids: list[str], extra: dict | None = None) -> int:
        total = 0
        for i in range(0, len(ids), 200):
            chunk = ids[i:i+200]
            p = {col: f"in.({','.join(chunk)})"}
            if extra:
                p.update(extra)
            total += cnt(table, p)
        return total

    return {
        "coins_2eur": len(coins_2eur),
        "commemo_2eur": sum(1 for c in coins_2eur if c.get("is_commemorative")),
        "standard_2eur": sum(1 for c in coins_2eur if not c.get("is_commemorative")),
        "needs_review_2eur": sum(1 for c in coins_2eur if c.get("needs_review")),
        "by_country": _by_country(coins_2eur),
        "variants": cnt_with_in("coin_variants", "parent_type_id", eurio_ids),
        "mint_releases": cnt_with_in("coin_mint_releases", "parent_type_id", eurio_ids),
        "source_refs_total": cnt_with_in("coin_source_refs", "coin_type_id", eurio_ids),
        "source_refs_numista": cnt_with_in(
            "coin_source_refs", "coin_type_id", eurio_ids, {"source": "eq.numista"}
        ),
        "market_prices": cnt_with_in("coin_market_prices", "eurio_id", eurio_ids),
        "embeddings": cnt_with_in("coin_embeddings", "eurio_id", eurio_ids),
        "confusion_map": cnt_with_in("coin_confusion_map", "eurio_id", eurio_ids),
        "user_collections": cnt_with_in("user_collections", "eurio_id", eurio_ids),
        "set_members": cnt_with_in("set_members", "eurio_id", eurio_ids),
    }


def _by_country(coins: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in coins:
        k = c.get("country") or "?"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def print_counts(counts: dict) -> None:
    print(f"  coins 2€              : {counts['coins_2eur']}")
    print(f"    └ commémo           : {counts['commemo_2eur']}")
    print(f"    └ standard          : {counts['standard_2eur']}")
    print(f"    └ needs_review      : {counts['needs_review_2eur']}")
    print(f"  coin_variants         : {counts['variants']}    [CASCADE]")
    print(f"  coin_mint_releases    : {counts['mint_releases']}    [CASCADE]")
    print(f"  coin_source_refs      : {counts['source_refs_total']}    [CASCADE]")
    print(f"    └ numista           : {counts['source_refs_numista']}")
    print(f"    └ autres            : {counts['source_refs_total'] - counts['source_refs_numista']}")
    print(f"  coin_market_prices    : {counts['market_prices']}    [CASCADE]")
    print(f"  coin_embeddings       : {counts['embeddings']}    [CASCADE]")
    print(f"  coin_confusion_map    : {counts['confusion_map']}    [CASCADE]")
    print(f"  user_collections      : {counts['user_collections']}    [RESTRICT — STOP si > 0]")
    print(f"  set_members           : {counts['set_members']}    [NO ACTION — STOP si > 0]")


def preflight_blockers(counts: dict) -> list[str]:
    """Return list of blockers preventing wipe."""
    blockers = []
    if counts["user_collections"] > 0:
        blockers.append(
            f"user_collections référence {counts['user_collections']} coins 2€ "
            "(FK RESTRICT). Stoppe le wipe."
        )
    if counts["set_members"] > 0:
        blockers.append(
            f"set_members référence {counts['set_members']} coins 2€ "
            "(FK NO ACTION). Stoppe le wipe."
        )
    return blockers


def do_wipe(sb: SupabaseClient) -> int:
    """DELETE FROM coins WHERE face_value = 2.0. Returns rows deleted."""
    deleted = sb.query(
        "coins",
        params={"select": "eurio_id", "face_value": "eq.2.0"},
    )
    sb.delete("coins", filters={"face_value": "eq.2.0"})
    return len(deleted)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Compte sans rien supprimer")
    g.add_argument("--apply", action="store_true", help="DELETE en base (irréversible)")
    parser.add_argument(
        "--wipe-storage", action="store_true",
        help="Aussi supprimer coin-images/{eurio_id}/ pour chaque coin 2€",
    )
    parser.add_argument(
        "--yes-i-understand", action="store_true",
        help="Requis pour --apply : confirme avoir lu le dry-run",
    )
    args = parser.parse_args()

    env = load_env()
    sb = SupabaseClient(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"])

    print("═" * 60)
    print(f"WIPE 2€ — {'DRY RUN' if args.dry_run else 'APPLY'} @ {datetime.now(timezone.utc).isoformat()}")
    print("═" * 60)

    print("\n▶ Pré-vol : counts dépendances cascade")
    counts = get_counts(sb)
    print_counts(counts)

    print("\n▶ Répartition par pays (top 10) :")
    by_country = counts["by_country"]
    for k, v in sorted(by_country.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {k or '?':<6} : {v}")

    blockers = preflight_blockers(counts)
    if blockers:
        print("\n⛔ BLOCKERS :")
        for b in blockers:
            print(f"    - {b}")
        return 2

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "dry-run" if args.dry_run else "apply",
        "counts": counts,
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"\n✓ Snapshot écrit : {SNAPSHOT_PATH.relative_to(ML_DIR.parent)}")

    if args.dry_run:
        print("\n--dry-run : rien n'est supprimé. Re-run avec --apply --yes-i-understand pour exécuter.")
        return 0

    if not args.yes_i_understand:
        print("\n⛔ --apply requiert aussi --yes-i-understand (confirme que tu as lu le dry-run)")
        return 2

    print("\n▶ DELETE FROM coins WHERE face_value = 2.0")
    n = do_wipe(sb)
    print(f"✓ {n} rows coins supprimés (cascade en cours côté DB)")

    print("\n▶ Vérification post-wipe")
    remaining = sb.count("coins", params={"face_value": "eq.2.0"})
    print(f"  coins WHERE face_value=2.0 : {remaining} (attendu 0)")
    if remaining != 0:
        print("⚠️  count != 0, investigate")
        return 3

    if args.wipe_storage:
        print("\n▶ --wipe-storage : suppression des dossiers coin-images/{eurio_id}/")
        print("  (TODO : non implémenté, à ajouter si nécessaire — pour l'instant les images")
        print("   orphelines seront overwrite au refetch et n'affectent rien)")

    print("\n✅ Wipe terminé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
