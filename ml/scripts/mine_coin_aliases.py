"""Mine des alias de thème depuis les titres i18n (chunk C2a-1).

Source 'acronym' : extrait le contenu entre parenthèses des titres
``coin_names_i18n`` quand il ressemble à un acronyme (un seul token,
2-6 lettres, MAJUSCULES dans le titre original). Ex. « European Monetary
Institute (EMI) » → alias ``emi``.

Les acronymes sont DANS les titres i18n mais le tokenizer les jette
(tokens < 4 chars) — d'où le faux rejet massif de la pièce EMI mesuré
au bench P0. Cet alias les réinjecte dans une table dédiée, matchée en
limite de mot par le theme-matcher.

Idempotent (INSERT OR IGNORE).

Usage:
    python -m scripts.mine_coin_aliases [--dry]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from sources.ebay.theme_tokens import normalize  # noqa: E402
from state import Store  # noqa: E402

DB_PATH = ML_DIR / "state" / "training.db"

_PAREN_RE = re.compile(r"\(([^)]+)\)")
# Un acronyme : un seul token, 2-6 lettres, MAJUSCULES dans l'original.
_ACRONYM_RE = re.compile(r"^[A-ZÀ-Þ]{2,6}$")


def _acronyms(title: str) -> set[str]:
    """Acronymes normalisés extraits des parenthèses d'un titre."""
    out: set[str] = set()
    for inner in _PAREN_RE.findall(title):
        tok = inner.strip()
        if _ACRONYM_RE.match(tok):
            out.add(normalize(tok))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true",
                        help="affiche sans écrire en base")
    args = parser.parse_args()

    store = Store(DB_PATH)
    conn = store._connection()  # noqa: SLF001

    rows = conn.execute(
        "SELECT eurio_id, lang, title FROM coin_names_i18n"
    ).fetchall()

    found: list[tuple[str, str, str]] = []
    for r in rows:
        for alias in _acronyms(r["title"]):
            found.append((r["eurio_id"], r["lang"], alias))

    if args.dry:
        for eid, lang, alias in sorted(found):
            print(f"  {eid}  [{lang}]  {alias}")
        print(f"\n{len(found)} alias acronymes depuis {len(rows)} titres i18n "
              f"({len(set(found))} distincts) — DRY, rien écrit")
        return 0

    n_ins = 0
    for eid, lang, alias in found:
        cur = conn.execute(
            "INSERT OR IGNORE INTO coin_aliases "
            "(eurio_id, lang, alias, source, confidence) "
            "VALUES (?, ?, ?, 'acronym', 'high')",
            (eid, lang, alias),
        )
        n_ins += cur.rowcount
    conn.commit()
    print(f"mine-acronyms : {len(found)} candidats depuis {len(rows)} titres "
          f"i18n → {n_ins} alias insérés (idempotent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
