"""Bench Claude vision sur le gold set de review humaine.

But : mesurer quel modèle Claude (Haiku 4.5 / Sonnet 4.6 / Opus 4.7) tranche
au mieux la question « la pièce visible dans le CROP correspond-elle au
TARGET proposé par theme-match ? » — c'est-à-dire le job qu'on veut confier
à la voie ccproxy pour les cas ambigus (partial + divergent).

Ground truth = décisions humaines (``decided_by='admin'``) :
  - ``decided_eurio_id == target_eurio_id``  → ground = "match"
  - ``decided_eurio_id != target_eurio_id``  → ground = "no_match" (humain a corrigé)
  - ``decision_notes='rejected'``            → ground = "no_match" (image inutilisable)
  - ``decided_eurio_id IS NULL`` sans rejected → exclu (skip)

Le bench appelle ccproxy en mode vision (crop + canonical inline base64) pour
chaque (item, modèle), parse le JSON, et compare. Sortie : CSV des décisions
brutes + résumé console (accuracy, precision, recall, F1, tokens, coût).

Usage :
  python -m scripts.bench_claude_review                       # full run, 3 modèles
  python -m scripts.bench_claude_review --models haiku --limit 5  # smoke test
  python -m scripts.bench_claude_review --out bench_2026-05-25.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Permet ``python -m scripts.bench_claude_review`` ET ``python ml/scripts/bench_claude_review.py``.
ML_DIR = Path(__file__).resolve().parent.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))

from ccproxy_client import (  # noqa: E402
    ChatResult,
    chat,
    health,
    image_part,
    parse_json_response,
    text_part,
)
from storage.local_cache import local_path  # noqa: E402

logger = logging.getLogger("bench")

DB_PATH = ML_DIR / "state" / "eurio.db"
DATASETS_DIR = ML_DIR / "datasets"

MODELS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
}

# ─── Prompt ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a numismatic expert reviewing online listings of euro "
    "commemorative coins.\n\n"
    "You will see two images:\n"
    "  1. CROP — a coin extracted from an online marketplace photo.\n"
    "  2. CANONICAL — the official reference image of the proposed target coin.\n\n"
    "Decide whether the CROP shows THE SAME coin design as the CANONICAL.\n"
    "Same coin = same country, year, and commemorative design.\n"
    "Allow for: wear, lighting, angle, partial crop, low resolution.\n"
    "Different coin = different design, year, or country, OR the crop shows "
    "something that is not the target (multi-coin photo with wrong coin "
    "centered, unrelated object, unreadable).\n\n"
    "Respond with ONE LINE of strict JSON, nothing else. No preamble, no "
    "explanation outside the fields, no markdown fences.\n"
    'Schema: {"verdict":"match"|"no_match"|"uncertain",'
    '"face":"obverse"|"reverse"|"unknown",'
    '"confidence":<float 0..1>}\n'
)


def build_user_parts(
    *, crop_path: Path, canonical_path: Path,
    target_label: str, listing_title: str,
) -> list[dict]:
    return [
        text_part("Image 1 — CROP from listing:"),
        image_part(crop_path),
        text_part("Image 2 — CANONICAL reference of proposed target:"),
        image_part(canonical_path),
        text_part(
            f"Proposed target: {target_label}\n"
            f"Listing title: {listing_title or '(empty)'}\n\n"
            "JSON verdict:"
        ),
    ]


# ─── Gold set ───────────────────────────────────────────────────────────────


@dataclass
class GoldItem:
    review_id: str
    asset_id: str
    storage_path: str
    target_eurio_id: str
    target_label: str
    target_numista_id: int | None
    listing_title: str
    decided_eurio_id: str | None
    decision_notes: str | None
    ground: str  # 'match' | 'no_match'

    @property
    def crop_path(self) -> Path:
        return local_path("enrichment-crops", self.storage_path)

    @property
    def canonical_path(self) -> Path | None:
        if not self.target_numista_id:
            return None
        coin_dir = DATASETS_DIR / str(self.target_numista_id)
        if not coin_dir.exists():
            return None
        for name in ("obverse.jpg", "obverse.png", "obverse.jpeg"):
            p = coin_dir / name
            if p.exists():
                return p
        # Fallback : premier fichier image
        for f in sorted(coin_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                return f
        return None


def load_gold_set(limit: int | None = None) -> list[GoldItem]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT rq.id AS review_id,
               rq.image_asset_id AS asset_id,
               rq.decided_eurio_id,
               rq.decision_notes,
               a.storage_path,
               s.target_eurio_id,
               s.listing_title,
               c.country_name AS t_country_name,
               c.year         AS t_year,
               c.theme        AS t_theme,
               c.numista_id   AS t_numista_id
          FROM review_queue rq
          JOIN image_assets a ON a.id = rq.image_asset_id
          JOIN source_images s ON s.id = a.source_image_id
          LEFT JOIN coins c ON c.eurio_id = s.target_eurio_id
         WHERE rq.decided_by = 'admin'
           AND a.storage_path IS NOT NULL
           AND s.target_eurio_id IS NOT NULL
         ORDER BY rq.decided_at DESC
        """
    ).fetchall()

    items: list[GoldItem] = []
    for r in rows:
        if r["decision_notes"] == "rejected":
            ground = "no_match"
        elif r["decided_eurio_id"] is None:
            continue  # skip
        elif r["decided_eurio_id"] == r["target_eurio_id"]:
            ground = "match"
        else:
            ground = "no_match"

        bits = [r["t_country_name"], str(r["t_year"]) if r["t_year"] else None, r["t_theme"]]
        label = " · ".join(b for b in bits if b) or r["target_eurio_id"]
        items.append(GoldItem(
            review_id=r["review_id"],
            asset_id=r["asset_id"],
            storage_path=r["storage_path"],
            target_eurio_id=r["target_eurio_id"],
            target_label=label,
            target_numista_id=r["t_numista_id"],
            listing_title=r["listing_title"] or "",
            decided_eurio_id=r["decided_eurio_id"],
            decision_notes=r["decision_notes"],
            ground=ground,
        ))
        if limit and len(items) >= limit:
            break

    return items


