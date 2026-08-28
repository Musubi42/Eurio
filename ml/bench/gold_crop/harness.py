"""Le banc : exécute un bras sur le jeu d'or, juge, et rend le tableau.

    python -m bench.gold_crop.harness --out state/gold_crop/v1 \
        --bras baseline_prod gold_replay measure_tilt_ellipse

Trois choses que ce module refuse de faire, et chacune a une règle derrière :

* classer un écart de moins de 5 points d'amputation — **RE-7**, 60 images ne
  départagent pas 3 images d'écart. Il l'écrit dans le tableau au lieu de
  classer ;
* déclarer un vainqueur sans les bornes — un tableau sans plancher ni plafond
  est illisible ;
* exécuter un bras candidat qui importe le juge — **RE-2**, contrôlé avant de
  lancer quoi que ce soit.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from bench.gold_crop import bras as _bras_builtin  # noqa: F401  (enregistrement)
from bench.gold_crop.datasets import Cas, JeuDOr, charger
from bench.gold_crop.geometry import Cercle
from bench.gold_crop.iface import ContexteBorne, ContexteCandidat, controler_re2, get_bras
from bench.gold_crop.judge import (
    ARC_MIN,
    D_FRAC,
    JUGE_VERSION,
    M_MARGE,
    REGION_C1,
    juger,
)

ML_DIR = Path(__file__).resolve().parents[2]
ECART_NON_SIGNIFICATIF = 5.0     # points de taux d'amputation — RE-7


def _sortie_224(raw, cand: Cercle):
    from vision.normalize_snap import CropConfig, _crop_mask_resize_float
    if raw is None:
        return None
    return _crop_mask_resize_float(raw, cand.cx, cand.cy, cand.r, "bench",
                                   config=CropConfig()).image


def executer(nom: str, jeu: JeuDOr, *, m: float = M_MARGE, arc_min: float = ARC_MIN,
             d_frac: float = D_FRAC, c2_compte: bool = False,
             avec_c2: bool = True, region: str = REGION_C1) -> dict:
    fn, borne = get_bras(nom)
    fautes = controler_re2(nom)
    if fautes:
        raise RuntimeError(f"RE-2 : le bras candidat « {nom} » est disqualifié — "
                           + " ; ".join(fautes))
    cas_json = []
    for c in jeu.cas:
        ctx = (ContexteBorne(c.largeur, c.hauteur, c.hint, c.gold, c.gold_2e_passe)
               if borne else ContexteCandidat(c.largeur, c.hauteur, c.hint))
        raw = c.raw() if (avec_c2 or nom == "measure_tilt_ellipse") else None
        cands = fn(raw, ctx)
        if not cands:
            cas_json.append({"asset_id": c.asset_id, "strate": c.strate_retenue,
                             "verdict_humain": c.verdict_humain, "absent": True})
            continue
        principal = Cercle(cands[0].cx, cands[0].cy, cands[0].r)
        mes = juger(c.gold, principal, (c.hauteur, c.largeur),
                    _sortie_224(raw, principal) if avec_c2 else None,
                    m=m, arc_min=arc_min, d_frac=d_frac, c2_compte=c2_compte,
                    region=region)
        cas_json.append({
            "asset_id": c.asset_id, "strate": c.strate,
            "strate_confirmee": c.strate_confirmee,
            "strate_retenue": c.strate_retenue,
            "verdict_humain": c.verdict_humain,
            "gold": {"cx": c.gold.cx, "cy": c.gold.cy, "a": c.gold.a,
                     "b": c.gold.b, "theta": c.gold.theta},
            "pred": {"cx": principal.cx, "cy": principal.cy, "r": principal.r},
            "candidats": [{"cx": k.cx, "cy": k.cy, "r": k.r, "source": k.source,
                           "debug": k.debug} for k in cands],
            **mes,
        })
    return {
        "arm": nom, "borne": borne, "gold_version": jeu.version,
        "gold_sha256": jeu.gold_sha256, "requete_sha256": jeu.requete_sha256,
        "judge_version": JUGE_VERSION, "m": m, "d_frac": d_frac, "arc_min": arc_min,
        "c2_compte": c2_compte, "region_c1": region,
        "execute_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_indecidables": len(jeu.indecidables), "n_non_annotes": len(jeu.non_annotes),
        "cases": cas_json,
    }


# ─── agrégation ─────────────────────────────────────────────────────────────

def _pct(xs) -> float:
    xs = list(xs)
    return 100.0 * sum(xs) / len(xs) if xs else float("nan")


def resume(run: dict, cases: list[dict] | None = None) -> dict:
    cs = [c for c in (cases if cases is not None else run["cases"]) if not c.get("absent")]
    if not cs:
        return {"n": 0}
    biou = np.array([c["boundary_iou"] for c in cs])
    return {
        "n": len(cs),
        "amputation_pct": _pct(c["ampute"] for c in cs),
        "amp_C1_pct": _pct(not c["C1_ok"] for c in cs),
        "amp_C2_pct": _pct(not c["C2_ok"] for c in cs),
        "biou_med": float(np.median(biou)),
        "biou_p10": float(np.percentile(biou, 10)),
        "iou_masque_med": float(np.median([c["mask_iou"] for c in cs])),
        "hausdorff_p90": float(np.percentile([c["hausdorff_frac"] for c in cs], 90)),
    }


def tableau(runs: list[dict]) -> str:
    """Le tableau de `PROTOCOLE-BANC.md` : amputation en première colonne."""
    lignes = ["| bras | amput. % | amp C1 | amp C2 | BIoU méd. | BIoU p10 | "
              "IoU masque méd. | Haus. p90 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    ordre = ([r for r in runs if r["arm"] == "human_2nd_pass"]
             + [r for r in runs if r["arm"] == "gold_replay"]
             + [r for r in runs if not r["borne"]])
    for r in ordre:
        s = resume(r)
        if not s["n"]:
            lignes.append(f"| `{r['arm']}` | — | | | | | | |")
            continue
        etiq = f"`{r['arm']}`" + (" *(borne)*" if r["borne"] else "")
        lignes.append(
            f"| {etiq} | **{s['amputation_pct']:.1f}** | {s['amp_C1_pct']:.1f} | "
            f"{s['amp_C2_pct']:.1f} | {s['biou_med']:.3f} | **{s['biou_p10']:.3f}** | "
            f"{s['iou_masque_med']:.3f} | {s['hausdorff_p90']:.3f} |")
    return "\n".join(lignes)


def tableau_par_strate(runs: list[dict]) -> str:
    strates = sorted({c["strate_retenue"] for r in runs for c in r["cases"]
                      if not c.get("absent")})
    lignes = ["| bras | " + " | ".join(strates) + " |",
              "|---|" + "|".join(["---:"] * len(strates)) + "|"]
    for r in runs:
        vals = []
        for s in strates:
            cs = [c for c in r["cases"] if c.get("strate_retenue") == s]
            res = resume(r, cs)
            vals.append("—" if not res["n"] else f"{res['amputation_pct']:.0f} %")
        lignes.append(f"| `{r['arm']}` | " + " | ".join(vals) + " |")
    return "\n".join(lignes)


def departage(a: dict, b: dict) -> str:
    """RE-7 — 60 images ne départagent pas moins de ~5 points d'amputation."""
    da = resume(a)["amputation_pct"] - resume(b)["amputation_pct"]
    if abs(da) < ECART_NON_SIGNIFICATIF:
        return (f"{a['arm']} et {b['arm']} : écart {da:+.1f} pt — "
                f"**pas un départage** (RE-7, < {ECART_NON_SIGNIFICATIF:.0f} pt sur 60 images)")
    gagnant, perdant = (b, a) if da > 0 else (a, b)
    return f"{gagnant['arm']} devant {perdant['arm']} de {abs(da):.1f} pt"


