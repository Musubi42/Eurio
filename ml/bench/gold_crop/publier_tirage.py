"""Publie le TIRAGE local (`manifest.json`) dans le **canonique**.

Le pendant de `fetch` : celui-ci descend l'or, celui-là monte ce qu'il y a à
annoter. Depuis D12, la séance d'annotation se tient depuis le front hébergé —
donc le canonique doit porter le tirage, sinon il n'y a rien à afficher.

    cd ml && python -m bench.gold_crop.publier_tirage --out state/gold_crop/v1

Ce que la conversion fait, et pourquoi :

* `prefill.ok = false` → `prefill: null`, **mais `prefill_reason` est gardée**.
  Une proposition absente et une proposition douteuse ne sont pas la même
  chose, et la raison (`too_circular:0.983`, `no_contour`…) dit sur quelles
  strates `measure_tilt` propose mal. La perdre effacerait l'information ;
* `major/minor/angle` → `a/b/theta_deg`, le vocabulaire de 0019 et 0020. Le
  serveur remet `a >= b` de toute façon (le piège `cv2.fitEllipse`), mais on
  n'envoie pas du désordre en comptant sur lui pour le ranger ;
* **`verdict` n'est pas envoyé.** Le manifeste le porte ; le tirage servi à
  l'annotateur ne doit pas. Un annotateur qui voit le verdict humain le
  confirme au lieu de tracer ce qu'il voit, et RE-4 ne mesure plus rien.

La route est **idempotente** par `(gold_version, asset_id)` : republier est
sans danger tant que la version n'est pas gelée. Une fois gelée, c'est un 409 —
et c'est voulu, le tirage fixe la population mesurée.

Codes de sortie : 0 ok · 1 réseau/auth/manifeste · 2 refus du canonique (409 :
version gelée, ou requête d'échantillonnage divergente).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from bench.gold_crop.fetch import ErreurCanonique, _diagnostic_http

ML_DIR = Path(__file__).resolve().parents[2]

#: Même convention que `fetch` / `geler`. ⚠️ INDISPENSABLE :
#: `eurio-api.musubi.dev` est derrière Cloudflare, qui refuse l'UA par défaut
#: d'urllib (`Python-urllib/3.x`) avec un 403 « error code: 1010 » — une page
#: HTML, pas du JSON. La panne ne se voit QUE dans l'outil.
USER_AGENT = "eurio-gold-publier-tirage/1.0"


class RefusCanonique(Exception):
    """409 : le serveur refuse (gel, ou requête divergente). Sa raison est
    reprise VERBATIM — la reformuler perdrait ce qui dit quoi faire."""


def _detail(brut: str) -> str:
    """Le `detail` d'une HTTPException FastAPI, ou le corps tel quel."""
    try:
        return str(json.loads(brut).get("detail", brut))
    except ValueError:
        return brut.strip()


def entree_tirage(image: dict) -> dict:
    """Une image du manifeste → une image du payload de la route.

    `verdict`, `tilt_deg`, `bbox_json`, `fichier`… ne montent pas : ils sont
    soit joignables depuis `image_assets`, soit du contexte de la machine du ML.
    """
    prefill = image.get("prefill") or {}
    ellipse = None
    if prefill.get("ok"):
        coords = (prefill.get("cx"), prefill.get("cy"), prefill.get("major"),
                  prefill.get("minor"), prefill.get("angle"))
        if None not in coords:
            ellipse = {"cx": prefill["cx"], "cy": prefill["cy"],
                       "a": prefill["major"], "b": prefill["minor"],
                       "theta_deg": prefill["angle"]}
    hint = image.get("hint") or {}
    return {"asset_id": image["asset_id"],
            "role": image.get("role", "tirage"),
            "rn": image.get("rn"),
            "strate_tiree": image.get("strate"),
            "width": image.get("width"),
            "height": image.get("height"),
            "hint": {"cx": hint.get("cx"), "cy": hint.get("cy"),
                     "r": hint.get("r")},
            "prefill": ellipse,
            "prefill_reason": prefill.get("reason")}


