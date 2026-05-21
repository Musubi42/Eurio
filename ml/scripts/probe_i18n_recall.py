"""Probe — recall du matcher I2 vs baseline legacy, offline.

Cf. chunk C du kickoff I2 (``i18n-theme-matcher-kickoff.md``), étape
"smoke run end-to-end".

Rejoue ``title_matches_theme`` (version I2 multilingue) sur les listings
historiquement rejetés en ``theme_mismatch`` par le matcher legacy. Tout
listing pour lequel I2 renvoie ``True`` est un **recover** : un faux
négatif legacy potentiellement corrigé — ou un vrai négatif réintroduit
(à vérifier visuellement).

Baseline legacy = 0 par construction (ces listings ONT été rejetés). On
mesure donc le *recovery rate* + on imprime les titres recover pour
audit manuel de légitimité.

Usage:
    python -m scripts.probe_i18n_recall
    python -m scripts.probe_i18n_recall --marketplace EBAY_FR
    python -m scripts.probe_i18n_recall --limit 5

Script jetable — supprimé après validation I2.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.ebay.queries import (  # noqa: E402
    _legacy_title_matches_theme,
    _theme_keywords,
    title_matches_theme,
)
from sources.ebay.theme_tokens import extract_tokens, load_i18n_title  # noqa: E402

DB_PATH = ROOT / "state" / "training.db"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marketplace", default="EBAY_FR",
                        help="Marketplace assumé (listings legacy = NULL). Défaut EBAY_FR.")
    parser.add_argument("--limit", type=int, help="Limiter le nombre d'eurio_ids")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    eurio_ids = [r[0] for r in conn.execute(
        """
        SELECT DISTINCT target_eurio_id FROM discarded_listings
        WHERE reason='theme_mismatch' AND target_eurio_id IS NOT NULL
          AND title IS NOT NULL
        ORDER BY target_eurio_id
        """
    ).fetchall()]
    if args.limit:
        eurio_ids = eurio_ids[:args.limit]

    total_listings = 0
    total_recovered = 0

    for eurio_id in eurio_ids:
        rows = conn.execute(
            """
            SELECT title FROM discarded_listings
            WHERE reason='theme_mismatch' AND target_eurio_id=? AND title IS NOT NULL
            """,
            (eurio_id,),
        ).fetchall()
        titles = [r[0] for r in rows]
        if not titles:
            continue

        fr_title = load_i18n_title(conn, eurio_id, "fr")
        en_title = load_i18n_title(conn, eurio_id, "en")
        fr_tok = extract_tokens(fr_title, "fr") if fr_title else []
        en_tok = extract_tokens(en_title, "en") if en_title else []
        legacy_tok = _theme_keywords(eurio_id)

        recovered = []
        for title in titles:
            i2 = title_matches_theme(title, eurio_id, conn=conn)
            # legacy = _legacy par construction False ; on revérifie pour sûreté.
            legacy = _legacy_title_matches_theme(title, legacy_tok)
            if i2 and not legacy:
                recovered.append(title)

        total_listings += len(titles)
        total_recovered += len(recovered)

        print(f"\n{'='*70}")
        print(f"{eurio_id}")
        print(f"  i18n FR : {fr_title!r}  → tokens {fr_tok}")
        print(f"  i18n EN : {en_title!r}  → tokens {en_tok}")
        print(f"  legacy tokens (slug EN) : {legacy_tok}")
        print(f"  listings theme_mismatch : {len(titles)}  |  recover I2 : {len(recovered)}")
        if recovered:
            print(f"  -- titres recover (à auditer : vrai positif ?) --")
            for t in recovered[:12]:
                print(f"     ✔ {t}")
            if len(recovered) > 12:
                print(f"     … +{len(recovered)-12} autres")

    print(f"\n{'='*70}")
    print(f"TOTAL : {total_recovered}/{total_listings} listings recover "
          f"({100*total_recovered/total_listings:.0f}%) sur {len(eurio_ids)} eurio_ids")
    print("Baseline legacy recall sur cet échantillon = 0 (rejets par construction).")
    print("→ Auditer visuellement : les recover sont-ils des VRAIS positifs ?")

    conn.close()


if __name__ == "__main__":
    main()
