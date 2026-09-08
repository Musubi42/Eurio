"""Gèle une version d'or et publie son instantané dans `model-artifacts`.

Le gel est ce qui tient **RE-5** : tant que `frozen_at` est NULL la version
s'annote ; une fois gelée, toute écriture repart en **409** et une correction
exige une NOUVELLE version — plus la ré-exécution de tous les bras. C'est donc
le geste qui sépare « la séance du PO » de « la référence contre laquelle on
juge ».

    cd ml && python -m bench.gold_crop.geler --version v1 --note "séance du 29/08"

Trois choses valent d'être dites, parce qu'elles ont chacune un piège derrière :

* **le sha256 est calculé par le serveur**, sur l'instantané canonique. Un gel
  dont le client fournirait l'empreinte n'attesterait rien — il attesterait ce
  que le client a bien voulu envoyer. Ici le client ne fait que *vérifier* ;
* **re-geler un contenu identique est idempotent** (`deja: true`) ; re-geler un
  contenu DIFFÉRENT est un 409, et c'est voulu : ça voudrait dire que l'or a
  bougé après son gel ;
* **la publication n'est pas une route.** L'API expose `POST
  /crop-gold/<v>/geler` et `GET /crop-gold/<v>/instantane` ; c'est ce CLI qui
  relit l'instantané et le pousse dans `model-artifacts` — bucket déjà miroité
  par la sauvegarde, contrairement à un bucket neuf qui manquerait à
  `MIRROR_BUCKETS` sans que rien ne le dise (D11).

Garde CLIENT (pas serveur) : on refuse de geler moins de 60 annotations en
passe 1, parce que la séance en compte 60. `--force` passe outre — mais le banc
tournera alors sur un or incomplet, et RE-4 sur 12 images ne conclut rien.

Codes de sortie : 0 ok · 1 réseau/auth · 2 refus (garde des 60, 409, ou
empreinte divergente).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from bench.gold_crop.fetch import ErreurCanonique, _diagnostic_http, lire_canonique

ML_DIR = Path(__file__).resolve().parents[2]

USER_AGENT = "eurio-gold-geler/1.0"

#: La séance d'annotation compte 60 images (15 par strate, cf. `sample.py`).
N_SEANCE = 60

#: Bucket DÉJÀ miroité par la chaîne de sauvegarde.
BUCKET_INSTANTANE = "model-artifacts"


def cle_instantane(version: str) -> str:
    """Où vit l'instantané publié. Une clé par version, jamais écrasée."""
    return f"crop-gold/{version}/instantane.json"


