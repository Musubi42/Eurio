"""Gate derive-then-diff des design_groups STANDARD par avers (cf. KICKOFF §4.6).

LECTURE SEULE. Dérive les groupes avers depuis ``design_description`` (via
``bootstrap.obverse_groups.derive_groups``) et les compare à la table de
référence validée à la main (``ml/data/design_groups_obverse_expected.json``).

C'est le **gate bloquant** avant tout bootstrap / rollout pays : exit ≠ 0 si un
écart est détecté (groupe manquant / en trop, membres divergents, ligne non
parsable). Sans entrée ``expected`` pour le pays, le rapport est imprimé mais le
gate échoue (on ne valide jamais à l'aveugle).

Usage :
    python -m scripts.audit_obverse_groups --country BE
    python -m scripts.audit_obverse_groups --country BE --face-value 2.0
    python -m scripts.audit_obverse_groups --country BE --db /chemin/eurio.db
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

from bootstrap.obverse_groups import (  # noqa: E402
    DeriveResult,
    derive_groups,
    load_overrides,
    load_standard_coins,
)

EXPECTED_PATH = ML_DIR / "data" / "design_groups_obverse_expected.json"
DEFAULT_DB = ML_DIR / "state" / "eurio.db"


def _open_ro(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _load_expected(country: str) -> dict[str, list[str]] | None:
    data = json.loads(EXPECTED_PATH.read_text())
    block = data.get(country.upper())
    if block is None:
        return None
    return {gid: sorted(members) for gid, members in block.items()}


def _print_derived(result: DeriveResult) -> None:
    print(f"\nGroupes dérivés ({len(result.groups)}) :")
    for g in result.groups:
        tag = " [SINGLETON]" if g.is_singleton else ""
        rng = f"{g.year_min}" if g.year_min == g.year_max else f"{g.year_min}-{g.year_max}"
        print(f"  {g.group_id:34} {rng:>9}  {g.designation}{tag}")
        for m in g.members:
            print(f"      • {m}")
    if result.unparsable:
        print(f"\n⚠ Non parsables ({len(result.unparsable)}) — à corriger / reviewer :")
        for eid in result.unparsable:
            print(f"      ✗ {eid}")


def _diff(
    derived: DeriveResult, expected: dict[str, list[str]]
) -> list[str]:
    """Retourne la liste des écarts (vide = match parfait)."""
    errors: list[str] = []
    got = {g.group_id: sorted(g.members) for g in derived.groups}

    for gid in sorted(set(got) | set(expected)):
        if gid not in expected:
            errors.append(f"groupe DÉRIVÉ inattendu (absent de expected) : {gid} → {got[gid]}")
        elif gid not in got:
            errors.append(f"groupe ATTENDU manquant (non dérivé) : {gid} → {expected[gid]}")
        elif got[gid] != expected[gid]:
            errors.append(
                f"membres divergents pour {gid} :\n"
                f"        dérivé   = {got[gid]}\n"
                f"        attendu  = {expected[gid]}"
            )

    if derived.unparsable:
        errors.append(f"{len(derived.unparsable)} pièce(s) non parsable(s) : {derived.unparsable}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True, help="ISO2 (ex. BE)")
    parser.add_argument("--face-value", type=float, default=None, help="optionnel, ex. 2.0")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()

    conn = _open_ro(Path(args.db))
    try:
        coins = load_standard_coins(conn, args.country, args.face_value)
    finally:
        conn.close()

    print(f"Pays {args.country.upper()} — {len(coins)} standard(s) canonique(s) chargé(s).")
    result = derive_groups(coins, load_overrides())
    _print_derived(result)

    expected = _load_expected(args.country)
    if expected is None:
        print(
            f"\n✗ GATE ÉCHEC : aucune entrée 'expected' pour {args.country.upper()} dans "
            f"{EXPECTED_PATH.name}. Ajouter la table validée à la main avant bootstrap."
        )
        return 2

    errors = _diff(result, expected)
    if errors:
        print(f"\n✗ GATE ÉCHEC — {len(errors)} écart(s) vs ground truth :")
        for e in errors:
            print(f"    - {e}")
        return 1

    print(f"\n✓ GATE OK — {len(result.groups)} groupe(s) conformes à la ground truth, 0 écart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
