"""One-shot : fige le gold denom provisoire (labels visuels Claude, 2026-06-13).

Labels par index (tri par bimetal_score croissant, cf. gold_index.json). Source =
pass visuel sur state/denom_bench/label_page*.png (224² natif). Schéma :
  label ∈ {pos, neg, unk}  · kind (neg) ∈ {cent, medal, chart, other} · conf ∈ {hi, lo}
`pos` = vrai 2€ ; `neg` = pas un 2€ ; `unk` = pièce obscurcie (capsule/lot/flou),
dénomination non vérifiable → à trancher par un humain.
⚠️ provisoire : les `lo` (et tous les `unk`) demandent une vérif humaine.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "state" / "denom_bench"

# idx -> (label, kind|None, conf)
LBL: dict[int, tuple[str, str | None, str]] = {
    # ---- page 0 (0-14) : zone basse-score, dominée par le junk -------------
    0: ("neg", "medal", "hi"),   1: ("neg", "medal", "lo"),   2: ("neg", "other", "lo"),  # 2≈1€ (anneau or/centre argent)
    3: ("pos", None, "lo"),      4: ("neg", "cent", "hi"),    5: ("neg", "medal", "hi"),  # 3: 2€ en capsule (full-res)
    6: ("pos", None, "lo"),      7: ("pos", None, "lo"),      8: ("neg", "medal", "hi"),  # 7: 2€ en holder ; 8: médaille tête classique
    9: ("neg", "cent", "hi"),    10: ("pos", None, "lo"),     11: ("neg", "cent", "lo"),
    12: ("pos", None, "hi"),     13: ("neg", "chart", "hi"),  14: ("neg", "medal", "hi"),  # 12: 2€ commémo en capsule
    # ---- page 1 (15-29) ----------------------------------------------------
    15: ("neg", "cent", "hi"),   16: ("neg", "medal", "hi"),  17: ("neg", "medal", "hi"),  # 17: même médaille tête classique que 8
    18: ("neg", "cent", "hi"),   19: ("pos", None, "lo"),     20: ("neg", "cent", "lo"),
    21: ("pos", None, "hi"),     22: ("pos", None, "hi"),     23: ("pos", None, "lo"),
    24: ("pos", None, "lo"),     25: ("pos", None, "lo"),     26: ("pos", None, "lo"),
    27: ("pos", None, "lo"),     28: ("pos", None, "lo"),     29: ("pos", None, "lo"),
    # ---- page 2 (30-44) ----------------------------------------------------
    30: ("pos", None, "lo"),     31: ("neg", "cent", "lo"),   32: ("pos", None, "hi"),
    33: ("neg", "chart", "hi"),  34: ("neg", "cent", "lo"),   35: ("pos", None, "hi"),
    36: ("pos", None, "hi"),     37: ("pos", None, "hi"),     38: ("neg", "cent", "lo"),  # 37: 2€ bimétal clair (full-res)
    39: ("pos", None, "lo"),     40: ("neg", "chart", "hi"),  41: ("pos", None, "lo"),
    42: ("neg", "cent", "lo"),   43: ("neg", "cent", "lo"),   44: ("neg", "cent", "lo"),
    # ---- page 3 (45-59) ----------------------------------------------------
    45: ("pos", None, "hi"),     46: ("neg", "other", "lo"),  47: ("neg", "cent", "lo"),  # 46: SET multi-pièces, pas un 2€
    48: ("neg", "cent", "lo"),   49: ("pos", None, "hi"),     50: ("pos", None, "hi"),    # 49: 2€ bimétal en capsule
    51: ("neg", "cent", "lo"),   52: ("pos", None, "hi"),     53: ("pos", None, "hi"),
    54: ("pos", None, "lo"),     55: ("pos", None, "lo"),     56: ("neg", "medal", "hi"),  # 54: 2€ commémo en capsule
    57: ("pos", None, "lo"),     58: ("pos", None, "lo"),     59: ("pos", None, "hi"),    # 59: 2€ bimétal en capsule
    # ---- page 4 (60-74) : majorité 2€ ------------------------------------
    60: ("pos", None, "lo"),     61: ("pos", None, "hi"),     62: ("pos", None, "lo"),
    63: ("pos", None, "lo"),     64: ("pos", None, "hi"),     65: ("pos", None, "hi"),    # 64: 2€ bimétal en capsule
    66: ("pos", None, "hi"),     67: ("pos", None, "hi"),     68: ("pos", None, "lo"),
    69: ("pos", None, "hi"),     70: ("pos", None, "hi"),     71: ("pos", None, "hi"),
    72: ("pos", None, "lo"),     73: ("pos", None, "lo"),     74: ("pos", None, "hi"),    # 74: 2€ bimétal (RF) en capsule
    # ---- page 5 (75-89) ----------------------------------------------------
    75: ("pos", None, "lo"),     76: ("neg", "cent", "hi"),   77: ("pos", None, "lo"),    # 76: or monométal (eagle)=20/50ct ; 77/79/83: 2€ colorisé "bleuet" (confirmé user)
    78: ("pos", None, "hi"),     79: ("pos", None, "lo"),     80: ("pos", None, "hi"),
    81: ("pos", None, "hi"),     82: ("pos", None, "hi"),     83: ("pos", None, "lo"),
    84: ("pos", None, "hi"),     85: ("pos", None, "hi"),     86: ("pos", None, "hi"),
    87: ("pos", None, "hi"),     88: ("pos", None, "hi"),     89: ("pos", None, "hi"),
    # ---- page 6 (90-104) ---------------------------------------------------
    90: ("neg", "chart", "hi"),  91: ("pos", None, "hi"),     92: ("pos", None, "hi"),
    93: ("neg", "chart", "hi"),  94: ("neg", "chart", "hi"),  95: ("pos", None, "hi"),
    96: ("pos", None, "hi"),     97: ("pos", None, "hi"),     98: ("pos", None, "hi"),
    99: ("pos", None, "hi"),     100: ("pos", None, "hi"),    101: ("pos", None, "hi"),
    102: ("pos", None, "lo"),    103: ("pos", None, "hi"),    104: ("pos", None, "hi"),
    # ---- page 7 (105-111) --------------------------------------------------
    105: ("pos", None, "hi"),    106: ("pos", None, "hi"),    107: ("pos", None, "hi"),
    108: ("pos", None, "hi"),    109: ("pos", None, "hi"),    110: ("pos", None, "hi"),
    111: ("unk", None, "lo"),
}

idx_rows = json.load(open(OUT / "gold_index.json"))
assert len(idx_rows) == len(LBL), f"{len(idx_rows)} crops vs {len(LBL)} labels"
out = []
seed = {}
for r in idx_rows:
    label, kind, conf = LBL[r["idx"]]
    seed[r["asset_id"]] = {**r, "label": label, "kind": kind, "conf": conf,
                           "source": "seed-112", "labeled_by": "claude-visual-2026-06-13"}

# MERGE non-destructif : met à jour les 112 labels seed dans le gold existant
# par asset_id, PRÉSERVE les autres provenances (mined-v2 cents, clean-resolved-2eur).
# Idempotent → re-run sûr (ne clobbe pas le gold élargi). Cf. C7 §H11bis.
gold_path = OUT / "denom_gold.jsonl"
existing = []
if gold_path.exists():
    existing = [json.loads(l) for l in gold_path.read_text().splitlines() if l.strip()]
merged = [seed[o["asset_id"]] if o["asset_id"] in seed else o for o in existing]
seen = {o["asset_id"] for o in existing}
merged += [v for k, v in seed.items() if k not in seen]
gold_path.write_text("\n".join(json.dumps(o) for o in merged) + "\n")

from collections import Counter
print("seed labels :", len(seed), "| gold total :", len(merged))
print("label :", dict(Counter(o["label"] for o in merged)))
print("neg kind :", dict(Counter(o.get("kind") for o in merged if o["label"] == "neg")))
print("→", gold_path)