# ─── Bench loop ─────────────────────────────────────────────────────────────


@dataclass
class CallResult:
    review_id: str
    model_alias: str
    model_id: str
    ground: str
    verdict: str | None
    face: str | None
    confidence: float | None
    raw_content: str
    tokens_in: int
    tokens_out: int
    cache_read: int
    cost_usd: float
    duration_ms: int
    error: str | None = None


def run_single(
    item: GoldItem, model_alias: str, model_id: str, base_url: str,
) -> CallResult:
    canonical = item.canonical_path
    if canonical is None:
        return CallResult(
            review_id=item.review_id, model_alias=model_alias, model_id=model_id,
            ground=item.ground, verdict=None, face=None, confidence=None,
            raw_content="", tokens_in=0, tokens_out=0, cache_read=0,
            cost_usd=0.0, duration_ms=0,
            error=f"no canonical image for numista_id={item.target_numista_id}",
        )
    try:
        user_parts = build_user_parts(
            crop_path=item.crop_path,
            canonical_path=canonical,
            target_label=item.target_label,
            listing_title=item.listing_title,
        )
        result: ChatResult = chat(
            model=model_id, system=SYSTEM_PROMPT,
            user_parts=user_parts, base_url=base_url,
        )
    except Exception as exc:  # noqa: BLE001
        return CallResult(
            review_id=item.review_id, model_alias=model_alias, model_id=model_id,
            ground=item.ground, verdict=None, face=None, confidence=None,
            raw_content="", tokens_in=0, tokens_out=0, cache_read=0,
            cost_usd=0.0, duration_ms=0,
            error=f"{type(exc).__name__}: {exc}",
        )

    parsed = parse_json_response(result.content)
    verdict = face = confidence = None
    if parsed is not None:
        v = parsed.get("verdict")
        if v in ("match", "no_match", "uncertain"):
            verdict = v
        f = parsed.get("face")
        if f in ("obverse", "reverse", "unknown"):
            face = f
        c = parsed.get("confidence")
        if isinstance(c, (int, float)):
            confidence = float(c)

    return CallResult(
        review_id=item.review_id, model_alias=model_alias, model_id=model_id,
        ground=item.ground, verdict=verdict, face=face, confidence=confidence,
        raw_content=result.content,
        tokens_in=result.tokens_in, tokens_out=result.tokens_out,
        cache_read=result.cache_read_tokens,
        cost_usd=result.cost_usd, duration_ms=result.duration_ms,
    )


