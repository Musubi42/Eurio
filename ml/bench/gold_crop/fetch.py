"""Rapatrie l'or du **canonique** vers le `gold.json` que lit le banc.

La source de vérité de l'or est `eurio.db` sur le VPS (tables
`crop_gold_versions` / `crop_gold_annotations`, cf. D11) — pas le fichier local.
`bench.gold_crop.datasets.charger()` ne sait pourtant lire qu'un
`<out>/gold.json` : c'est ce module qui fait le pont. Deux conséquences
concrètes :

* le harness (RE-4) peut tourner sur **une autre machine** que celle de la
  séance — le PC n'a jamais vu passer un `gold.json` ;
* le jour de RE-4, on exécute sur la version **gelée**, et l'empreinte est
  re-calculée ici puis comparée à `snapshot_sha256`. Un or qu'on croit gelé
  mais dont le contenu a bougé est exactement ce que RE-5 interdit.

⚠️ **`fetch` COMPLÈTE `sample`, il ne le remplace pas.** `charger()` a besoin du
`manifest.json` et des `raws/` produits par
`python -m bench.gold_crop.sample --out <dir>` ; `fetch` n'apporte que les
annotations. Sans manifeste dans `--out`, le harness ne partira pas.

    cd ml && python -m bench.gold_crop.fetch --out state/gold_crop/v1

**Le filet local n'est pas écrasé à l'aveugle.** Si le `gold.json` sur place
porte des annotations que le canonique n'a PAS (asset_id + passe), c'est le
symptôme d'un envoi qui a échoué : le fichier est alors la seule copie, et
l'écraser la perdrait. On refuse (code 2) et on les liste, sauf `--force`.
L'inverse — le canonique en sait plus — s'écrase sans discuter.

Empreinte : `store.crop_gold.instantane()` sérialise 12 colonnes par ligne,
triées par `(passe, asset_id)`, en JSON déterministe. Toutes ces colonnes sont
rendues par `GET /crop-gold/<v>` dans ce même ordre, donc **l'empreinte est
reproductible côté client** — c'est ce que fait `empreinte_instantane()`.

Codes de sortie : 0 ok · 1 réseau/auth · 2 refus (filet local, ou empreinte
divergente).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

ML_DIR = Path(__file__).resolve().parents[2]

#: Même convention que `annotate/serve.py`. ⚠️ INDISPENSABLE :
#: `eurio-api.musubi.dev` est derrière Cloudflare, qui refuse l'UA par défaut
#: d'urllib (`Python-urllib/3.x`) avec un 403 « error code: 1010 » — une page
#: HTML, pas du JSON. `curl` passe, le client Python non : la panne ne se voit
#: QUE dans l'outil.
USER_AGENT = "eurio-gold-fetch/1.0"

#: Les 13 colonnes de l'instantané canonique, cf. `store.crop_gold.instantane`.
COLONNES_INSTANTANE = ("asset_id", "passe", "cx", "cy", "a", "b", "theta_deg",
                       "indecidable", "strate_tiree", "strate_confirmee",
                       "familles", "actor", "editor_version")


class ErreurCanonique(Exception):
    """Le canonique n'a pas répondu ce qu'il fallait. Le message est pour un
    humain : il dit quoi faire, pas seulement ce qui a cassé."""


def _sortie(out: Path, passe: int) -> Path:
    """Le nom de fichier que `datasets.charger()` et `serve.py` attendent."""
    return out / ("gold.json" if passe == 1 else f"gold.pass{passe}.json")


def lire_canonique(version: str, *, base_url: str, token: str,
                   timeout: float = 30.0) -> dict:
    """`GET /crop-gold/<version>`, toutes passes confondues.

    Pas de filtre `passe` : l'empreinte de l'instantané porte sur TOUTES les
    lignes. Filtrer ici la rendrait irreproductible.
    """
    req = urlrequest.Request(
        f"{base_url.rstrip('/')}/crop-gold/{version}",
        headers={"Authorization": f"Bearer {token}",
                 "User-Agent": USER_AGENT})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urlerror.HTTPError as exc:
        corps = exc.read().decode(errors="replace")
        raise ErreurCanonique(_diagnostic_http(exc.code, corps)) from exc
    except Exception as exc:                                  # noqa: BLE001
        raise ErreurCanonique(
            f"canonique injoignable ({base_url}) : {exc}") from exc


def _diagnostic_http(code: int, corps: str) -> str:
    """Traduit un code HTTP en geste. Un « 403 » nu ne dit pas quoi faire."""
    extrait = corps.strip()[:300]
    if code == 403 and "<html" in corps.lower():
        return ("403 avec une page HTML : c'est Cloudflare, pas l'API. L'UA par "
                "défaut d'urllib est refusé (« error code: 1010 ») — le client "
                f"doit poser un User-Agent (ici « {USER_AGENT} »). "
                f"Extrait : {extrait[:120]}")
    if code in (401, 403):
        return (f"{code} — le token n'a pas le scope `lab:read`, ou il est "
                f"expiré. Vérifie EURIO_API_TOKEN. Détail : {extrait}")
    if code == 404:
        return (f"404 — cette version d'or n'existe pas dans le canonique. "
                f"Détail : {extrait}")
    return f"HTTP {code} : {extrait}"


def empreinte_instantane(version: str, lignes: list[dict]) -> str:
    """Rejoue `store.crop_gold.instantane()` côté client, à l'octet.

    Le serveur projette 13 colonnes par ligne, dans l'ordre `(passe, asset_id)`
    rendu par `lire()`, puis `json.dumps(sort_keys=True,
    separators=(",", ":"), ensure_ascii=False)`. `GET /crop-gold/<v>` rend ces
    mêmes lignes dans ce même ordre : la reproduction est exacte, pas
    approchée.
    """
    import hashlib

    projete = [{k: ligne.get(k) for k in COLONNES_INSTANTANE} for ligne in lignes]
    contenu = json.dumps({"gold_version": version, "annotations": projete},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(contenu.encode()).hexdigest()


def entree_gold(ligne: dict) -> dict:
    """Une ligne canonique → une entrée `gold.json`, format outil d'annotation.

    L'ellipse redevient `theta` (le canonique la stocke en `theta_deg`), et
    `indecidable` / `prefill_modifie` redeviennent des booléens (SQLite les
    range en 0/1).
    """
    coords = (ligne.get("cx"), ligne.get("cy"), ligne.get("a"),
              ligne.get("b"), ligne.get("theta_deg"))
    ellipse = None
    if None not in coords:
        ellipse = {"cx": ligne["cx"], "cy": ligne["cy"], "a": ligne["a"],
                   "b": ligne["b"], "theta": ligne["theta_deg"]}
    prefill = ligne.get("prefill_modifie")
    return {"asset_id": ligne["asset_id"],
            "ellipse": ellipse,
            "indecidable": bool(ligne.get("indecidable")),
            "strate_tiree": ligne.get("strate_tiree"),
            "strate_confirmee": ligne.get("strate_confirmee"),
            "familles": ligne.get("familles"),
            "secondes": ligne.get("secondes"),
            "prefill_modifie": None if prefill is None else bool(prefill),
            "editor_version": ligne.get("editor_version")}


def etiquettes_famille(familles: list[str] | None) -> list[str]:
    """Les colonnes où une image se compte (D16).

    `[]` n'est pas « rien » : c'est **facile**, aucune des trois difficultés.
    `None` est « pas encore étiquetée » — les deux se confondre ferait passer
    une image non relue pour une image facile.
    """
    if familles is None:
        return ["(non étiquetée)"]
    return list(familles) or ["facile"]


def _annotations_reelles(fichier: Path) -> dict:
    """Les entrées d'un `gold.json` qui portent un GESTE.

    Une entrée ouverte puis abandonnée (strate confirmée, pas d'ellipse) n'est
    pas une annotation — `serve.py` ne l'envoie pas au canonique, donc elle ne
    doit pas déclencher la protection du filet.
    """
    if not fichier.exists():
        return {}
    try:
        brut = json.loads(fichier.read_text()).get("annotations", {})
    except ValueError:
        return {}
    return {k: v for k, v in brut.items()
            if v.get("ellipse") or v.get("indecidable")}


def orphelines_locales(fichier: Path, entrees_canonique: dict) -> list[str]:
    """Ce que le fichier local porte et que le canonique ignore.

    C'est la trace d'un envoi qui a échoué : ces annotations n'existent nulle
    part ailleurs. Les écraser serait la seule vraie perte possible ici.
    """
    return sorted(set(_annotations_reelles(fichier)) - set(entrees_canonique))


def ecrire(fichier: Path, entrees: dict, *, version: str, passe: int,
           frozen_at: str | None, snapshot_sha256: str | None) -> None:
    """Écriture atomique (`.tmp` + `replace`), comme `serve.py`.

    Un `gold.json` tronqué ferait échouer le banc sur un message de JSON, pas
    sur la vraie cause.
    """
    fichier.parent.mkdir(parents=True, exist_ok=True)
    tmp = fichier.with_suffix(".tmp")
    tmp.write_text(json.dumps(
        {"version": version, "passe": passe,
         "ecrit_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "origine": "canonique", "frozen_at": frozen_at,
         "snapshot_sha256": snapshot_sha256,
         "n": len(entrees), "annotations": entrees},
        indent=1, ensure_ascii=False))
    tmp.replace(fichier)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ML_DIR / "state" / "gold_crop" / "v1"),
                    help="dossier du jeu d'or (celui de `sample`)")
    ap.add_argument("--version", default=None,
                    help="version d'or ; défaut : celle du manifeste, sinon v1")
    ap.add_argument("--passe", type=int, default=1, choices=(1, 2))
    ap.add_argument("--force", action="store_true",
                    help="écraser le filet local même s'il porte des "
                         "annotations absentes du canonique")
    ap.add_argument("--api-url", default=os.environ.get("EURIO_API_URL"))
    ap.add_argument("--api-token", default=os.environ.get("EURIO_API_TOKEN"))
    a = ap.parse_args(argv)

    if not a.api_url or not a.api_token:
        print("🔴 EURIO_API_URL / EURIO_API_TOKEN absents — le canonique est "
              "injoignable, et c'est LUI la source de vérité de l'or (D11). "
              "Charge le devShell (`direnv reload`, ou `eval \"$(direnv export "
              "zsh)\"`) avant de relancer.")
        return 1

    out = Path(a.out).resolve()
    manifeste = out / "manifest.json"
    version = a.version
    if version is None and manifeste.exists():
        version = json.loads(manifeste.read_text()).get("version")
    version = version or "v1"

    try:
        rep = lire_canonique(version, base_url=a.api_url, token=a.api_token)
    except ErreurCanonique as exc:
        print(f"🔴 {exc}")
        return 1

    lignes = rep.get("annotations") or []
    infos = rep.get("version") or {}
    frozen_at = infos.get("frozen_at")
    snapshot = infos.get("snapshot_sha256")

    recalcule = empreinte_instantane(version, lignes)
    if frozen_at and snapshot and recalcule != snapshot:
        print(f"🔴 empreinte divergente sur l'or GELÉ {version} :")
        print(f"   canonique   {snapshot}")
        print(f"   recalculée  {recalcule}")
        print("   L'or a bougé après son gel, ou la réponse est tronquée. "
              "RE-5 interdit de continuer : rien n'est écrit.")
        return 2

    entrees = {ligne["asset_id"]: entree_gold(ligne)
               for ligne in lignes if int(ligne.get("passe", 1)) == a.passe}
    fichier = _sortie(out, a.passe)
    orphelines = orphelines_locales(fichier, entrees)
    if orphelines and not a.force:
        print(f"🔴 refus : {fichier.name} porte {len(orphelines)} annotation(s) "
              f"que le canonique n'a pas —")
        for asset in orphelines:
            print(f"   {asset}")
        print("   C'est le symptôme d'un envoi qui a échoué : ce fichier en est "
              "la SEULE copie. Renvoie-les (rouvre la séance, la route est "
              "idempotente) avant de rapatrier, ou `--force` pour les perdre.")
        return 2

    ecrire(fichier, entrees, version=version, passe=a.passe,
           frozen_at=frozen_at, snapshot_sha256=snapshot)

    par_famille: dict[str, int] = {}
    for e in entrees.values():
        for f in etiquettes_famille(e.get("familles")):
            par_famille[f] = par_famille.get(f, 0) + 1

    print(f"or {version}  ·  passe {a.passe} → {fichier}")
    print(f"annotations : {len(entrees)} (toutes passes : {len(lignes)})")
    # Une image compte dans CHACUNE de ses familles : la somme dépasse le total.
    print("par famille : " + (
        "  ".join(f"{k} {v}" for k, v in sorted(par_famille.items())) or "—"))
    if frozen_at:
        print(f"gelé le {frozen_at}  ·  sha256 {snapshot}  ·  empreinte vérifiée")
    else:
        print("⚠️  version NON gelée — copie de travail, pas une référence : "
              "RE-5 n'est tenu que par le gel (`python -m bench.gold_crop.geler "
              f"--version {version}`).")
    if not manifeste.exists():
        print(f"⚠️  pas de manifest.json dans {out} — `fetch` complète `sample`, "
              f"il ne le remplace pas. Le banc ne partira pas sans le manifeste "
              f"ni les raws : `python -m bench.gold_crop.sample --out {a.out}`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
