"""Les RUNS du banc du crop, servis à la planche comparative (`/gold-crop/planche`).

Ce module lit `state/gold_crop/<version>/run_*.json` — les fichiers que
`bench.gold_crop.harness` écrit **sur la machine qui a exécuté le banc**. Ils
n'existent nulle part ailleurs : ni en base, ni sur MinIO, ni sur le VPS.

POURQUOI IL N'EST PAS DANS `crop_gold_routes.py`
------------------------------------------------
`crop_gold_routes` est monté sur l'app LEAN (`server_serve.py`) : c'est lui qui
sert l'or du canonique, et la séance d'annotation en dépend depuis un
téléphone. Y greffer ces deux routes les ferait apparaître dans l'OpenAPI du
VPS, où elles répondraient 404 sur chaque appel — une capacité annoncée qui
n'existe pas, c'est-à-dire exactement la panne muette que ce dépôt paie le plus
cher. Ce module est donc monté **uniquement** par `serving/server.py` (l'app
FULL, `:8042`), et la règle de synchronisation FULL ↔ LEAN est enfreinte ici
**à dessein** : la dépendance n'est pas `cv2`, c'est le disque local.

Côté front, la page qui les consomme est marquée `meta: { heavy: true }` : elle
se grise toute seule en hébergé, sans essai/erreur HTTP.

SCOPE
-----
Lecture pure, scope sémantique `lab:read` — le même que `GET /crop-gold/{v}`.
Il n'est **exigé que si l'auth est armée** (`EURIO_API_AUTH_REQUIRED`) : sur
`:8042` l'auth est un no-op par convention (`serving/auth.require_token`) et
aucun appelant du front n'envoie de jeton au ML local. Exiger un PAT ici
rendrait la page inutilisable sur la machine même où les fichiers existent.

Module stdlib AU NIVEAU MODULE : ni `cv2`, ni `numpy`, ni `bench.*` à l'import.
Le résumé est recalculé ici — `bench.gold_crop.harness.resume` tire `numpy`
puis, par la chaîne des bras, `vision.*`. `tests/test_crop_gold_runs_routes.py`
compare chiffre à chiffre les deux implémentations.

**RE-4 fait exception, et c'est délibéré** : c'est le point d'arrêt du banc, le
seul chiffre pour lequel une seconde implémentation serait une faute. Il est
importé PARESSEUSEMENT depuis le harness (même patron que
`crop_recovery_routes.run_detail`), dans le handler, avec repli explicite si
l'import échoue — la planche reste montrable sans lui, elle le dit.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

from serving import auth as api_auth

router = APIRouter(prefix="/crop-gold", tags=["crop-gold-runs"])

_ML_DIR = Path(__file__).resolve().parent.parent
_DIR = _ML_DIR / "state" / "gold_crop"

#: Une version d'or, un asset : des identifiants, jamais des chemins. Tout ce
#: qui n'est pas cette classe est refusé AVANT toute jointure de chemin. Le
#: garde négatif en tête n'est pas décoratif : `.` et `..` sont composés de
#: caractères tous autorisés, et `..` seul suffirait à remonter d'un cran.
_JETON = re.compile(r"^(?!\.+$)[A-Za-z0-9_.-]{1,64}$")


def exiger_lecture_lab(
    request: Request,
    eurio_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """`lab:read` — exigé seulement là où l'auth est armée (cf. en-tête)."""
    if not api_auth.auth_required():
        return
    from serving.auth_principal import require_principal

    principal = require_principal(request, eurio_session, authorization)
    if "lab:read" not in principal.scopes:
        raise HTTPException(status_code=403, detail="missing scope: lab:read")


def _racine(gold_version: str) -> Path:
    if not _JETON.match(gold_version):
        raise HTTPException(status_code=422, detail=f"version d'or invalide : {gold_version!r}")
    return _DIR / gold_version


# ─── Le résumé, en stdlib ────────────────────────────────────────────────────


def _percentile(valeurs: list[float], q: float) -> float:
    """Interpolation linéaire — la convention de `numpy.percentile` par défaut.

    Réimplémentée plutôt qu'importée : `numpy` n'a rien à faire dans un module
    de service qui lit du JSON, et la médiane du banc doit rester le MÊME
    nombre que celui du tableau de `harness`. C'est le test qui le tient.
    """
    xs = sorted(valeurs)
    if not xs:
        return float("nan")
    pos = (len(xs) - 1) * q / 100.0
    bas = int(pos)
    haut = min(bas + 1, len(xs) - 1)
    return xs[bas] + (xs[haut] - xs[bas]) * (pos - bas)


def _pct(drapeaux: list[bool]) -> float:
    return 100.0 * sum(1 for d in drapeaux if d) / len(drapeaux) if drapeaux else float("nan")


def resume(cas: list[dict[str, Any]]) -> dict[str, Any]:
    """Miroir stdlib de `bench.gold_crop.harness.resume`.

    Un bras qui n'a rien rendu (`absent`) ne compte pas : `human_2nd_pass` sans
    seconde passe rend `{"n": 0}`, et la planche doit l'afficher comme une
    borne non mesurée — pas comme un bras à 0 % d'amputation.
    """
    cs = [c for c in cas if not c.get("absent")]
    if not cs:
        return {"n": 0}
    biou = [float(c["boundary_iou"]) for c in cs]
    return {
        "n": len(cs),
        "amputation_pct": _pct([bool(c["ampute"]) for c in cs]),
        "amp_C1_pct": _pct([not c["C1_ok"] for c in cs]),
        "amp_C2_pct": _pct([not c["C2_ok"] for c in cs]),
        "marge_promise_ko_pct": _pct([not c.get("marge_promise_ok", True) for c in cs]),
        "biou_med": _percentile(biou, 50),
        "biou_p10": _percentile(biou, 10),
        "iou_masque_med": _percentile([float(c["mask_iou"]) for c in cs], 50),
        "hausdorff_p90": _percentile([float(c["hausdorff_frac"]) for c in cs], 90),
    }


