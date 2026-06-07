"""Alias colloquiaux générés par LLM ancré (chunk C2a-2).

Le theme-matcher tape `coin_aliases` en limite de mot (livré C2a-1). C1
a montré que les acronymes en parenthèses ne couvrent que ~5 cas (EMI) :
le gros du vocabulaire de marché — « Studentenrevolte », « Iris »
(surnom d'ESRO-2B), « Brügel » — n'est PAS dans les titres i18n Numista,
qui sont des traductions littérales. Les vendeurs eBay, eux, écrivent le
terme de marché. D'où le faux rejet / la non-attribution.

Ce script ne TOUCHE PAS le matcher : il ne fait que peupler la table
`coin_aliases` avec `source='llm'`. Deux modes, sur le pattern du
LLM-juge de `bench_theme_match.py` :

  export-batch — pour un périmètre de coins (défaut : BE 2017-2021, le
                 périmètre du gold), sort un JSONL : par coin son
                 `eurio_id`, `theme`, les 6 titres i18n, et **les sœurs
                 du groupe de découverte** (eurio_id + theme) comme
                 contexte anti-collision. Claude Code lit ce batch et
                 écrit à la main `aliases_llm.jsonl`.

  ingest       — ré-ingère `aliases_llm.jsonl` dans `coin_aliases` avec
                 `source='llm'`. **Garde-fou anti-collision** : un alias
                 candidat est rejeté s'il matche, en limite de mot et
                 normalisé, un titre i18n ou un alias d'une **sœur du
                 groupe** — sinon il taperait sur la mauvaise pièce.
                 Idempotent (INSERT OR IGNORE). Les rejets sont loggués.

Format de `aliases_llm.jsonl` (une ligne par coin) ::

    {"eurio_id": "be-2018-2eur-...", "aliases": [
        {"alias": "studentenrevolte", "lang": "de", "confidence": "high"},
        {"alias": "mai 68",           "lang": "fr", "confidence": "low"}
    ]}

`confidence` est une métadonnée honnête (audit + future calibration) —
le matcher ne la lit pas : un alias `low` tape comme un `high`. La
sécurité, c'est le garde-fou anti-collision, pas la confidence.

Usage::

    python -m scripts.llm_coin_aliases export-batch [--country BE] [--years 2017-2021]
    python -m scripts.llm_coin_aliases ingest [--dry]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from sources.ebay.theme_tokens import normalize  # noqa: E402
from store import Store  # noqa: E402

DB_PATH = ML_DIR / "state" / "eurio.db"
BENCH_DIR = ML_DIR / "state" / "discovery_bench"
BATCH_PATH = BENCH_DIR / "aliases_batch.jsonl"
ALIASES_PATH = BENCH_DIR / "aliases_llm.jsonl"

I18N_LANGS = ("fr", "en", "de", "es", "it", "nl")
VALID_CONFIDENCE = ("high", "low")


# ── helpers ────────────────────────────────────────────────────────────────

def _parse_years(spec: str) -> list[int]:
    """`"2017-2021"` ou `"2018"` ou `"2017,2019"` → liste d'années triées."""
    years: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            years.update(range(int(lo), int(hi) + 1))
        elif part:
            years.add(int(part))
    return sorted(years)


def _word_match(needle: str, haystack: str) -> bool:
    """Vrai si `needle` (déjà normalisé) apparaît en limite de mot dans
    `haystack` (déjà normalisé). Même sémantique que le matcher."""
    if not needle:
        return False
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def collides(alias: str, sister_corpus: list[str]) -> str | None:
    """Renvoie le fragment de vocab sœur en collision, ou None.

    `alias` et `sister_corpus` sont déjà normalisés. Une collision = le
    candidat apparaît en limite de mot dans un titre i18n ou un alias
    d'une sœur du groupe → il taperait aussi sur cette sœur, le matcher
    confondrait les deux pièces. Fonction pure, testable.
    """
    for fragment in sister_corpus:
        if _word_match(alias, fragment):
            return fragment
    return None


def _group_coins(conn, country: str, year: int) -> list[str]:
    """eurio_ids des 2 € commémo d'un groupe de découverte (pays, année)."""
    rows = conn.execute(
        "SELECT eurio_id FROM coins WHERE country=? AND face_value=2.0 "
        "AND is_commemorative=1 AND year=? ORDER BY eurio_id",
        (country, year),
    ).fetchall()
    return [r["eurio_id"] for r in rows]


def _i18n_titles(conn, eurio_id: str) -> dict[str, str]:
    """{lang: titre} des titres Numista localisés d'un coin."""
    return {
        r["lang"]: r["title"]
        for r in conn.execute(
            "SELECT lang, title FROM coin_names_i18n WHERE eurio_id=?",
            (eurio_id,),
        ).fetchall()
    }


# ── export-batch ───────────────────────────────────────────────────────────

