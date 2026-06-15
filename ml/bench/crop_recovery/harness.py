"""Harness : exécute une stratégie sur les jeux, crope+score (probe GELÉE) chaque
candidat, calcule les métriques, écrit le JSON (schéma BENCHMARK §4). Les stratégies ne
touchent jamais ce fichier — elles n'écrivent que `recrop()`.
"""

from __future__ import annotations

import json

import numpy as np

from .common import STATE_DIR, TAU, crop_candidate, iou_circles, load_raw, score_crops
from .iface import Candidate, get_strategy


def _run_case(raw, hint, strat, gold):
    cands: list[Candidate] = [Candidate(hint["cx"], hint["cy"], hint["r_final"], "baseline")]
    try:
        cands += [c for c in strat(raw, hint) if c.source != "baseline"]
    except Exception as exc:  # une stratégie qui casse sur un cas ne tue pas le run
        cands[0].debug["strategy_error"] = str(exc)
    imgs, keep = [], []
    for i, c in enumerate(cands):
        im = crop_candidate(raw, c.cx, c.cy, c.r)
        if im is not None:
            imgs.append(im); keep.append(i)
    scores = score_crops(imgs) if imgs else []
    rec = []
    for i, s in zip(keep, scores):
        c = cands[i]
        d = {"cx": round(c.cx, 1), "cy": round(c.cy, 1), "r": round(c.r, 1),
             "source": c.source, "score": round(float(s), 4)}
        if gold is not None:
            d["iou_gold"] = round(iou_circles((c.cx, c.cy, c.r), tuple(gold)), 4)
        rec.append(d)
    if not rec:
        return None
    chosen = max(range(len(rec)), key=lambda i: rec[i]["score"])
    base = next((r["score"] for r in rec if r["source"] == "baseline"), None)
    return {"candidates": rec, "chosen_idx": chosen,
            "chosen_score": rec[chosen]["score"], "baseline_score": base,
            "passed": rec[chosen]["score"] >= TAU}


def run(strategy_name: str, datasets: list[str], limit: int | None = None) -> dict:
    strat = get_strategy(strategy_name)
    out_cases: list[dict] = []
    for ds in datasets:
        path = STATE_DIR / f"{ds}.json"
        if not path.exists():
            print(f"  (jeu {ds} absent — construire via bench.crop_recovery.datasets)")
            continue
        cases = json.loads(path.read_text())["cases"]
        if limit:
            cases = cases[:limit]
        print(f"  {ds}: {len(cases)} cas…")
        for k, e in enumerate(cases):
            raw = load_raw(e["raw_key"])
            if raw is None:
                continue
            r = _run_case(raw, e["hint"], strat, e.get("gold_circle"))
            if r is None:
                continue
            out_cases.append({
                "case_id": e["case_id"], "dataset": ds,
                "raw_key": e["raw_key"], "target_eurio_id": e.get("target_eurio_id"),
                "emu_globe": e.get("emu_globe", False),
                "gold_circle": e.get("gold_circle"),
                "is_fragment": e.get("is_fragment", False),
                **r,
            })
            if (k + 1) % 50 == 0:
                print(f"    …{k + 1}/{len(cases)}")
    result = {"strategy": strategy_name, "tau": TAU, "cases": out_cases}
    out_path = STATE_DIR / f"run_{strategy_name.replace(':', '_')}.json"
    out_path.write_text(json.dumps(result))
    print(f"\n→ {out_path}")
    metrics(result)
    return result


def metrics(result: dict) -> dict:
    """Tableau D1/D2/D3 + gardes (cf. BENCHMARK §6). Pur sur le JSON (re-calculable)."""
    cases = result["cases"]
    by = lambda ds: [c for c in cases if c["dataset"] == ds]
    tau = result["tau"]
    out = {}
    print(f"\n{'='*60}\nMÉTRIQUES — stratégie {result['strategy']} (τ={tau})\n{'='*60}")

    d1 = by("D1")
    if d1:
        iou = np.array([c["candidates"][c["chosen_idx"]].get("iou_gold", 0.0) for c in d1])
        base_iou = []
        for c in d1:
            b = next((cc for cc in c["candidates"] if cc["source"] == "baseline"), None)
            base_iou.append(b.get("iou_gold", 0.0) if b else 0.0)
        out["D1"] = {"n": len(d1), "iou_median": float(np.median(iou)),
                     "iou_ge_0.8": float((iou >= 0.8).mean()),
                     "baseline_iou_median": float(np.median(base_iou))}
        print(f"D1 gold géométrie  n={len(d1)}  IoU médian={np.median(iou):.3f} "
              f"(baseline {np.median(base_iou):.3f})  %IoU≥0.8={100*(iou>=0.8).mean():.0f}%  "
              f"[cible ≥0.80]")

    for ds, label, cible in [("D2", "récupération", "≥70% EMU/globe")]:
        d = by(ds)
        if not d:
            continue
        eg = [c for c in d if c["emu_globe"]]
        au = [c for c in d if not c["emu_globe"]]
        def rec(s): return 100 * np.mean([c["passed"] for c in s]) if s else 0.0
        def basepass(s): return 100 * np.mean([(c["baseline_score"] or 0) >= tau for c in s]) if s else 0.0
        out["D2"] = {"n": len(d), "n_emu_globe": len(eg), "n_autres": len(au),
                     "recovery_emu_globe": rec(eg), "recovery_autres": rec(au),
                     "baseline_emu_globe": basepass(eg)}
        au_txt = f"{rec(au):.0f}% (n={len(au)})" if au else "n/a (n=0)"
        print(f"D2 {label}    n={len(d)}  récup EMU/globe={rec(eg):.0f}% "
              f"(baseline {basepass(eg):.0f}%, n={len(eg)})  récup autres={au_txt}  [cible {cible}]")

    d3a = by("D3a")
    if d3a:
        ret = 100 * np.mean([c["passed"] for c in d3a])
        base_ret = 100 * np.mean([(c["baseline_score"] or 0) >= tau for c in d3a])
        out["D3a"] = {"n": len(d3a), "retention": ret, "baseline_retention": base_ret}
        print(f"D3a rétention succ n={len(d3a)}  rétention={ret:.0f}% "
              f"(baseline {base_ret:.0f}%)  [garde ≥98%]")
    d3b = by("D3b")
    if d3b:
        fa = 100 * np.mean([c["passed"] for c in d3b])
        out["D3b"] = {"n": len(d3b), "false_accept": fa}
        print(f"D3b fragments      n={len(d3b)}  faux-accept={fa:.0f}%  [garde ≤2%]")
    return out
