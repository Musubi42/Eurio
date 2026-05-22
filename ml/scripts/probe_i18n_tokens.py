"""Probe — validation empirique des stop-words de theme_tokens.

Cf. chunk C du kickoff I2 (``i18n-theme-matcher-kickoff.md``) et le
critère de ``language-probe.md`` §"Stop-words : critère de validation".

Lit tous les titres ``coin_names_i18n`` par langue, applique
``extract_tokens``, et imprime la distribution du nombre de tokens
utiles + les tokens les plus fréquents (candidats stop-words manqués).

Critère : médiane de tokens utiles ∈ [2, 6].
- médiane > 6 → stop-words sous-spécifiés (faux positifs en vue)
- médiane < 2 → stop-words trop agressifs (faux négatifs)

Usage:
    python -m scripts.probe_i18n_tokens
    python -m scripts.probe_i18n_tokens --lang fr
    python -m scripts.probe_i18n_tokens --sample 50      # sous-échantillon
    python -m scripts.probe_i18n_tokens --top-tokens 30

Script jetable — supprimé après tuning des stop-words (V2 cutover).
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.ebay.theme_tokens import extract_tokens  # noqa: E402

DB_PATH = ROOT / "state" / "eurio.db"


def _percentile(sorted_vals: list[int], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def probe_lang(conn: sqlite3.Connection, lang: str, *, sample: int | None,
               top_tokens: int) -> None:
    rows = conn.execute(
        "SELECT eurio_id, title FROM coin_names_i18n WHERE lang=? ORDER BY eurio_id",
        (lang,),
    ).fetchall()
    if sample is not None:
        # Échantillon stratifié simple : 1 sur N pour couvrir tout l'alphabet.
        step = max(1, len(rows) // sample)
        rows = rows[::step][:sample]

    if not rows:
        print(f"\n[{lang}] aucune row coin_names_i18n — skip")
        return

    counts: list[int] = []
    token_freq: Counter[str] = Counter()
    zero_token: list[tuple[str, str]] = []
    over_six: list[tuple[str, str, list[str]]] = []
    examples: list[tuple[str, str, list[str]]] = []

    for eurio_id, title in rows:
        toks = extract_tokens(title, lang)
        counts.append(len(toks))
        token_freq.update(toks)
        if len(toks) == 0:
            zero_token.append((eurio_id, title))
        if len(toks) > 6:
            over_six.append((eurio_id, title, toks))
        if len(examples) < 5:
            examples.append((eurio_id, title, toks))

    counts_sorted = sorted(counts)
    median = statistics.median(counts_sorted)
    mean = statistics.mean(counts_sorted)
    p25 = _percentile(counts_sorted, 0.25)
    p75 = _percentile(counts_sorted, 0.75)
    n_zero = len(zero_token)
    n_over = len(over_six)
    n = len(rows)

    verdict = "OK" if 2 <= median <= 6 else ("TROP BAS" if median < 2 else "TROP HAUT")

    print(f"\n{'='*64}")
    print(f"[{lang}]  n={n} titres" + (f" (échantillon de {sample})" if sample else ""))
    print(f"{'='*64}")
    print(f"  tokens/titre : median={median:.1f}  mean={mean:.2f}  "
          f"min={counts_sorted[0]}  p25={p25:.1f}  p75={p75:.1f}  max={counts_sorted[-1]}")
    print(f"  médiane ∈ [2,6] ? → {verdict}")
    print(f"  titres à 0 token  : {n_zero}/{n} ({100*n_zero/n:.0f}%)")
    print(f"  titres à >6 tokens: {n_over}/{n} ({100*n_over/n:.0f}%)")

    print(f"\n  -- 5 exemples --")
    for eurio_id, title, toks in examples:
        print(f"    {title!r:50} → {toks}")

    if zero_token:
        print(f"\n  -- titres à 0 token (max 8) --")
        for eurio_id, title in zero_token[:8]:
            print(f"    {title!r}")

    if over_six:
        print(f"\n  -- titres à >6 tokens (max 5) --")
        for eurio_id, title, toks in over_six[:5]:
            print(f"    {title!r:50} → {toks}")

    print(f"\n  -- {top_tokens} tokens les plus fréquents (candidats stop-words) --")
    for tok, freq in token_freq.most_common(top_tokens):
        print(f"    {freq:4}×  {tok}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", help="Langue unique (défaut: toutes présentes)")
    parser.add_argument("--sample", type=int, help="Sous-échantillon stratifié")
    parser.add_argument("--top-tokens", type=int, default=25)
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        if args.lang:
            langs = [args.lang]
        else:
            langs = [r[0] for r in conn.execute(
                "SELECT DISTINCT lang FROM coin_names_i18n ORDER BY lang"
            ).fetchall()]
        if not langs:
            print("coin_names_i18n vide — rien à prober.")
            return
        for lang in langs:
            probe_lang(conn, lang, sample=args.sample, top_tokens=args.top_tokens)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