# ─── Reporting ──────────────────────────────────────────────────────────────


def classify(predicted: str | None) -> str:
    """Mappe verdict en binaire pour scorer : uncertain → no_match (default
    conservatif côté pipeline ; un cas incertain partira en review humaine)."""
    if predicted == "match":
        return "match"
    return "no_match"


def summarize(results: list[CallResult]) -> dict[str, dict]:
    by_model: dict[str, dict] = defaultdict(lambda: {
        "n": 0, "ok": 0, "err": 0, "parse_fail": 0,
        "tp": 0, "fp": 0, "tn": 0, "fn": 0,
        "uncertain": 0,
        "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "duration_ms": 0,
    })
    for r in results:
        m = by_model[r.model_alias]
        m["n"] += 1
        if r.error:
            m["err"] += 1
            continue
        if r.verdict is None:
            m["parse_fail"] += 1
            continue
        if r.verdict == "uncertain":
            m["uncertain"] += 1
        m["ok"] += 1
        pred = classify(r.verdict)
        if pred == "match" and r.ground == "match":   m["tp"] += 1
        elif pred == "match" and r.ground == "no_match": m["fp"] += 1
        elif pred == "no_match" and r.ground == "no_match": m["tn"] += 1
        elif pred == "no_match" and r.ground == "match": m["fn"] += 1
        m["tokens_in"] += r.tokens_in
        m["tokens_out"] += r.tokens_out
        m["cost_usd"] += r.cost_usd
        m["duration_ms"] += r.duration_ms

    out = {}
    for alias, m in by_model.items():
        scored = m["tp"] + m["fp"] + m["tn"] + m["fn"]
        accuracy = (m["tp"] + m["tn"]) / scored if scored else 0
        prec = m["tp"] / (m["tp"] + m["fp"]) if (m["tp"] + m["fp"]) else 0
        rec  = m["tp"] / (m["tp"] + m["fn"]) if (m["tp"] + m["fn"]) else 0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
        ok = max(m["ok"], 1)
        out[alias] = {
            **m,
            "accuracy": accuracy, "precision_match": prec,
            "recall_match": rec, "f1_match": f1,
            "tokens_in_avg": m["tokens_in"] / ok,
            "tokens_out_avg": m["tokens_out"] / ok,
            "cost_per_100": (m["cost_usd"] / ok) * 100,
            "duration_ms_avg": m["duration_ms"] / ok,
        }
    return out


def print_summary(summary: dict[str, dict]) -> None:
    print()
    print("═" * 96)
    print(f"{'MODEL':<10} {'n':>4} {'acc':>6} {'prec':>6} {'rec':>6} {'F1':>6} "
          f"{'tok_in':>8} {'tok_out':>8} {'$/100':>8} {'ms_avg':>8} "
          f"{'unc':>4} {'err':>4} {'pf':>4}")
    print("─" * 96)
    for alias, m in summary.items():
        print(
            f"{alias:<10} {m['n']:>4} "
            f"{m['accuracy']*100:>5.1f}% "
            f"{m['precision_match']*100:>5.1f}% "
            f"{m['recall_match']*100:>5.1f}% "
            f"{m['f1_match']*100:>5.1f}% "
            f"{m['tokens_in_avg']:>8.0f} "
            f"{m['tokens_out_avg']:>8.0f} "
            f"${m['cost_per_100']:>6.3f} "
            f"{m['duration_ms_avg']:>8.0f} "
            f"{m['uncertain']:>4} {m['err']:>4} {m['parse_fail']:>4}"
        )
    print("═" * 96)
    print("Legend: acc=binary accuracy · prec/rec/F1 on the 'match' class")
    print("        unc=uncertain · err=ccproxy/network error · pf=JSON parse fail")
    print("        $/100 = anthropic cost extrapolated to 100 successful calls")