def _dimensions(racine: Path) -> dict[str, dict[str, Any]]:
    """`asset_id → {largeur, hauteur}`, lu du manifeste du tirage.

    Le run ne porte PAS les dimensions du raw, et sans elles la planche ne peut
    pas caler son `viewBox` : une ellipse en pixels natifs dessinée sur un
    `viewBox` supposé carré est fausse sur tout raw qui ne l'est pas — fausse
    sans en avoir l'air, ce qui est le pire cas pour une planche de contrôle.
    """
    fichier = racine / "manifest.json"
    if not fichier.exists():
        return {}
    try:
        manifeste = json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        im["asset_id"]: {"largeur": im.get("width"), "hauteur": im.get("height")}
        for im in manifeste.get("images", [])
        if im.get("asset_id")
    }


def _re4(cas: list[dict[str, Any]]) -> dict[str, Any]:
    """⛔ Le point d'arrêt — le juge sépare-t-il les acceptés des rejetés ?

    Importé du harness, jamais réimplémenté : deux calculs d'un Fisher exact qui
    divergeraient sur la troisième décimale, c'est un banc dont on ne sait plus
    lequel des deux dit la vérité. Une borne n'en a pas : rejouer l'or contre
    lui-même ne mesure pas le pouvoir prédictif du juge.
    """
    try:
        from bench.gold_crop.harness import re4
    except Exception as exc:  # noqa: BLE001 — numpy/scipy absents : on le DIT
        return {"verdict": "indisponible",
                "raison": f"le harness n'est pas importable ici : {exc}"}
    return re4({"cases": cas})


@router.get("/{gold_version}/runs", dependencies=[Depends(exiger_lecture_lab)])
def get_runs(gold_version: str) -> dict[str, Any]:
    """Tous les bras exécutés sur cette version d'or, résumés et détaillés.

    404 si aucun run : le banc n'a pas tourné ICI. Ce n'est pas une panne, et
    la planche le dit avec la commande à lancer.
    """
    racine = _racine(gold_version)
    fichiers = sorted(racine.glob("run_*.json"))
    if not fichiers:
        raise HTTPException(
            status_code=404,
            detail=(f"aucun run pour {gold_version} — lance "
                    f"`cd ml && python -m bench.gold_crop.harness "
                    f"--out state/gold_crop/{gold_version}`"),
        )
    dims = _dimensions(racine)
    runs = []
    for fichier in fichiers:
        try:
            brut = json.loads(fichier.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # Un run illisible ne fait pas tomber les autres : la planche vaut
            # surtout par la COMPARAISON, elle doit rester montrable amputée.
            runs.append({"bras": fichier.stem.removeprefix("run_"), "erreur": str(exc),
                         "cas": [], "resume": {"n": 0}})
            continue
        cas = []
        for c in brut.get("cases", []):
            aid = c.get("asset_id", "")
            cas.append({**c, **dims.get(aid, {"largeur": None, "hauteur": None}),
                        "raw_url": f"/crop-gold/{gold_version}/raws/{aid}"})
        runs.append({
            "bras": brut.get("arm", fichier.stem.removeprefix("run_")),
            "re4": _re4(cas) if not brut.get("borne") else None,
            "borne": bool(brut.get("borne")),
            "juge_version": brut.get("judge_version"),
            "execute_le": brut.get("execute_le"),
            "gold_sha256": brut.get("gold_sha256"),
            "requete_sha256": brut.get("requete_sha256"),
            "n_indecidables": brut.get("n_indecidables"),
            "n_non_annotes": brut.get("n_non_annotes"),
            "params": {
                "m": brut.get("m"),
                "d_frac": brut.get("d_frac"),
                "arc_min": brut.get("arc_min"),
                "region": brut.get("region_c1"),
                "c2_compte": bool(brut.get("c2_compte")),
            },
            "resume": resume(cas),
            "cas": cas,
        })
    return {"gold_version": gold_version, "n": len(runs), "runs": runs}


@router.get("/{gold_version}/raws/{asset_id}", dependencies=[Depends(exiger_lecture_lab)])
def get_raw(gold_version: str, asset_id: str) -> FileResponse:
    """Le raw local du tirage — la planche n'a alors besoin ni de MinIO ni de PAT.

    Les raws sont déjà sur la machine du banc (`sample` les y a posés) : les
    présigner depuis MinIO ferait dépendre une page LOCALE d'un service DISTANT
    pour une image qui est à un chemin de là.
    """
    racine = _racine(gold_version)
    if not _JETON.match(asset_id):
        raise HTTPException(status_code=422, detail=f"asset_id invalide : {asset_id!r}")
    chemin = racine / "raws" / f"{asset_id}.jpg"
    if not chemin.exists():
        raise HTTPException(status_code=404, detail=f"raw absent : {asset_id}")
    return FileResponse(chemin, media_type="image/jpeg")
