"""Audit déterministe de l'attribution standard (multi-années → groupe).

LECTURE SEULE. Rejoue ``attribute_standard_listing`` sur les titres eBay réels
d'un pays et mesure l'effet du nouveau comportement multi-années→groupe : combien
de lots multi-années (« Kursmünzen 2000-2008 ») sont désormais rattachés à un
groupe au lieu d'être jetés en « ambigu ». Sert de socle au workflow de vérif.

Sortie JSON : counts par verdict, focus multi-années (résolus vs spans-groups),
et échantillons de résolus (title → groupe) pour audit adversarial.

Usage : python -m scripts.audit_standard_attribution --country ES [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ML_DIR = Path(__file__).resolve().parents[1]
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from sources.ebay.standards import attribute_standard_listing  # noqa: E402
from sources.text_signals import extract_listing_text_signals  # noqa: E402

DEFAULT_DB = ML_DIR / "state" / "eurio.db"
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _design_group_of(conn: sqlite3.Connection, eurio_id: str | None) -> str | None:
    if not eurio_id:
        return None
    r = conn.execute(
        "SELECT COALESCE(design_group_id, eurio_id) FROM coins WHERE eurio_id=?",
        (eurio_id,),
    ).fetchone()
    return r[0] if r else eurio_id


def audit(conn: sqlite3.Connection, country: str, denom: float = 2.0) -> dict:
    titles = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT listing_title FROM source_images "
            "WHERE source='ebay' AND listing_title IS NOT NULL AND listing_title != ''"
        ).fetchall()
    ]
    verdicts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    multiyear_total = 0
    multiyear_resolved = 0
    multiyear_spans = 0
    samples_resolved: list[dict] = []
    for title in titles:
        m = attribute_standard_listing(title, denom, country, conn=conn)
        verdicts[m.verdict] += 1
        reasons[m.reason.split(":")[0]] += 1
        n_years = len(extract_listing_text_signals(title).years)
        if n_years >= 2:
            multiyear_total += 1
            if m.reason.startswith("year_group_resolved"):
                multiyear_resolved += 1
                if len(samples_resolved) < 20:
                    samples_resolved.append({
                        "title": title[:90],
                        "target": m.target_eurio_id,
                        "group": _design_group_of(conn, m.target_eurio_id),
                        "reason": m.reason,
                    })
            elif m.reason.startswith("year_spans_groups"):
                multiyear_spans += 1
    return {
        "country": country.upper(),
        "n_titles_scanned": len(titles),
        "verdicts": dict(verdicts),
        "reason_prefixes": dict(reasons),
        "multiyear": {
            "total": multiyear_total,
            "resolved_to_group": multiyear_resolved,
            "spans_groups": multiyear_spans,
        },
        "samples_resolved": samples_resolved,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--country", required=True)
    p.add_argument("--denom", type=float, default=2.0)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--json", action="store_true", help="sortie JSON brute")
    args = p.parse_args()
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    res = audit(conn, args.country, args.denom)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
        return 0
    print(f"== {res['country']} — {res['n_titles_scanned']} titres ==")
    print(f"verdicts: {res['verdicts']}")
    print(f"raisons : {res['reason_prefixes']}")
    my = res["multiyear"]
    print(f"multi-années: {my['total']} total → {my['resolved_to_group']} résolus au "
          f"groupe, {my['spans_groups']} multi-groupes (ambigu)")
    for s in res["samples_resolved"][:12]:
        print(f"  ✓ {s['group']:28} ← «{s['title']}»")
    return 0


if __name__ == "__main__":
    sys.exit(main())