# ─── Main ───────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Bench Claude vision pour review queue")
    parser.add_argument("--models", nargs="+", default=list(MODELS.keys()),
                        choices=list(MODELS.keys()),
                        help="Modèles à tester (alias).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limite items du gold set (smoke test).")
    parser.add_argument("--base-url", default="http://127.0.0.1:3002")
    parser.add_argument("--out", type=Path, default=ML_DIR / "state" / "bench_claude_review.csv")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Pré-flight ccproxy
    try:
        h = health(args.base_url)
        print(f"[health] ccproxy OK · claude={h.get('claude_version', '?')}")
    except Exception as exc:  # noqa: BLE001
        print(f"[health] ccproxy unreachable at {args.base_url}: {exc}", file=sys.stderr)
        print("Démarre ccproxy : cd services/ccproxy && ./bin/ccproxy --debug", file=sys.stderr)
        return 2

    items = load_gold_set(limit=args.limit)
    print(f"[gold] {len(items)} items chargés "
          f"(match={sum(1 for it in items if it.ground == 'match')}, "
          f"no_match={sum(1 for it in items if it.ground == 'no_match')})")
    if not items:
        print("Gold set vide — rien à bencher.", file=sys.stderr)
        return 1

    # Filtre items dont la canonical existe sur disque
    items = [it for it in items if it.canonical_path is not None]
    print(f"[gold] {len(items)} items après filtre canonical disponible")

    results: list[CallResult] = []
    total = len(items) * len(args.models)
    done = 0
    t_start = time.monotonic()

    for alias in args.models:
        model_id = MODELS[alias]
        print(f"\n[{alias}] {model_id}  ({len(items)} items)")
        for i, item in enumerate(items, 1):
            r = run_single(item, alias, model_id, args.base_url)
            results.append(r)
            done += 1
            elapsed = time.monotonic() - t_start
            eta = (elapsed / done) * (total - done) if done else 0
            tag = "OK"
            if r.error:
                tag = f"ERR ({r.error[:40]})"
            elif r.verdict is None:
                tag = f"PARSE_FAIL ({r.raw_content[:30]!r})"
            else:
                hit = "✓" if classify(r.verdict) == r.ground else "✗"
                tag = f"{hit} pred={r.verdict:<9} gt={r.ground}"
            print(f"  [{i:>3}/{len(items)}] {item.review_id[:8]}  {tag}  "
                  f"({r.duration_ms} ms, in={r.tokens_in} out={r.tokens_out})  "
                  f"eta={int(eta)}s")

    # Save CSV
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "review_id", "model_alias", "model_id", "ground",
            "verdict", "face", "confidence",
            "tokens_in", "tokens_out", "cache_read", "cost_usd", "duration_ms",
            "error", "raw_content",
        ])
        for r in results:
            w.writerow([
                r.review_id, r.model_alias, r.model_id, r.ground,
                r.verdict or "", r.face or "",
                f"{r.confidence:.3f}" if r.confidence is not None else "",
                r.tokens_in, r.tokens_out, r.cache_read,
                f"{r.cost_usd:.6f}", r.duration_ms,
                r.error or "", r.raw_content,
            ])
    print(f"\n[csv] {len(results)} rows → {args.out}")

    print_summary(summarize(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
