"""Gold benchmark + replay harness pour le theme-matcher (chunk P0).

Trois modes — cf. docs/sources-refacto/ebay-multi-marketplace/
theme-matcher-recall-kickoff.md §"Cadre de mesure".

  export  — échantillonne les listings d'un run réel, en sort un batch
            JSONL à étiqueter + un groups.json de contexte (I3 amont).
  ingest  — fusionne batch + labels en un gold gelé versionné (I1).
  replay  — rejoue le matcher courant sur le gold gelé, sort les
            métriques recall / précision / faux-rejet / auto-attribution
            (I2). Hors quota, déterministe.

Usage:
    python -m scripts.bench_theme_match export [--run b6bede99] [--sample 200]
    python -m scripts.bench_theme_match ingest
    python -m scripts.bench_theme_match replay
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))

from sources.ebay.filters import accept_listing  # noqa: E402
from sources.ebay.queries import match_listing_to_group  # noqa: E402
from store import Store  # noqa: E402

DB_PATH = ML_DIR / "state" / "eurio.db"
BENCH_DIR = ML_DIR / "state" / "discovery_bench"

BATCH_PATH = BENCH_DIR / "batch.jsonl"
GROUPS_PATH = BENCH_DIR / "groups.json"
LABELS_PATH = BENCH_DIR / "labels.jsonl"
GOLD_PATH = BENCH_DIR / "theme_match_gold.jsonl"

# Périmètre du seed : run réel BE 2017-2021.
SEED_YEARS = (2017, 2018, 2019, 2020, 2021)
_YEAR_RE = re.compile(r"\b(201[7-9]|202[01])\b")
I18N_LANGS = ("fr", "en", "de", "es", "it", "nl")


# ── helpers ───────────────────────────────────────────────────────────────

def _norm_listing_id(source_ref: str) -> str:
    """`ebay_v1|id|var_img3` ou `ebay_listing_v1|id|var` → `v1|id|var`."""
    s = re.sub(r"^ebay_(listing_)?", "", source_ref)
    return re.sub(r"_img\d+$", "", s)


def _year_from_skw(item_web_url: str | None) -> int | None:
    """Année du groupe depuis le `_skw` de l'URL eBay (= la requête)."""
    if not item_web_url:
        return None
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(item_web_url).query)
    except ValueError:
        return None
    skw = (qs.get("_skw") or [""])[0]
    m = _YEAR_RE.search(skw)
    return int(m.group(1)) if m else None


def _be_group_coins(conn) -> dict[int, list[str]]:
    """{année: [eurio_id, …]} des 2 € commémo BE des années du seed."""
    out: dict[int, list[str]] = {}
    for year in SEED_YEARS:
        rows = conn.execute(
            "SELECT eurio_id FROM coins WHERE country='BE' AND face_value=2.0 "
            "AND is_commemorative=1 AND year=? ORDER BY eurio_id",
            (year,),
        ).fetchall()
        out[year] = [r["eurio_id"] for r in rows]
    return out


# ── export ────────────────────────────────────────────────────────────────

