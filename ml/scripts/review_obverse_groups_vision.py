"""Review vision Claude des design_groups STANDARD par avers (cf. KICKOFF §4.7).

Pour chaque design_group avers d'un pays, envoie les avers canoniques des Types
membres à Claude et vérifie qu'ils partagent bien le **même avers**. Valide a
posteriori le groupage (déterministe) — n'écrit RIEN, ne re-groupe RIEN. Sortie =
liste d'anomalies pour review PO.

ccproxy est **user-owned** (port 3002) : le script échoue proprement si le proxy
est down (pré-flight ``/health``), ne lance aucun scrape ni écriture.

Codes de sortie : 0 = tous cohérents ; 1 = anomalie(s) (avers divergent / outlier) ;
2 = erreur d'exécution (ccproxy down, avers manquant, parse fail).

Usage :
    python -m scripts.review_obverse_groups_vision --country BE
    python -m scripts.review_obverse_groups_vision --country BE --model sonnet
    python -m scripts.review_obverse_groups_vision --country BE --include-singletons
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

import ccproxy_client  # noqa: E402
from foundation.claude_review import DEFAULT_MODEL_ALIAS, MODELS  # noqa: E402
from foundation.obverse_group_review import (  # noqa: E402
    canonical_obverse_path,
    review_group,
)

DEFAULT_DB = ML_DIR / "state" / "eurio.db"
ACCEPTED_PATH = ML_DIR / "data" / "obverse_review_accepted.json"


def _load_accepted() -> dict[str, str]:
    """Anomalies acceptées par le PO (group_id → raison) — ne font pas échouer le gate."""
    if not ACCEPTED_PATH.exists():
        return {}
    data = json.loads(ACCEPTED_PATH.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _open_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load_groups(conn: sqlite3.Connection, country: str) -> dict[str, list[sqlite3.Row]]:
    """design_group_id → membres (Types canoniques standard) du pays."""
    rows = conn.execute(
        """
        SELECT design_group_id, eurio_id, numista_id, year
          FROM coins
         WHERE country = ? AND is_commemorative = 0 AND canonical_eurio_id IS NULL
           AND design_group_id IS NOT NULL
         ORDER BY design_group_id, year, eurio_id
        """,
        (country.upper(),),
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(r["design_group_id"], []).append(r)
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True, help="ISO2 (ex. BE)")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--model", default=DEFAULT_MODEL_ALIAS, choices=list(MODELS))
    parser.add_argument("--base-url", default="http://127.0.0.1:3002")
    parser.add_argument(
        "--include-singletons", action="store_true",
        help="review aussi les groupes mono-membre (trivialement cohérents, skip par défaut)",
    )
    args = parser.parse_args()

    # Pré-flight ccproxy (user-owned) — échoue proprement si down.
    try:
        ccproxy_client.health(args.base_url)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ ccproxy injoignable sur {args.base_url} ({exc}). Démarre-le puis relance.")
        return 2

    conn = _open_ro(Path(args.db))
    try:
        groups = _load_groups(conn, args.country)
    finally:
        conn.close()

    if not groups:
        print(f"Aucun design_group avers pour {args.country.upper()} (bootstrap fait ?).")
        return 2

    accepted = _load_accepted()
    anomalies = 0
    accepted_hits = 0
    errors = 0
    total_cost = 0.0
    print(f"Review vision avers — {args.country.upper()} — {len(groups)} groupe(s) — modèle {args.model}\n")

    for group_id, members in groups.items():
        if len(members) < 2 and not args.include_singletons:
            print(f"  {group_id:28} · {len(members)} membre — skip (mono-membre)")
            continue

        resolved: list[tuple[str, Path]] = []
        missing: list[str] = []
        for m in members:
            path = canonical_obverse_path(m["numista_id"])
            if path is None:
                missing.append(f"{m['eurio_id']} (numista={m['numista_id']})")
            else:
                resolved.append((m["eurio_id"], path))

        if missing:
            print(f"  {group_id:28} ✗ avers manquant(s), groupe non reviewé : {missing}")
            errors += 1
            continue
        if len(resolved) < 2:
            print(f"  {group_id:28} · 1 avers résolu — skip")
            continue

        rev = review_group(
            group_id=group_id, members=resolved,
            model_alias=args.model, base_url=args.base_url,
        )
        total_cost += rev.cost_usd
        if rev.error:
            print(f"  {group_id:28} ✗ erreur LLM : {rev.error}")
            errors += 1
        elif rev.ok:
            conf = f"{rev.confidence:.2f}" if rev.confidence is not None else "?"
            print(f"  {group_id:28} ✓ avers cohérent ({len(resolved)} membres, conf {conf})")
        elif group_id in accepted:
            accepted_hits += 1
            conf = f"{rev.confidence:.2f}" if rev.confidence is not None else "?"
            detail = f"outlier = {rev.outlier_label}" if rev.outlier_label else "avers divergents"
            print(f"  {group_id:28} ⚠ accepté (PO) — {detail} (conf {conf})")
            print(f"        raison: {accepted[group_id]}")
        else:
            anomalies += 1
            conf = f"{rev.confidence:.2f}" if rev.confidence is not None else "?"
            detail = f"outlier = {rev.outlier_label}" if rev.outlier_label else "avers divergents"
            print(f"  {group_id:28} ⚠ ANOMALIE — {detail} (conf {conf})")
            print(f"        raw: {rev.raw_content}")

    print(
        f"\nCoût total ≈ ${total_cost:.4f}. Anomalies: {anomalies}, "
        f"acceptées (PO): {accepted_hits}, erreurs: {errors}."
    )
    if errors:
        return 2
    if anomalies:
        print("→ Anomalies à trancher par le PO (aucun re-groupage automatique).")
        return 1
    print("✓ Tous les groupes reviewés sont cohérents (anomalies acceptées incluses).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
