"""Probe V1 — distribution réelle des langues de titres par marketplace.

Cf. ``docs/sources-refacto/ebay-multi-marketplace/language-probe.md``
§"Étape 2 — Probe marketplaces × langues".

But : confirmer empiriquement ``MARKETPLACE_ACTIVE_LANGS`` (matcher I2)
et trancher le routing PT provisoire (PT→ES vs PT→GB-only).

Deux mesures :

1. **Langues par marketplace** — 8 eurio_ids × 9 marketplaces, 50 titres
   chacun. Une langue est "active" sur un marketplace si elle représente
   ≥ 10 % des titres classés (hors `unknown`).
2. **Recall PT** — 1 coin PT requêté sur EBAY_ES vs EBAY_GB. Si ES
   n'apporte pas ≥ ×2 le recall GB, PT repasse en GB-only.

Détection de langue : **heuristique maison** (mots-marqueurs numismatiques
+ function-words). ``langdetect`` a été essayé puis abandonné — il smear
systématiquement IT/ES vers `pt` sur les titres courts en majuscules.

Le JSON de sortie embarque **tous les titres bruts** par marketplace →
le classifieur peut être ré-itéré offline via ``--reclassify <json>``
sans re-taper l'API.

Coût quota : (8×9) + 2 = ~74 calls eBay.

Usage:
    python -m scripts.probe_marketplace_languages
    python -m scripts.probe_marketplace_languages --limit-mkt EBAY_FR,EBAY_GB
    python -m scripts.probe_marketplace_languages --reclassify state/probe_...json

Output : ``ml/state/probe_marketplace_languages_<timestamp>.json``.

Script jetable — supprimé après validation V1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.market.ebay_client import SEARCH_URL, get_app_token  # noqa: E402
from sources.ebay.queries import CATEGORY_EURO_COINS, build_query, load_coin  # noqa: E402
from sources.ebay.theme_tokens import normalize  # noqa: E402
from store import Store  # noqa: E402

# Échantillon : 1 commémo circulée (2012-2022) par grand pays + 2 micro-États.
DEFAULT_SAMPLE = [
    "fr-2022-2eur-90th-anniversary-of-president-jacques-chirac-s-birth",
    "de-2022-2eur-thuringia-s-wartburg-castle-in-eisenach",
    "it-2022-2eur-30th-anniversary-of-the-death-of-giovanni-falcone-and-paolo",
    "es-2022-2eur-garajonay-national-park-la-gomera",
    "nl-2014-2eur-king-willem-alexander-and-princess-beatrix",
    "be-2022-2eur-the-healthcare-sector-in-recognition-of-the-exceptional",
    "ad-2022-2eur-andorra-european-union-relations",
    "sm-2022-2eur-530-years-since-the-death-of-piero-della-francesca",
]

PT_PROBE_COIN = "pt-2021-2eur-portuguese-presidency-of-the-council-of-the-european-union"

# Marketplaces sondés + langue de query native (cf. vision.md §P3).
MARKETPLACES: dict[str, str] = {
    "EBAY_AT": "de",
    "EBAY_BE": "fr",
    "EBAY_DE": "de",
    "EBAY_ES": "es",
    "EBAY_FR": "fr",
    "EBAY_GB": "en",
    "EBAY_IE": "en",
    "EBAY_IT": "it",
    "EBAY_NL": "nl",
}

ACCEPT_LANG: dict[str, str] = {
    "EBAY_AT": "de-AT", "EBAY_BE": "fr-BE", "EBAY_DE": "de-DE",
    "EBAY_ES": "es-ES", "EBAY_FR": "fr-FR", "EBAY_GB": "en-GB",
    "EBAY_IE": "en-IE", "EBAY_IT": "it-IT", "EBAY_NL": "nl-NL",
}

ACTIVE_THRESHOLD = 0.10  # langue "active" si ≥ 10 % des titres classés
SEARCH_LIMIT = 50

# ── Classifieur heuristique ───────────────────────────────────────────────
# Marqueurs FORTS (weight 3) : noms numismatiques + orthographes
# discriminantes. Marqueurs FAIBLES (weight 1) : function-words.
# Tous écrits en forme normalisée (lowercase + NFKD drop-accents).
# Marqueurs FORTS = noms numismatiques + orthographes discriminantes
# + noms de pays dans la langue du vendeur (uniquement les formes
# SANS ambiguïté inter-langues — ex. "francia" IT∩ES est exclu).
STRONG: dict[str, set[str]] = {
    "fr": {"piece", "pieces", "monnaie", "neuve", "neuf", "coffret",
           "scellee", "etui", "piecette",
           "allemagne", "espagne", "autriche", "grece", "irlande"},
    # NB: "unc"/"bu"/"fdc"/"proof"/"coincard" exclus — abréviations de
    # grade et boilerplate internationaux, employés par les vendeurs de
    # toutes langues (ils polluaient massivement le bucket en).
    "en": {"coin", "coins", "uncirculated",
           "germany", "spain", "italy", "greece", "ireland"},
    "de": {"munze", "munzen", "gedenkmunze", "gedenkmunzen", "kursmunze",
           "stempelglanz", "bankfrisch", "auswahl",
           "frankreich", "deutschland", "spanien", "italien",
           "griechenland", "irland", "niederlande"},
    "it": {"moneta", "monete", "commemorativo", "commemorativa", "scegli",
           "spedizione", "conio",
           "germania", "spagna", "grecia", "irlanda"},
    "es": {"moneda", "monedas", "conmemorativa", "conmemorativo", "caja",
           "estuche", "alemania", "espana"},
    "nl": {"munt", "munten", "herdenkingsmunt", "circulatiemunt", "uitgifte",
           "frankrijk", "duitsland", "spanje", "griekenland", "oostenrijk",
           "ierland"},
    "pt": {"moeda", "moedas", "comemorativa"},
}
WEAK: dict[str, set[str]] = {
    "fr": {"le", "la", "les", "des", "avec", "pour", "sous", "dans",
           "vendeur", "livraison", "achat", "qualite", "annee"},
    "en": {"the", "and", "with", "from", "new", "mint", "year"},
    "de": {"und", "der", "die", "das", "von", "mit", "neu", "jahr"},
    "it": {"della", "dal", "tutti", "con", "del", "gli", "una", "anno"},
    "es": {"anos", "eleccion", "circular", "sin", "los", "las", "para",
           "ano", "con", "del"},
    "nl": {"van", "het", "een", "met", "nieuw", "jaar"},
    "pt": {"com", "para", "nova"},
}
_WORD_RE = re.compile(r"\W+")


def classify(title: str) -> str:
    """Langue dominante d'un titre eBay, ou 'unknown'.

    Score = 3×(marqueurs forts) + 1×(function-words). Argmax. En cas
    d'égalité ou de score nul → 'unknown' (titre non-discriminant, ex.
    "2 EURO FRANCIA 2022").
    """
    toks = set(t for t in _WORD_RE.split(normalize(title or "")) if t)
    if not toks:
        return "unknown"
    scores: dict[str, int] = {}
    for lang in STRONG:
        s = 3 * len(toks & STRONG[lang]) + 1 * len(toks & WEAK[lang])
        if s:
            scores[lang] = s
    if not scores:
        return "unknown"
    top = max(scores.values())
    winners = [l for l, s in scores.items() if s == top]
    return winners[0] if len(winners) == 1 else "unknown"


def search(token: str, marketplace: str, q: str) -> tuple[int, list[str], str | None]:
    """Returns (total, titles, error)."""
    try:
        resp = httpx.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": marketplace,
                "Accept-Language": ACCEPT_LANG.get(marketplace, "en-US"),
            },
            params={"q": q, "limit": SEARCH_LIMIT, "category_ids": CATEGORY_EURO_COINS},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        return 0, [], str(exc)[:200]
    if resp.status_code != 200:
        return 0, [], f"HTTP {resp.status_code}: {resp.text[:160]}"
    body = resp.json()
    summaries = body.get("itemSummaries") or []
    titles = [s.get("title") or "" for s in summaries]
    total = body.get("total")
    return (total if isinstance(total, int) else len(summaries)), titles, None


def summarize_titles(titles: list[str]) -> dict[str, Any]:
    """Classifie une liste de titres → distribution + actives + échantillons."""
    by_lang: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    for t in titles:
        lang = classify(t)
        by_lang[lang] += 1
        samples.setdefault(lang, [])
        if len(samples[lang]) < 6:
            samples[lang].append(t)
    n_total = len(titles)
    n_classified = n_total - by_lang.get("unknown", 0)
    active = sorted(
        [l for l, c in by_lang.items()
         if l != "unknown" and n_classified and c / n_classified >= ACTIVE_THRESHOLD],
        key=lambda l: -by_lang[l],
    )
    return {
        "n_titles_total": n_total,
        "n_classified": n_classified,
        "by_lang": dict(by_lang.most_common()),
        "active_langs": active,
        "sample_titles_by_lang": samples,
    }


def _print_mkt(mkt: str, summ: dict[str, Any]) -> None:
    n, nc = summ["n_titles_total"], summ["n_classified"]
    pct = {l: f"{100*c/nc:.0f}%" for l, c in summ["by_lang"].items()
           if l != "unknown" and nc} if nc else {}
    unk = summ["by_lang"].get("unknown", 0)
    print(f"  {mkt:9} n={n:3} classified={nc:3} unknown={unk:3}  "
          f"active={summ['active_langs']}  dist={pct}")


def probe_languages(token: str, conn, eurio_ids: list[str],
                    marketplaces: list[str]) -> dict[str, Any]:
    coins = {}
    for eid in eurio_ids:
        try:
            coins[eid] = load_coin(conn, eid)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! skip {eid}: {exc}")

    result: dict[str, Any] = {}
    for mkt in marketplaces:
        qlang = MARKETPLACES[mkt]
        raw_titles: list[str] = []
        for eid, coin in coins.items():
            q = build_query(coin, query_lang=qlang).q
            _, titles, err = search(token, mkt, q)
            if err:
                print(f"  !! {mkt} {eid}: {err}")
                continue
            raw_titles.extend(titles)
            time.sleep(0.3)
        summ = summarize_titles(raw_titles)
        summ["query_lang"] = qlang
        summ["raw_titles"] = raw_titles  # corpus brut → reclassify offline
        result[mkt] = summ
        _print_mkt(mkt, summ)
    return result


def probe_pt_recall(token: str, conn) -> dict[str, Any]:
    try:
        coin = load_coin(conn, PT_PROBE_COIN)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"load_coin failed: {exc}"}
    q_es = build_query(coin, query_lang="es").q
    q_en = build_query(coin, query_lang="en").q
    n_es, _, err_es = search(token, "EBAY_ES", q_es)
    n_gb, _, err_gb = search(token, "EBAY_GB", q_en)
    ratio = (n_es / n_gb) if n_gb else None
    verdict = "garder PT→ES" if (ratio is not None and ratio >= 2.0) else "repasser PT→GB-only"
    print(f"  PT recall : ES={n_es}  GB={n_gb}  ratio={ratio}  → {verdict}")
    return {
        "coin": PT_PROBE_COIN,
        "ebay_es": {"q": q_es, "n_results": n_es, "error": err_es},
        "ebay_gb": {"q": q_en, "n_results": n_gb, "error": err_gb},
        "ratio_es_over_gb": ratio,
        "verdict": verdict,
        "criterion": "garder PT→ES si n(ES) ≥ 2 × n(GB)",
    }


def reclassify(path: Path) -> int:
    """Relit un JSON de probe et re-applique ``classify`` sur les titres bruts."""
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"# Reclassify {path.name}")
    for mkt, summ in data["marketplaces"].items():
        raw = summ.get("raw_titles")
        if raw is None:
            print(f"  !! {mkt} : pas de raw_titles (ancien format) — skip")
            continue
        new = summarize_titles(raw)
        new["query_lang"] = summ.get("query_lang")
        new["raw_titles"] = raw
        data["marketplaces"][mkt] = new
        _print_mkt(mkt, new)
    data["reclassified_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "state" / f"probe_marketplace_languages_{ts}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-mkt", help="Sous-ensemble de marketplaces (CSV)")
    parser.add_argument("--skip-pt", action="store_true", help="Sauter le sous-probe PT")
    parser.add_argument("--reclassify", help="Relire un JSON existant et re-classifier")
    args = parser.parse_args()

    if args.reclassify:
        return reclassify(Path(args.reclassify))

    client_id = os.environ.get("EBAY_CLIENT_ID")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("ERROR: EBAY_CLIENT_ID / EBAY_CLIENT_SECRET manquants", file=sys.stderr)
        return 2

    marketplaces = list(MARKETPLACES)
    if args.limit_mkt:
        marketplaces = [m.strip() for m in args.limit_mkt.split(",") if m.strip()]

    token = get_app_token(client_id, client_secret)
    store = Store(db_path=ROOT / "state" / "eurio.db")
    conn = store._connection()  # noqa: SLF001

    print(f"# Probe langues : {len(DEFAULT_SAMPLE)} eurio × {len(marketplaces)} mkts")
    lang_result = probe_languages(token, conn, DEFAULT_SAMPLE, marketplaces)

    pt_result: dict[str, Any] = {}
    if not args.skip_pt:
        print("# Sous-probe PT recall (ES vs GB)")
        pt_result = probe_pt_recall(token, conn)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "samples": DEFAULT_SAMPLE,
        "active_threshold": ACTIVE_THRESHOLD,
        "classifier": "heuristic-markers-v1",
        "marketplaces": lang_result,
        "pt_recall": pt_result,
    }
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = ROOT / "state" / f"probe_marketplace_languages_{ts}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
