"""Les bras du banc : deux bornes, deux candidats de référence.

⚠️ **Les bornes ne sont pas des candidats.** `gold_replay` et `human_2nd_pass`
lisent l'or — c'est leur raison d'être : sans elles, on attribue à une méthode
un défaut du format ou du bruit de la main. Elles sont enregistrées
`borne=True`, ce qui les exclut du classement et leur donne accès au
`ContexteBorne`.

Ce module n'importe pas le juge et ne lit aucun `gold.json` : `controler_re2`
le vérifie syntaxiquement pour les candidats qu'il déclare.
"""

from __future__ import annotations

import numpy as np

from bench.gold_crop.iface import Candidat, ContexteBorne, ContexteCandidat, enregistrer


@enregistrer("baseline_prod")
def baseline_prod(raw: np.ndarray | None, ctx: ContexteCandidat) -> list[Candidat]:
    """Le `bbox_json` actuel, tel qu'en base. **Le seul chiffre qui compte** :
    une méthode qui ne le bat pas ne se déploie pas."""
    h = ctx.hint
    return [Candidat(h["cx"], h["cy"], h["r"], "baseline_prod")]


@enregistrer("measure_tilt_ellipse")
def measure_tilt_ellipse(raw: np.ndarray | None, ctx: ContexteCandidat) -> list[Candidat]:
    """Le naïf gratuit : `fitEllipseAMS` déjà écrit dans `crop_detectors.py`.

    Le format n'accepte qu'un cercle (ADR-017) : on prend `r = demi-grand axe`,
    le plus petit cercle qui contient l'ellipse ajustée. Prendre le demi-petit
    axe amputerait par construction.
    """
    from vision.crop_detectors import measure_tilt

    if raw is None:
        return []
    m = measure_tilt(raw, ctx.hint)
    if not m.get("ok"):
        return [Candidat(ctx.hint["cx"], ctx.hint["cy"], ctx.hint["r"],
                         "measure_tilt_ellipse:repli", {"reason": m.get("reason")})]
    return [Candidat(m["cx"], m["cy"], m["major"], "measure_tilt_ellipse",
                     {"axis_ratio": m["axis_ratio"], "trustworthy": m["trustworthy"]})]


@enregistrer("gold_replay", borne=True)
def gold_replay(raw: np.ndarray | None, ctx: ContexteBorne) -> list[Candidat]:
    """**Le plafond mécanique** : l'or lui-même passé dans le format.

    `r = a`, le plus petit cercle contenant `E_gold`. Ce que ce bras perd, aucune
    méthode ne peut le récupérer — c'est le format qui le perd. Sans cette
    borne, on impute à la méthode un défaut d'ADR-017.
    """
    if ctx.gold is None:
        return []
    g = ctx.gold
    return [Candidat(g.cx, g.cy, g.a, "gold_replay", {"b_sur_a": g.b / g.a})]


@enregistrer("human_2nd_pass", borne=True)
def human_2nd_pass(raw: np.ndarray | None, ctx: ContexteBorne) -> list[Candidat]:
    """**Le plancher de bruit** : la 2ᵉ annotation, à ≥ 24 h d'écart.

    Aucune méthode ne peut être créditée au-dessus de la reproductibilité de la
    main qui a fabriqué l'or.
    """
    if ctx.gold_2e_passe is None:
        return []
    g = ctx.gold_2e_passe
    return [Candidat(g.cx, g.cy, g.a, "human_2nd_pass", {"b_sur_a": g.b / g.a})]