def _appel(url: str, *, token: str, payload: dict | None = None,
           methode: str = "GET", timeout: float = 30.0) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    entetes = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    if data is not None:
        entetes["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=data, headers=entetes, method=methode)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as r:
            corps = r.read()
            return json.loads(corps) if corps else {}
    except urlerror.HTTPError as exc:
        brut = exc.read().decode(errors="replace")
        if exc.code == 409:
            raise OrDejaGele(_detail(brut)) from exc
        raise ErreurCanonique(_diagnostic_http(exc.code, brut)) from exc
    except Exception as exc:                                  # noqa: BLE001
        raise ErreurCanonique(f"canonique injoignable ({url}) : {exc}") from exc


class OrDejaGele(Exception):
    """409 : le serveur refuse. Sa raison est reprise VERBATIM — la reformuler
    ferait perdre le seul élément qui dit quoi faire (les deux sha)."""


def _detail(brut: str) -> str:
    """Le `detail` d'une HTTPException FastAPI, ou le corps tel quel."""
    try:
        return str(json.loads(brut).get("detail", brut))
    except ValueError:
        return brut.strip()


def compter_passe1(lignes: list[dict]) -> int:
    """Les annotations de passe 1 qui portent un geste (ellipse ou renoncement)."""
    return sum(1 for ligne in lignes
               if int(ligne.get("passe", 1)) == 1
               and (ligne.get("indecidable") or ligne.get("cx") is not None))


def publier(contenu: str, version: str) -> tuple[str, str | None]:
    """Pousse l'instantané dans `model-artifacts`. Rend (clé, erreur).

    Import PARESSEUX de `shared.storage` : il tire boto3, et une publication
    indisponible ne doit pas empêcher le GEL — qui, lui, est déjà acquis côté
    canonique quand on arrive ici.
    """
    cle = cle_instantane(version)
    try:
        from shared.storage.local_cache import upload_through

        upload_through(BUCKET_INSTANTANE, cle, contenu.encode(),
                       block_on_disconnect=False)
        return cle, None
    except Exception as exc:                                  # noqa: BLE001
        return cle, str(exc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", default="v1")
    ap.add_argument("--note", default=None,
                    help="note libre — non transmise par la route de gel, "
                         "affichée pour le journal de session")
    ap.add_argument("--force", action="store_true",
                    help="geler moins de 60 annotations de passe 1")
    ap.add_argument("--api-url", default=os.environ.get("EURIO_API_URL"))
    ap.add_argument("--api-token", default=os.environ.get("EURIO_API_TOKEN"))
    a = ap.parse_args(argv)

    if not a.api_url or not a.api_token:
        print("🔴 EURIO_API_URL / EURIO_API_TOKEN absents — le gel s'écrit dans "
              "le canonique, il n'a aucun sens en local. Charge le devShell "
              "(`direnv reload`, ou `eval \"$(direnv export zsh)\"`).")
        return 1

    base = a.api_url.rstrip("/")
    try:
        rep = lire_canonique(a.version, base_url=base, token=a.api_token)
    except ErreurCanonique as exc:
        print(f"🔴 {exc}")
        return 1

    lignes = rep.get("annotations") or []
    n1 = compter_passe1(lignes)
    if n1 < N_SEANCE and not a.force:
        print(f"🔴 refus : {n1} annotation(s) de passe 1 sur {N_SEANCE} — il en "
              f"manque {N_SEANCE - n1}. La séance compte 60 images (15 par "
              f"strate) ; geler ici figerait un or incomplet, et RE-4 sur un "
              f"sous-ensemble ne conclut rien. `--force` si c'est délibéré.")
        return 2

    try:
        gel = _appel(f"{base}/crop-gold/{a.version}/geler", token=a.api_token,
                     payload={"snapshot_key": cle_instantane(a.version)},
                     methode="POST")
    except OrDejaGele as exc:
        print(f"🔴 409 — le serveur refuse, verbatim : {exc}")
        print("   Re-geler un contenu IDENTIQUE est idempotent ; ce 409 dit "
              "donc que le contenu a changé. RE-5 : ça exige une nouvelle "
              "version, pas un écrasement.")
        return 2
    except ErreurCanonique as exc:
        print(f"🔴 {exc}")
        return 1

    sha = gel.get("snapshot_sha256")
    if gel.get("deja"):
        print(f"or {a.version} déjà gelé le {gel.get('frozen_at')} sur le MÊME "
              f"contenu — le gel est idempotent, rien n'a changé.")
    else:
        print(f"or {a.version} gelé  ·  sha256 {sha}  ·  {gel.get('octets')} octets")

    try:
        snap = _appel(f"{base}/crop-gold/{a.version}/instantane", token=a.api_token)
    except ErreurCanonique as exc:
        print(f"⚠️  gel acquis, mais instantané illisible : {exc}")
        return 1

    contenu = snap.get("contenu", "")
    relu = hashlib.sha256(contenu.encode()).hexdigest()
    if sha and relu != sha:
        print(f"🔴 l'instantané relu ({relu}) ne porte pas l'empreinte du gel "
              f"({sha}) — rien n'est publié.")
        return 2

    cle, erreur = publier(contenu, a.version)
    if erreur:
        print(f"⚠️  publication impossible dans {BUCKET_INSTANTANE} : {erreur}")
        print(f"   Le gel TIENT (il vit dans le canonique) ; seule la copie "
              f"dans le bucket manque. À rejouer depuis une machine qui a les "
              f"accès MinIO.")
    else:
        print(f"instantané publié : {BUCKET_INSTANTANE}/{cle}")
    print(f"snapshot_key : {cle}")
    if a.note:
        print(f"note : {a.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