def cmd_export_batch(args: argparse.Namespace) -> int:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    store = Store(DB_PATH)
    conn = store._connection()  # noqa: SLF001

    country = args.country.upper()
    years = _parse_years(args.years)

    records: list[dict] = []
    for year in years:
        ids = _group_coins(conn, country, year)
        for eid in ids:
            crow = conn.execute(
                "SELECT theme FROM coins WHERE eurio_id=?", (eid,)
            ).fetchone()
            i18n = _i18n_titles(conn, eid)
            sisters = [
                {
                    "eurio_id": sid,
                    "theme": (conn.execute(
                        "SELECT theme FROM coins WHERE eurio_id=?", (sid,)
                    ).fetchone() or {"theme": None})["theme"],
                }
                for sid in ids if sid != eid
            ]
            records.append({
                "eurio_id": eid,
                "year": year,
                "theme": crow["theme"] if crow else None,
                "i18n": {k: i18n[k] for k in I18N_LANGS if k in i18n},
                "sisters": sisters,
            })

    with BATCH_PATH.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"export-batch → {BATCH_PATH}")
    print(f"  {len(records)} coins ({country} {years[0]}-{years[-1]})")
    mono = sum(1 for r in records if not r["sisters"])
    print(f"  dont {mono} en groupe mono-pièce (alias sans effet bench)")
    print(f"\nÉtape suivante : lire {BATCH_PATH.name}, écrire à la main "
          f"{ALIASES_PATH.name}, puis `go-task ml:aliases:ingest`.")
    return 0


# ── ingest ─────────────────────────────────────────────────────────────────

def cmd_ingest(args: argparse.Namespace) -> int:
    if not ALIASES_PATH.exists():
        print(f"manque {ALIASES_PATH} — lancer export-batch puis générer "
              f"les alias", file=sys.stderr)
        return 1
    store = Store(DB_PATH)
    conn = store._connection()  # noqa: SLF001

    coin_records = [
        json.loads(ln) for ln in ALIASES_PATH.read_text().splitlines()
        if ln.strip()
    ]

    # eurio_id → groupe (pays, année) → sœurs.
    eid_meta: dict[str, tuple[str, int]] = {}
    for rec in coin_records:
        row = conn.execute(
            "SELECT country, year FROM coins WHERE eurio_id=?",
            (rec["eurio_id"],),
        ).fetchone()
        if row is None:
            print(f"⚠ eurio_id inconnu : {rec['eurio_id']}", file=sys.stderr)
            return 1
        eid_meta[rec["eurio_id"]] = (row["country"], row["year"])

    # Alias candidats LLM par coin, normalisés — pour le corpus anti-collision
    # (une sœur peut elle-même recevoir un alias candidat dans ce même batch).
    llm_by_eid: dict[str, list[str]] = {}
    for rec in coin_records:
        llm_by_eid[rec["eurio_id"]] = [
            normalize(a["alias"]) for a in rec.get("aliases", [])
        ]

    def sister_corpus(eurio_id: str) -> list[str]:
        """Vocab normalisé des sœurs du groupe : titres i18n + alias DB
        existants + alias candidats LLM du même batch."""
        country, year = eid_meta[eurio_id]
        corpus: list[str] = []
        for sid in _group_coins(conn, country, year):
            if sid == eurio_id:
                continue
            for title in _i18n_titles(conn, sid).values():
                corpus.append(normalize(title))
            for r in conn.execute(
                "SELECT alias FROM coin_aliases WHERE eurio_id=?", (sid,)
            ).fetchall():
                corpus.append(r["alias"])
            corpus.extend(llm_by_eid.get(sid, []))
        return corpus

    n_ins = n_dup = n_rejected = 0
    for rec in coin_records:
        eid = rec["eurio_id"]
        corpus = sister_corpus(eid)
        for cand in rec.get("aliases", []):
            alias = normalize(cand["alias"])
            lang = cand.get("lang", "xx")
            confidence = cand.get("confidence", "high")
            if confidence not in VALID_CONFIDENCE:
                print(f"⚠ confidence invalide {confidence!r} ({eid} / "
                      f"{alias}) — attendu {VALID_CONFIDENCE}",
                      file=sys.stderr)
                return 1
            hit = collides(alias, corpus)
            if hit is not None:
                n_rejected += 1
                print(f"  ✗ COLLISION  {eid}  [{lang}]  {alias!r}  "
                      f"→ matche le vocab d'une sœur : {hit!r}")
                continue
            if args.dry:
                print(f"  + {eid}  [{lang}]  {alias!r}  ({confidence})")
                n_ins += 1
                continue
            cur = conn.execute(
                # P.3b : split source/method. L'alias dérive d'un titre
                # Numista via LLM → source='numista_api', method='llm'.
                "INSERT OR IGNORE INTO coin_aliases "
                "(eurio_id, lang, alias, source, method, confidence) "
                "VALUES (?, ?, ?, 'numista_api', 'llm', ?)",
                (eid, lang, alias, confidence),
            )
            if cur.rowcount:
                n_ins += 1
            else:
                n_dup += 1

    if not args.dry:
        conn.commit()

    verb = "à insérer" if args.dry else "insérés"
    print(f"\ningest llm-aliases : {n_ins} alias {verb}, "
          f"{n_dup} déjà présents, {n_rejected} rejetés pour collision"
          f"{'  — DRY, rien écrit' if args.dry else ' (idempotent)'}")
    return 0


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export-batch",
                           help="sort le batch de coins à enrichir")
    p_exp.add_argument("--country", default="BE", help="ISO2 (défaut BE)")
    p_exp.add_argument("--years", default="2017-2021",
                       help="range ou liste (défaut 2017-2021)")

    p_ing = sub.add_parser("ingest", help="ingère aliases_llm.jsonl")
    p_ing.add_argument("--dry", action="store_true",
                       help="affiche sans écrire en base")

    args = parser.parse_args()
    if args.cmd == "export-batch":
        return cmd_export_batch(args)
    if args.cmd == "ingest":
        return cmd_ingest(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
