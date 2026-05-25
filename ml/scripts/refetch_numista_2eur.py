"""Refetch Numista 2€ → SQLite (eurio.db) — orchestrateur cohorte-keyed.

Chunk P.7 du chantier coin-richness. Remplace l'ancien
``ml/referential/refetch_numista_2eur.py`` (Supabase-target) par une version
SQLite-only, alignée sur la doctrine ``SQLite-only`` + ``provenance
first-class`` (cf. ROADMAP-DB.md §2).

**Scope P.7a (cette étape)** : scaffold uniquement.

  - CLI ``--nids-file``, ``--dry-run`` / ``--apply``, ``--skip-prices``,
    ``--skip-images``, ``--cache-dir``.
  - Parse ``cohort_validation_19.txt`` : un NID par ligne, commentaires
    ``# …`` et lignes vides autorisés.
  - KeyManager wiring (status printing — RuntimeError tolerated when no
    keys configured pour permettre l'exécution scaffold sans secrets).
  - Plan printer : count NIDs, ~3*N calls estimés, slots de clé visibles.

  Pas encore : HTTP, transform, écriture DB. Ces étapes arrivent en P.7b
  (fetch + cache), P.7c (transform + DB writes), P.7d (tests fixtures).

Sous-étapes prévues post-P.7a — résumées ici pour mémoire ::

  P.7b  Fetch HTTP 3 endpoints (types/{nid}, /issues, /issues/{iid}/prices),
        cache JSON sur disque (cache-dir), rotation clés via KeyManager.
  P.7c  Transform payloads → rows DB. Cibles : coins, coin_source_refs,
        coin_mint_releases, mint_release_prices, coin_market_quotes
        (Type-level agrégé), coin_canonical_images, coin_credits,
        coin_observations (mintage/JOUE/theme), design_groups, coin_variants.
        Vocabulaire registry (source='numista_api'). Idempotent (UPSERT sur
        UNIQUE).
  P.7d  Tests pytest avec fixtures payloads Numista réels stockés en
        ``ml/tests/fixtures/numista/<nid>.json``.

**Usage cible (post-P.7d)** ::

    go-task ml:refetch-numista -- --nids-file ml/state/cohort_validation_19.txt --apply

⚠️ Kickoff §9 interdit le live fetch sur > 1 pièce avant V.1. Le mode
``--apply`` ne sera **pas** invoqué live durant la session P.7.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


def parse_nids_file(path: Path) -> list[int]:
    """Parse a NID list file. Format : un NID par ligne, commentaires
    ``# ...`` ignorés, lignes vides ignorées, commentaire inline après le
    NID autorisé (``68395    # ad-2014-2eur-standard``).

    Raises FileNotFoundError si le fichier n'existe pas, ValueError sur une
    ligne invalide (avec le numéro de ligne pour debug).
    """
    if not path.exists():
        raise FileNotFoundError(f"NIDs file not found: {path}")

    nids: list[int] = []
    seen: set[int] = set()
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        # Strip inline comment + whitespace.
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            nid = int(line)
        except ValueError as e:
            raise ValueError(
                f"{path}:{lineno}: cannot parse NID from {raw!r}"
            ) from e
        if nid in seen:
            raise ValueError(f"{path}:{lineno}: duplicate NID {nid}")
        seen.add(nid)
        nids.append(nid)
    return nids


def _load_keymanager_safe():
    """Best-effort KeyManager load. Returns None if no keys configured
    (scaffold can run without secrets). Other RuntimeErrors propagate."""
    try:
        from referential.numista_keys import KeyManager
    except ImportError as e:
        print(f"⚠️  KeyManager import failed: {e}")
        return None
    try:
        return KeyManager()
    except RuntimeError as e:
        # Typically "No Numista API keys found" when secrets/dev.env not loaded.
        print(f"⚠️  KeyManager init failed: {e}")
        return None


def print_plan(nids: list[int], cache_dir: Path, *,
               apply: bool, skip_prices: bool, skip_images: bool) -> None:
    n = len(nids)
    print("═" * 60)
    print("REFETCH NUMISTA 2€ — execution plan")
    print("═" * 60)
    print(f"  NIDs to fetch              : {n}")
    print(f"  Mode                       : {'--apply' if apply else '--dry-run'}")
    print(f"  Skip prices                : {skip_prices}")
    print(f"  Skip images                : {skip_images}")
    print(f"  Cache dir                  : {cache_dir}")

    # API call budget estimate (per NID) :
    #   - 1 × /types/{nid}                    → metadata
    #   - 1 × /types/{nid}/issues             → liste mint_releases
    #   - K × /types/{nid}/issues/{iid}/prices (K ≈ avg # issues per type)
    avg_issues = 4  # estimation prudente cf. archive kickoff §6.2
    calls_meta = 2 * n
    calls_prices = 0 if skip_prices else avg_issues * n
    total = calls_meta + calls_prices
    print(f"  Estimated API calls        : "
          f"{total} ({calls_meta} meta + {calls_prices} prices, "
          f"avg {avg_issues} issues/type)")

    km = _load_keymanager_safe()
    if km is None:
        print("  KeyManager                 : not loaded (no NUMISTA_API_KEY_* in env)")
    else:
        statuses = km.status()
        total_remaining = sum(s["remaining"] for s in statuses)
        print(f"  KeyManager                 : {len(statuses)} slot(s), "
              f"{total_remaining} calls remaining this month")
        for s in statuses:
            tag = " EXHAUSTED" if s["exhausted"] else ""
            print(f"    slot {s['slot']:>2}  calls={s['calls_this_month']:>5}  "
                  f"remaining={s['remaining']:>5}{tag}")

    print("\n  Preview (first 5 NIDs) :")
    for nid in nids[:5]:
        print(f"    {nid}")
    if n > 5:
        print(f"    ... +{n - 5} more")

    print("\n⚠️  P.7a SCAFFOLD — HTTP fetch + DB writes ne sont pas encore implémentés.")
    print("    Voir P.7b/c/d (cf. module docstring).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--nids-file",
        required=True,
        type=Path,
        help="Path to file with one NID per line (# comments allowed). "
             "Ex: ml/state/cohort_validation_19.txt",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=ML_DIR / "state" / "numista_cache",
        help="Directory to cache Numista API payloads (default: ml/state/numista_cache/)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="Plan only, no HTTP, no DB writes (default).")
    mode.add_argument("--apply", action="store_true",
                      help="Execute refetch. (NB: P.7a scaffold ne fait rien live)")
    parser.add_argument("--skip-prices", action="store_true",
                        help="Skip /issues/{iid}/prices (~75%% quota saving).")
    parser.add_argument("--skip-images", action="store_true",
                        help="Skip image URL capture (deferred to V.2/V.3).")
    args = parser.parse_args()

    try:
        nids = parse_nids_file(args.nids_file)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    if not nids:
        print(f"⚠️  No NIDs found in {args.nids_file} (empty or all comments).")
        return 1

    print_plan(
        nids, args.cache_dir,
        apply=args.apply,
        skip_prices=args.skip_prices,
        skip_images=args.skip_images,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