def publier(version: str, payload: dict, *, base_url: str, token: str,
            timeout: float = 60.0) -> dict:
    """`PUT /crop-gold/<version>/tirage`."""
    data = json.dumps(payload).encode()
    req = urlrequest.Request(
        f"{base_url.rstrip('/')}/crop-gold/{version}/tirage",
        data=data, method="PUT",
        headers={"Authorization": f"Bearer {token}",
                 "User-Agent": USER_AGENT,
                 "Content-Type": "application/json"})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as r:
            corps = r.read()
            return json.loads(corps) if corps else {}
    except urlerror.HTTPError as exc:
        brut = exc.read().decode(errors="replace")
        if exc.code == 409:
            raise RefusCanonique(_detail(brut)) from exc
        raise ErreurCanonique(_diagnostic_http(exc.code, brut)) from exc
    except Exception as exc:                                  # noqa: BLE001
        raise ErreurCanonique(
            f"canonique injoignable ({base_url}) : {exc}") from exc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ML_DIR / "state" / "gold_crop" / "v1"),
                    help="dossier du jeu d'or (celui de `sample`)")
    ap.add_argument("--version", default=None,
                    help="version d'or ; défaut : celle du manifeste, sinon v1")
    ap.add_argument("--api-url", default=os.environ.get("EURIO_API_URL"))
    ap.add_argument("--api-token", default=os.environ.get("EURIO_API_TOKEN"))
    a = ap.parse_args(argv)

    if not a.api_url or not a.api_token:
        print("🔴 EURIO_API_URL / EURIO_API_TOKEN absents — le tirage s'écrit "
              "dans le canonique, il n'a aucun sens en local. Charge le "
              "devShell (`direnv reload`, ou `eval \"$(direnv export zsh)\"`).")
        return 1

    manifeste = Path(a.out).resolve() / "manifest.json"
    if not manifeste.exists():
        print(f"🔴 pas de manifest.json dans {manifeste.parent} — le tirage "
              f"vient de `sample` : `python -m bench.gold_crop.sample --out "
              f"{a.out}`.")
        return 1
    try:
        m = json.loads(manifeste.read_text())
    except ValueError as exc:
        print(f"🔴 manifeste illisible ({manifeste}) : {exc}")
        return 1

    version = a.version or m.get("version") or "v1"
    images = [entree_tirage(i) for i in (m.get("images") or [])]
    if not images:
        print(f"🔴 manifeste vide : aucune image à publier ({manifeste}).")
        return 1

    try:
        rep = publier(version,
                      {"requete_sha256": m.get("requete_sha256"),
                       "images": images},
                      base_url=a.api_url, token=a.api_token)
    except RefusCanonique as exc:
        print(f"🔴 409 — le canonique refuse, verbatim : {exc}")
        print("   Un tirage ne se republie ni sur un or GELÉ, ni sous une "
              "version née d'une AUTRE requête d'échantillonnage : dans les "
              "deux cas ça changerait la population mesurée (RE-5).")
        return 2
    except ErreurCanonique as exc:
        print(f"🔴 {exc}")
        return 1

    ignorees = rep.get("ignorees") or []
    par_couple: dict[tuple[str, str], int] = {}
    for i in images:
        cle = (i.get("role") or "?", i.get("strate_tiree") or "(sans strate)")
        par_couple[cle] = par_couple.get(cle, 0) + 1

    print(f"tirage {version} → {a.api_url.rstrip('/')}/crop-gold/{version}/tirage")
    print(f"publiées : {rep.get('n')} / {len(images)}")
    for (role, strate), n in sorted(par_couple.items()):
        print(f"  {role:8s} {strate:12s} {n}")
    if ignorees:
        print(f"⚠️  {len(ignorees)} image(s) IGNORÉE(S) — `asset_id` absent "
              f"d'`image_assets` sur le canonique (purge, ou réplique en "
              f"retard) :")
        for asset in ignorees:
            print(f"   {asset}")
        print("   Le reste EST publié : un asset manquant ne fait pas tomber "
              "le tirage. Mais la séance aura moins d'images que prévu.")
    print("Le verdict humain n'a pas été envoyé — et c'est délibéré (RE-4).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