def cmd_export(args: argparse.Namespace) -> int:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    store = Store(DB_PATH)
    conn = store._connection()  # noqa: SLF001

    run_like = f"{args.run}%"
    group_coins = _be_group_coins(conn)

    # eurio_id → année (pour le groupe des listings gardés).
    eid_year = {
        r["eurio_id"]: r["year"]
        for r in conn.execute(
            "SELECT eurio_id, year FROM coins WHERE country='BE' "
            "AND face_value=2.0 AND is_commemorative=1"
        ).fetchall()
    }

    listings: dict[str, dict] = {}  # listing_id → record

    # Listings GARDÉS — 1 row par image, dédup par listing_id.
    for r in conn.execute(
        "SELECT source_ref, listing_title, marketplace, target_eurio_id, "
        "listing_price, listing_currency "
        "FROM source_images WHERE run_id LIKE ? AND source='ebay'",
        (run_like,),
    ).fetchall():
        lid = _norm_listing_id(r["source_ref"])
        if lid in listings or not r["listing_title"]:
            continue
        year = eid_year.get(r["target_eurio_id"] or "")
        if year is None:
            continue
        listings[lid] = {
            "listing_id": lid,
            "title": r["listing_title"],
            "marketplace": r["marketplace"],
            "group_year": year,
            "bucket": "kept",
            "price": r["listing_price"],
            "currency": r["listing_currency"],
            "pipeline_outcome": f"kept→{r['target_eurio_id']}",
        }

    # Listings REJETÉS — groupe via `_skw` de l'URL.
    for r in conn.execute(
        "SELECT source_ref, title, marketplace, reason, raw_payload "
        "FROM discarded_listings WHERE run_id LIKE ? AND source='ebay'",
        (run_like,),
    ).fetchall():
        lid = _norm_listing_id(r["source_ref"])
        if lid in listings or not r["title"]:
            continue
        payload: dict = {}
        try:
            payload = json.loads(r["raw_payload"]) or {}
        except (json.JSONDecodeError, TypeError):
            pass
        year = _year_from_skw(payload.get("item_web_url"))
        if year is None:
            continue
        bucket = "theme_mismatch" if r["reason"] == "theme_mismatch" else "other_discard"
        listings[lid] = {
            "listing_id": lid,
            "title": r["title"],
            "marketplace": r["marketplace"],
            "group_year": year,
            "bucket": bucket,
            "price": payload.get("price"),
            "currency": payload.get("currency"),
            "pipeline_outcome": f"discarded:{r['reason']}",
        }

    # Échantillonnage stratifié par (année × bucket).
    by_stratum: dict[tuple, list[dict]] = defaultdict(list)
    for rec in listings.values():
        by_stratum[(rec["group_year"], rec["bucket"])].append(rec)

    rng = random.Random(args.seed)
    n_strata = len(by_stratum)
    per_stratum = max(1, args.sample // max(1, n_strata))
    sampled: list[dict] = []
    for stratum, recs in sorted(by_stratum.items()):
        rng.shuffle(recs)
        sampled.extend(recs[:per_stratum])
    rng.shuffle(sampled)

    with BATCH_PATH.open("w") as f:
        for rec in sampled:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # groups.json — contexte de jugement : coins candidats par année.
    groups_ctx: dict[str, list[dict]] = {}
    for year, ids in group_coins.items():
        coins = []
        for eid in ids:
            crow = conn.execute(
                "SELECT theme FROM coins WHERE eurio_id=?", (eid,)
            ).fetchone()
            i18n = {
                lr["lang"]: lr["title"]
                for lr in conn.execute(
                    "SELECT lang, title FROM coin_names_i18n WHERE eurio_id=?",
                    (eid,),
                ).fetchall()
            }
            coins.append({
                "eurio_id": eid,
                "theme": crow["theme"] if crow else None,
                "i18n": {k: i18n[k] for k in I18N_LANGS if k in i18n},
            })
        groups_ctx[str(year)] = coins
    GROUPS_PATH.write_text(json.dumps(groups_ctx, ensure_ascii=False, indent=2))

    dist = Counter((r["group_year"], r["bucket"]) for r in sampled)
    print(f"export → {BATCH_PATH}  ({len(sampled)} listings, "
          f"{len(listings)} disponibles)")
    print(f"contexte → {GROUPS_PATH}")
    for (year, bucket), n in sorted(dist.items()):
        print(f"  {year} {bucket:16s} {n}")
    return 0


# ── ingest ────────────────────────────────────────────────────────────────

def cmd_ingest(args: argparse.Namespace) -> int:
    if not BATCH_PATH.exists() or not LABELS_PATH.exists():
        print(f"manque {BATCH_PATH} ou {LABELS_PATH}", file=sys.stderr)
        return 1
    batch = {
        json.loads(ln)["listing_id"]: json.loads(ln)
        for ln in BATCH_PATH.read_text().splitlines() if ln.strip()
    }
    labels = {
        json.loads(ln)["listing_id"]: json.loads(ln)
        for ln in LABELS_PATH.read_text().splitlines() if ln.strip()
    }
    missing = set(batch) - set(labels)
    if missing:
        print(f"⚠ {len(missing)} listing(s) du batch sans label — non gelés",
              file=sys.stderr)

    valid_verdicts = {"lot", "not-a-coin", "wrong-scope", "ambiguous"}
    gold: list[dict] = []
    for lid, label in labels.items():
        if lid not in batch:
            print(f"⚠ label inconnu ignoré : {lid}", file=sys.stderr)
            continue
        verdict = label["verdict"]
        if not (verdict in valid_verdicts or verdict.startswith("coin:")):
            print(f"⚠ verdict invalide {verdict!r} ({lid})", file=sys.stderr)
            return 1
        rec = dict(batch[lid])
        rec["group_year"] = label.get("group_year", rec["group_year"])
        rec["verdict"] = verdict
        if label.get("note"):
            rec["note"] = label["note"]
        gold.append(rec)

    gold.sort(key=lambda r: (r["group_year"], r["listing_id"]))
    with GOLD_PATH.open("w") as f:
        for rec in gold:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"gold gelé → {GOLD_PATH}  ({len(gold)} entrées)")
    print("distribution verdicts :")
    for v, n in sorted(Counter(
        r["verdict"].split(":")[0] for r in gold
    ).items()):
        print(f"  {v:14s} {n}")
    return 0


