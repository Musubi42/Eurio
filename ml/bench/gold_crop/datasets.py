"""Le jeu d'or vu par le banc : manifeste + `gold.json` → une liste de cas.

`gold.json` est un artefact de DONNÉES (RE-5) : il vit dans
`ml/state/gold_crop/<version>/`, gitignoré, et sur MinIO. Le dépôt n'en porte
que le `sha256` et la requête.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bench.gold_crop.geometry import Ellipse


@dataclass
class Cas:
    asset_id: str
    strate: str
    strate_confirmee: str | None
    verdict_humain: str
    fichier: Path
    largeur: int
    hauteur: int
    hint: dict
    gold: Ellipse
    gold_2e_passe: Ellipse | None = None

    def raw(self) -> np.ndarray | None:
        import cv2
        return cv2.imread(str(self.fichier), cv2.IMREAD_COLOR)

    @property
    def strate_retenue(self) -> str:
        """La strate CONFIRMÉE prime. Celle du tirage vient de proxys textuels ;
        seule la confirmation du PO la rend honnête (cf. `JEU-D-OR.md`)."""
        return self.strate_confirmee or self.strate


def _ellipse(d: dict | None) -> Ellipse | None:
    if not d:
        return None
    return Ellipse.depuis_degres(d["cx"], d["cy"], d["a"], d["b"], d["theta"])


@dataclass
class JeuDOr:
    version: str
    racine: Path
    cas: list[Cas]
    gold_sha256: str
    requete_sha256: str
    indecidables: list[str]
    non_annotes: list[str]

    def par_strate(self) -> dict[str, list[Cas]]:
        out: dict[str, list[Cas]] = {}
        for c in self.cas:
            out.setdefault(c.strate_retenue, []).append(c)
        return out


def charger(racine: str | Path) -> JeuDOr:
    """Les cas annotés et annotables. Un « indécidable » **sort du jeu**.

    Il n'est pas remplacé automatiquement : la réserve existe pour que le PO
    en annote un de plus, pas pour qu'un script substitue une image dans son
    dos. Un jeu d'or qui se répare tout seul n'est plus un jeu d'or.
    """
    racine = Path(racine)
    manifeste = json.loads((racine / "manifest.json").read_text())
    gold_p = racine / "gold.json"
    if not gold_p.exists():
        raise FileNotFoundError(
            f"{gold_p} absent — la séance d'annotation n'a pas eu lieu. "
            f"`python -m bench.gold_crop.annotate.serve --out {racine}`")
    brut = gold_p.read_bytes()
    annot = json.loads(brut)["annotations"]
    p2 = racine / "gold.pass2.json"
    annot2 = json.loads(p2.read_text())["annotations"] if p2.exists() else {}

    cas, indecidables, non_annotes = [], [], []
    for img in manifeste["images"]:
        a = annot.get(img["asset_id"])
        if a is None or not a.get("ellipse"):
            if img["role"] == "tirage":
                non_annotes.append(img["asset_id"])
            continue
        if a.get("indecidable"):
            indecidables.append(img["asset_id"])
            continue
        cas.append(Cas(
            asset_id=img["asset_id"], strate=img["strate"],
            strate_confirmee=a.get("strate_confirmee"),
            verdict_humain=img["verdict"],
            fichier=racine / img["fichier"],
            largeur=int(img["width"]), hauteur=int(img["height"]),
            hint=img["hint"], gold=_ellipse(a["ellipse"]),
            gold_2e_passe=_ellipse((annot2.get(img["asset_id"]) or {}).get("ellipse")),
        ))
    return JeuDOr(
        version=manifeste.get("version", "v1"), racine=racine, cas=cas,
        gold_sha256=hashlib.sha256(brut).hexdigest(),
        requete_sha256=manifeste.get("requete_sha256", ""),
        indecidables=indecidables, non_annotes=non_annotes)
