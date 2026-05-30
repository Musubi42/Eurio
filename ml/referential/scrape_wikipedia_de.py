"""Parse la matrice « Übersicht » de de.wikipedia 2-Euro-Gedenkmünzen.

Seconde source de **couverture** (cf. memory ``project_eurlex_source``) : une
matrice pays × année qui dit aussi ce qui n'a PAS été émis (tiret) ou est
planifié (parenthèses) — complémentaire du JO.

Le tableau (1er ``wikitable zebra`` de la page) a une structure à cellules
fusionnées :
- en-tête : ``Land`` + une colonne par année ; les années à émission commune
  (2007/2009/2012/2015/2022) portent ``colspan=2`` → sous-colonnes E (nationale)
  et G (commune) ;
- lignes pays : des ``colspan`` compriment les années sans émission (avant
  l'entrée du pays dans l'euro), d'où une expansion de grille nécessaire.

Valeurs de cellule : nombre = pièces émises ; ``(n)`` = planifié ; ``–`` = aucune
émission cette année ; vide = hors zone euro / non concerné.

Écrit dans ``wikipedia_coverage`` (PK country, year, kind). Idempotent.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

_ML_ROOT = Path(__file__).resolve().parents[1]
if str(_ML_ROOT) not in sys.path:
    sys.path.insert(0, str(_ML_ROOT))

logger = logging.getLogger(__name__)

WIKI_URL = "https://de.wikipedia.org/wiki/2-Euro-Gedenkm%C3%BCnzen"
USER_AGENT = "Eurio/0.1 wikipedia-de-matrix (https://github.com/Musubi42/Eurio)"
SOURCE = "wikipedia_de"

# Nom allemand (substantif Wikipedia) → ISO2. Explicite (pas de dépendance au
# dico text_signals qui ne couvre pas tous les exonymes DE).
GERMAN_COUNTRY_TO_ISO2: dict[str, str] = {
    "andorra": "AD", "belgien": "BE", "bulgarien": "BG", "deutschland": "DE",
    "estland": "EE", "finnland": "FI", "frankreich": "FR", "griechenland": "GR",
    "irland": "IE", "italien": "IT", "kroatien": "HR", "lettland": "LV",
    "litauen": "LT", "luxemburg": "LU", "malta": "MT", "monaco": "MC",
    "niederlande": "NL", "österreich": "AT", "portugal": "PT", "san marino": "SM",
    "slowakei": "SK", "slowenien": "SI", "spanien": "ES", "vatikanstadt": "VA",
    "vatikan": "VA", "zypern": "CY",
}


@dataclass
class CoverageCell:
    country: str   # ISO2
    year: int
    kind: str      # 'E' (nationale) | 'G' (commune)
    count: int
    planned: bool


def _normalize_year(text: str) -> int | None:
    t = text.strip().lstrip("’'").strip()
    digits = re.sub(r"[^\d]", "", t)
    if len(digits) == 2:
        return 2000 + int(digits)
    if len(digits) == 4:
        return int(digits)
    return None


def _country_iso2(text: str) -> str | None:
    # Le texte de cellule duplique souvent le nom (lien + libellé) + marqueur
    # de note. On prend le plus long nom DE connu qui apparaît dedans.
    low = re.sub(r"\s+", " ", text.lower())
    best: tuple[int, str] | None = None
    for name, iso2 in GERMAN_COUNTRY_TO_ISO2.items():
        if name in low and (best is None or len(name) > best[0]):
            best = (len(name), iso2)
    return best[1] if best else None


def _parse_value(text: str) -> tuple[int, bool] | None:
    """``'2'`` → (2, False) ; ``'(2)'`` → (2, True) ; ``'–'`` → (0, False) ;
    vide → None (hors-périmètre, pas de row)."""
    t = re.sub(r"\s+", "", text)
    if not t:
        return None
    planned = "(" in t
    if "–" in t or "—" in t or t == "-":
        return (0, False)
    # Une cellule peut lister plusieurs émissions (« (1)(1) » = 2 planifiées) :
    # on SOMME les groupes de chiffres plutôt que de les concaténer.
    groups = re.findall(r"\d+", t)
    if not groups:
        return None
    return (sum(int(g) for g in groups), planned)


def parse_matrix(html: str) -> list[CoverageCell]:
    soup = BeautifulSoup(html, "html.parser")
    # La matrice = wikitable dont l'en-tête commence par 'Land' ET dont la
    # 1re ligne contient des colonnes-années (≥5). Discrimine de la table de
    # stats (qui commence aussi par 'Land' mais colonnes = démographie).
    table: Tag | None = None
    best_year_cols = 0
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if not rows:
            continue
        header = rows[0].find_all(["th", "td"])
        if not header or not header[0].get_text(strip=True).lower().startswith("land"):
            continue
        n_year = sum(1 for th in header[1:]
                     if _normalize_year(th.get_text(" ", strip=True)) is not None)
        if n_year > best_year_cols:
            best_year_cols, table = n_year, t
    if table is None or best_year_cols < 5:
        raise ValueError("matrice Übersicht introuvable (table 'Land' + années)")

    rows = table.find_all("tr")
    header = rows[0].find_all(["th", "td"])
    # Colonnes : pour chaque th année après 'Land', 1 col (E) ou 2 (E,G).
    columns: list[tuple[int, str]] = []
    for th in header[1:]:
        year = _normalize_year(th.get_text(" ", strip=True))
        if year is None:
            continue
        colspan = int(th.get("colspan") or 1)
        columns.append((year, "E"))
        if colspan >= 2:
            columns.append((year, "G"))

    cells: list[CoverageCell] = []
    # Lignes de données : on saute row0 (années) et row1 (sous-en-tête E/G).
    for r in rows[2:]:
        tds = r.find_all(["th", "td"])
        if not tds:
            continue
        iso2 = _country_iso2(tds[0].get_text(" ", strip=True))
        if iso2 is None:
            continue  # ligne Σ/total ou séparateur
        # Expansion de grille : map les cellules (après le pays) aux colonnes,
        # en dépliant les colspan (années comprimées sans émission).
        pos = 0
        for td in tds[1:]:
            span = int(td.get("colspan") or 1)
            # Retire les notes de bas de page (<sup class="reference">) dont le
            # numéro se collerait sinon à la valeur (ex. « 1[23] » → 123).
            for sup in td.find_all("sup"):
                sup.decompose()
            parsed = _parse_value(td.get_text(" ", strip=True))
            for _ in range(span):
                if pos >= len(columns):
                    break
                year, kind = columns[pos]
                pos += 1
                if parsed is not None:
                    count, planned = parsed
                    cells.append(CoverageCell(iso2, year, kind, count, planned))
    return cells


def _fetch_html() -> str:
    resp = httpx.get(WIKI_URL, headers={"User-Agent": USER_AGENT},
                     follow_redirects=True, timeout=40)
    resp.raise_for_status()
    return resp.text


def harvest(store, *, html: str | None = None, dry_run: bool = False) -> int:
    """Parse la matrice et upsert dans ``wikipedia_coverage``. Retourne n cells."""
    html = html or _fetch_html()
    cells = parse_matrix(html)
    logger.info("[wiki-de] %d cellules parsées", len(cells))
    if dry_run:
        return len(cells)
    conn = store._connection()  # noqa: SLF001
    for c in cells:
        conn.execute(
            """
            INSERT INTO wikipedia_coverage (country, year, kind, count, planned, source)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (country, year, kind) DO UPDATE SET
              count = excluded.count, planned = excluded.planned,
              fetched_at = datetime('now')
            """,
            (c.country, c.year, c.kind, c.count, 1 if c.planned else 0, SOURCE),
        )
    conn.commit()
    return len(cells)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + affiche, n'écrit pas en DB.")
    parser.add_argument("--log", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    from state import Store

    store = Store(_ML_ROOT / "state" / "eurio.db")
    n = harvest(store, dry_run=args.dry_run)
    print(f"{n} cellules {'(dry-run)' if args.dry_run else 'écrites'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