def re4(run: dict) -> dict:
    """⛔ **Le point d'arrêt.** Le juge sépare-t-il les acceptés des rejetés ?

    Si `amputation_rate` ne les sépare pas, le juge est faux et le banc s'arrête
    là — quelle que soit sa cohérence géométrique. Test de référence :
    `quality_score` y échoue à 0,0008 près.
    """
    from scipy.stats import fisher_exact, mannwhitneyu

    cs = [c for c in run["cases"] if not c.get("absent")]
    acc = [c for c in cs if c["verdict_humain"] == "accept"]
    rej = [c for c in cs if c["verdict_humain"] == "reject"]
    if not acc or not rej:
        return {"verdict": "impossible", "raison": "un des deux groupes est vide"}
    table = [[sum(c["ampute"] for c in rej), len(rej) - sum(c["ampute"] for c in rej)],
             [sum(c["ampute"] for c in acc), len(acc) - sum(c["ampute"] for c in acc)]]
    _, p_fisher = fisher_exact(table)
    out = {
        "n_accept": len(acc), "n_reject": len(rej),
        "amputation_pct_accept": _pct(c["ampute"] for c in acc),
        "amputation_pct_reject": _pct(c["ampute"] for c in rej),
        "fisher_p": float(p_fisher),
        "table_2x2": {"rejete": {"ampute": table[0][0], "sain": table[0][1]},
                      "accepte": {"ampute": table[1][0], "sain": table[1][1]}},
    }
    for grandeur in ("boundary_iou", "C1_marge_min_frac", "mask_iou"):
        va = [c[grandeur] for c in acc]
        vr = [c[grandeur] for c in rej]
        u = mannwhitneyu(va, vr, alternative="two-sided")
        out[grandeur] = {"med_accept": float(np.median(va)),
                         "med_reject": float(np.median(vr)),
                         "mannwhitney_p": float(u.pvalue)}
    out["verdict"] = "sépare" if p_fisher < 0.05 else "NE SÉPARE PAS"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ML_DIR / "state" / "gold_crop" / "v1"))
    ap.add_argument("--bras", nargs="+",
                    default=["human_2nd_pass", "gold_replay", "baseline_prod",
                             "measure_tilt_ellipse"])
    ap.add_argument("--m", type=float, default=M_MARGE)
    ap.add_argument("--d-frac", type=float, default=D_FRAC)
    ap.add_argument("--arc-min", type=float, default=ARC_MIN)
    ap.add_argument("--c2-compte", action="store_true",
                    help="faire entrer C2 dans le taux d'amputation (cf. D8)")
    ap.add_argument("--sans-c2", action="store_true")
    ap.add_argument("--region-c1", default=REGION_C1,
                    choices=("retenu", "cadre", "disque"),
                    help="sur quelle région C1 mesure la marge (D9)")
    a = ap.parse_args(argv)

    racine = Path(a.out)
    jeu = charger(racine)
    print(f"jeu d'or {jeu.version} · {len(jeu.cas)} cas annotés "
          f"· {len(jeu.indecidables)} indécidables · {len(jeu.non_annotes)} non annotés")
    print(f"gold sha256 {jeu.gold_sha256[:12]}… · requête {jeu.requete_sha256[:12]}…")

    runs = []
    for nom in a.bras:
        r = executer(nom, jeu, m=a.m, arc_min=a.arc_min, d_frac=a.d_frac,
                     c2_compte=a.c2_compte, avec_c2=not a.sans_c2,
                     region=a.region_c1)
        (racine / f"run_{nom}.json").write_text(json.dumps(r, indent=1))
        runs.append(r)
        print(f"  {nom:24s} → run_{nom}.json")

    print("\n" + tableau(runs))
    print("\nPar strate (taux d'amputation) :\n" + tableau_par_strate(runs))

    base = next((r for r in runs if r["arm"] == "baseline_prod"), None)
    if base:
        print("\n⛔ RE-4 — le juge sépare-t-il les acceptés des rejetés ?")
        v = re4(base)
        print(json.dumps(v, indent=1, ensure_ascii=False))
        if v.get("verdict") == "NE SÉPARE PAS":
            print("\n🔴 Le juge est FAUX. Le banc s'arrête là (RE-4).")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