# ── replay ────────────────────────────────────────────────────────────────

def replay_bench(conn) -> dict:
    """Rejoue le pipeline (accept_listing + theme-matcher) sur le gold gelé.

    Source de vérité unique du bench, partagée par le CLI (``cmd_replay``)
    et l'API (``api/bench_routes.py``). Renvoie un dict :

    - ``listings`` : une entrée structurée par listing du gold — donnée,
      label humain, sorties étape par étape, issue, flag d'accord ;
    - ``metrics``  : les agrégats (faux rejet, recall, auto-attribution…).

    Déterministe, hors quota. Lève ``FileNotFoundError`` si le gold manque.
    """
    if not GOLD_PATH.exists():
        raise FileNotFoundError(
            f"gold absent : {GOLD_PATH} — lancer ingest d'abord"
        )
    group_coins = _be_group_coins(conn)
    gold = [json.loads(ln) for ln in GOLD_PATH.read_text().splitlines() if ln.strip()]

    n_valid = n_false_discard = n_auto_correct = n_auto_wrong = 0
    n_kept_review = 0
    n_junk = n_correct_discard = n_false_keep = 0
    n_auto_total = 0
    n_accept_rej = n_matcher_rej = 0
    lot_outcomes: Counter = Counter()
    listings: list[dict] = []

    for g in gold:
        verdict = g["verdict"]
        ids = group_coins.get(g["group_year"], [])
        # Réplique fidèle du pipeline : accept_listing PUIS le matcher.
        ok, reason = accept_listing(
            {"title": g["title"], "price": g.get("price"),
             "currency": g.get("currency")},
            2.0, expected_year=g["group_year"], is_commemorative=True,
        )
        matcher: dict | None = None
        gm = None
        if not ok:
            mv = f"accept:{reason}"
            discarded = True
            n_accept_rej += 1
        else:
            gm = match_listing_to_group(g["title"], ids, conn=conn)
            mv = gm.verdict
            discarded = mv == "no_match"
            matcher = {
                "verdict": gm.verdict,
                "matched": list(gm.matched),
                "contradictions": list(gm.contradictions),
            }
            if discarded:
                n_matcher_rej += 1
            if mv == "single":
                n_auto_total += 1

        if verdict.startswith("coin:") or verdict == "ambiguous":
            n_valid += 1
            want = verdict.split(":", 1)[1] if ":" in verdict else None
            if discarded:
                n_false_discard += 1
                outcome = "FALSE_DISCARD"
            elif mv == "single" and want and gm and gm.matched == (want,):
                n_auto_correct += 1
                outcome = "auto_ok"
            elif mv == "single":
                n_auto_wrong += 1
                outcome = "auto_WRONG"
            else:  # ambiguous / lot — gardé, routé en review
                n_kept_review += 1
                outcome = "review"
        elif verdict in ("not-a-coin", "wrong-scope"):
            n_junk += 1
            if discarded:
                n_correct_discard += 1
                outcome = "junk_discarded"
            else:
                n_false_keep += 1
                outcome = "FALSE_KEEP"
        else:  # lot
            lot_outcomes["discarded" if discarded else mv] += 1
            outcome = f"lot→{'discarded' if discarded else mv}"

        listings.append({
            "listing_id": g["listing_id"],
            "title": g["title"],
            "marketplace": g.get("marketplace"),
            "group_year": g["group_year"],
            "price": g.get("price"),
            "currency": g.get("currency"),
            "bucket": g.get("bucket"),
            "note": g.get("note"),
            "verdict": verdict,
            "accept": {"ok": ok, "reason": reason},
            "matcher": matcher,
            "outcome": outcome,
            "agreement": "WRONG" not in outcome and "FALSE" not in outcome,
        })

    def rate(num: int, den: int) -> float | None:
        return num / den if den else None

    metrics = {
        "total": len(gold),
        "n_valid": n_valid,
        "n_false_discard": n_false_discard,
        "false_discard_rate": rate(n_false_discard, n_valid),
        "recall_rate": rate(n_valid - n_false_discard, n_valid),
        "n_auto_correct": n_auto_correct,
        "auto_attribution_rate": rate(n_auto_correct, n_valid),
        "n_kept_review": n_kept_review,
        "review_rate": rate(n_kept_review, n_valid),
        "n_auto_total": n_auto_total,
        "precision": rate(n_auto_correct, n_auto_total),
        "n_auto_wrong": n_auto_wrong,
        "n_junk": n_junk,
        "n_correct_discard": n_correct_discard,
        "n_false_keep": n_false_keep,
        "false_keep_rate": rate(n_false_keep, n_junk),
        "lot_outcomes": dict(lot_outcomes),
        "n_accept_rej": n_accept_rej,
        "n_matcher_rej": n_matcher_rej,
    }
    return {"listings": listings, "metrics": metrics}


