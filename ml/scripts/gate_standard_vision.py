"""Gate vision du standard scrape : rejette les commémos/junk leakées (cf. KICKOFF).

L'éval (``scripts.eval_obverse_attribution_vision``) a montré que le standard scrape
attribue des commémos à titre vendeur générique aux classes standard (l'exclusion
text-based ne les voit pas). Ce gate tranche sur l'IMAGE : pour chaque crop eBay
OUVERT en review attribué à un groupe standard du pays, Claude classe le crop, et —
avec ``--apply`` — les ``wrong_coin`` / ``junk`` à haute confiance sont **rejetés**
par le chemin canonique (``image_assets.resolution_status='rejected'``,
``training_eligible=0``, ``review_queue`` clos, event d'état actor=``vision_gate``).

Réversible : un faux rejet se restaure via la liste des rejetés (endpoint
``/review/rejected`` + restore). On NE rejette PAS ``wrong_era`` (vrai standard mal
groupé → laissé à l'humain) ni ``correct`` / ``reverse_cant_tell``.

Dry-run par défaut (classe + rapporte, n'écrit rien). ccproxy user-owned (port 3002).

Usage :
    python -m scripts.gate_standard_vision --country BE                 # dry-run
    python -m scripts.gate_standard_vision --country BE --apply
    python -m scripts.gate_standard_vision --country BE --apply --min-confidence 0.85
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from shared import ccproxy_client  # noqa: E402
from training.foundation.claude_review import DEFAULT_MODEL_ALIAS, MODELS  # noqa: E402
from training.foundation.obverse_group_review import canonical_obverse_path  # noqa: E402
from training.foundation.standard_gate_review import classify_crop  # noqa: E402
from store import Store, emit_state_event  # noqa: E402
from shared.storage.local_cache import local_path  # noqa: E402

DEFAULT_DB = ML_DIR / "state" / "eurio.db"
REJECT_LABELS = ("wrong_coin", "junk")  # wrong_era = vrai standard mal groupé → on garde
ENGINE_VERSION = "vision_standard_gate_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _group_canon(conn: sqlite3.Connection, country: str) -> dict[str, tuple[str, str, list[Path]]]:
    """grp → (designation, year_range, [avers canoniques des membres])."""
    rows = conn.execute(
        """
        SELECT COALESCE(c.design_group_id, c.eurio_id) AS grp,
               dg.designation AS designation,
               MIN(c.year) AS y0, MAX(c.year) AS y1,
               GROUP_CONCAT(c.numista_id) AS ref_numistas
          FROM coins c
          LEFT JOIN design_groups dg ON dg.id = c.design_group_id
         WHERE c.country = ? AND c.is_commemorative = 0 AND c.canonical_eurio_id IS NULL
         GROUP BY grp
        """,
        (country.upper(),),
    ).fetchall()
    out: dict[str, tuple[str, str, list[Path]]] = {}
    for r in rows:
        paths = []
        for nid in (r["ref_numistas"] or "").split(","):
            nid = nid.strip()
            if nid and (p := canonical_obverse_path(int(nid))) is not None:
                paths.append(p)
        rng = f"{r['y0']}" if r["y0"] == r["y1"] else f"{r['y0']}-{r['y1']}"
        out[r["grp"]] = (r["designation"] or r["grp"], rng, paths)
    return out


def _open_items(conn: sqlite3.Connection, country: str, limit: int | None) -> list[sqlite3.Row]:
    sql = (
        "SELECT rq.id AS review_id, rq.image_asset_id, ia.storage_path, "
        "       si.listing_title, COALESCE(c.design_group_id, c.eurio_id) AS grp "
        "  FROM review_queue rq "
        "  JOIN image_assets ia ON ia.id = rq.image_asset_id "
        "  JOIN source_images si ON si.id = ia.source_image_id "
        "  JOIN coins c ON c.eurio_id = si.target_eurio_id "
        " WHERE rq.status = 'open' AND si.source = 'ebay' "
        "   AND c.country = ? AND c.is_commemorative = 0 AND c.canonical_eurio_id IS NULL "
        "   AND ia.storage_path IS NOT NULL "
        " ORDER BY grp, ia.fetched_at DESC"
    )
    params: list[object] = [country.upper()]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, params).fetchall()


def _reject(conn: sqlite3.Connection, *, review_id: str, asset_id: str, label: str, conf: float | None) -> bool:
    """Rejet canonique réversible. Retourne True si écrit (review encore open)."""
    now = _now_iso()
    reason = f"vision_standard_gate:{label}"
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE image_assets SET resolution_status='rejected', training_eligible=0, "
            "quality_reason=?, resolved_at=? WHERE id=?",
            ("vision_standard_gate", now, asset_id),
        )
        cur = conn.execute(
            "UPDATE review_queue SET status='done', decision_notes=?, decided_at=?, "
            "decided_by='vision_gate', decision_engine_version=?, decision_metadata_json=? "
            "WHERE id=? AND status='open'",
            (reason, now, ENGINE_VERSION,
             json.dumps({"reason": reason, "confidence": conf}), review_id),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            return False
        # actor enum-contraint (image_state_events) → 'ccproxy' (vision Claude) ;
        # la provenance fine du gate vit dans `reason` + review_queue.decided_by.
        emit_state_event(
            conn, asset_id=asset_id, to_state="rejected",
            actor="ccproxy", reason=reason,
        )
        conn.execute("COMMIT")
        return True
    except Exception:
        conn.execute("ROLLBACK")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True)
    parser.add_argument("--apply", action="store_true", help="écrit les rejets (défaut = dry-run)")
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--limit", type=int, default=None, help="cap le nombre de crops classés")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--model", default=DEFAULT_MODEL_ALIAS, choices=list(MODELS))
    parser.add_argument("--base-url", default="http://127.0.0.1:3002")
    args = parser.parse_args()

    try:
        ccproxy_client.health(args.base_url)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ ccproxy injoignable ({exc}).")
        return 2

    store = Store(Path(args.db))
    conn = store._connection()
    canon = _group_canon(conn, args.country)
    items = _open_items(conn, args.country, args.limit)
    print(
        f"Gate vision standard — {args.country.upper()} — {len(items)} crop(s) open "
        f"{'[APPLY]' if args.apply else '[DRY-RUN]'} min_conf={args.min_confidence}\n"
    )

    tally: Counter[str] = Counter()
    rejected = 0
    total_cost = 0.0
    for it in items:
        grp = it["grp"]
        if grp not in canon or not canon[grp][2]:
            tally["no_canonical"] += 1
            continue
        designation, rng, paths = canon[grp]
        try:
            crop_path = local_path("enrichment-crops", it["storage_path"])
        except Exception:  # noqa: BLE001
            tally["unresolved"] += 1
            continue
        v = classify_crop(
            canonical_paths=paths, crop_path=crop_path,
            group_label=designation, year_range=rng,
            listing_title=it["listing_title"] or "",
            model_alias=args.model, base_url=args.base_url,
        )
        total_cost += v.cost_usd
        if v.error:
            tally[f"err_{v.error}"] += 1
            continue
        tally[v.label] += 1
        will_reject = v.label in REJECT_LABELS and (v.confidence or 0) >= args.min_confidence
        if will_reject:
            mark = "REJECT" if args.apply else "would-reject"
            print(f"  {mark:12} {v.label:11} conf={v.confidence:.2f} {grp}  «{(it['listing_title'] or '')[:50]}»")
            if args.apply and _reject(
                conn, review_id=it["review_id"], asset_id=it["image_asset_id"],
                label=v.label, conf=v.confidence,
            ):
                rejected += 1

    print(f"\nClassés : {dict(tally)}")
    would = sum(tally[l] for l in REJECT_LABELS)
    if args.apply:
        print(f"Rejetés : {rejected} (réversible via /review/rejected). Coût ≈ ${total_cost:.4f}")
    else:
        print(f"À rejeter (≥{args.min_confidence}) : ~{would} wrong_coin/junk. "
              f"Relancer avec --apply. Coût ≈ ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