def cmd_replay(args: argparse.Namespace) -> int:
    store = Store(DB_PATH)
    conn = store._connection()  # noqa: SLF001
    try:
        result = replay_bench(conn)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    m = result["metrics"]

    def pct(num: int, den: int | None) -> str:
        if not den:
            return "   n/a"
        return f"{100*num/den:5.1f}%  ({num}/{den})"

    print("=" * 68)
    print(f"REPLAY pipeline (accept_listing + theme-matcher) — {GOLD_PATH.name}"
          f"  ({m['total']} entrées)")
    print("=" * 68)
    print(f"  pièces valides du périmètre        {m['n_valid']}")
    print(f"  TAUX DE FAUX REJET                 {pct(m['n_false_discard'], m['n_valid'])}")
    print(f"  recall (gardé quelque part)        "
          f"{pct(m['n_valid'] - m['n_false_discard'], m['n_valid'])}")
    print(f"  TAUX D'AUTO-ATTRIBUTION  ★         {pct(m['n_auto_correct'], m['n_valid'])}")
    print(f"    dont en review (pas auto)        {pct(m['n_kept_review'], m['n_valid'])}")
    print(f"  précision des auto-attributions    "
          f"{pct(m['n_auto_correct'], m['n_auto_total'])}")
    print(f"    auto-attributions erronées       {m['n_auto_wrong']}")
    print(f"  junk (not-a-coin / wrong-scope)    {m['n_junk']}")
    print(f"    correctement rejeté              {pct(m['n_correct_discard'], m['n_junk'])}")
    print(f"    FALSE KEEP (junk gardé)          {pct(m['n_false_keep'], m['n_junk'])}")
    if m["lot_outcomes"]:
        print(f"  lots — verdicts : {m['lot_outcomes']}")
    print(f"  rejets : accept_listing {m['n_accept_rej']} · matcher {m['n_matcher_rej']}")
    print("-" * 68)

    if args.verbose:
        for r in sorted(result["listings"],
                        key=lambda x: (x["group_year"], x["listing_id"])):
            mv = r["matcher"]["verdict"] if r["matcher"] else r["accept"]["reason"]
            flag = "  ⚠" if not r["agreement"] else "   "
            print(f"{flag} {r['group_year']} {r['verdict']:30s} → {mv:14s} "
                  f"{r['outcome']:15s} {r['title'][:52]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export", help="échantillonne un batch à étiqueter")
    p_exp.add_argument("--run", default="b6bede99", help="préfixe du run_id seed")
    p_exp.add_argument("--sample", type=int, default=200, help="taille cible")
    p_exp.add_argument("--seed", type=int, default=42, help="seed RNG")

    sub.add_parser("ingest", help="fusionne batch + labels → gold gelé")

    p_rep = sub.add_parser("replay", help="rejoue le matcher sur le gold")
    p_rep.add_argument("-v", "--verbose", action="store_true",
                       help="détail par listing")

    args = parser.parse_args()
    if args.cmd == "export":
        return cmd_export(args)
    if args.cmd == "ingest":
        return cmd_ingest(args)
    if args.cmd == "replay":
        return cmd_replay(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
