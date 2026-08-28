"""Serveur jetable de la séance d'annotation du jeu d'or.

Sert `<out>/` (manifeste + raws) et l'outil, et **écrit à chaque image
validée** — dans le canonique **et** dans `<out>/gold.json`.

L'écriture incrémentale n'est pas un confort : une séance de 40 minutes perdue
sur un onglet fermé, on ne la refait pas. Et les deux destinations ne font pas
doublon :

* le **canonique** (`PUT /crop-gold/<version>/annotations`, via `EURIO_API_URL`
  + `EURIO_API_TOKEN`) est la vérité — sauvegardée, joignable, servable au
  front hébergé. C'est ce qui manquait à `denom-gold`, dont le verdict humain
  vit dans un `.jsonl` local ;
* le **fichier** est le filet : si le réseau tousse au milieu de la séance,
  l'annotation est déjà sur disque et le renvoi la rattrapera. Il n'est PAS la
  source de vérité.

Sans `EURIO_API_URL`, le serveur le **dit au démarrage et à chaque écriture**
au lieu de tourner en mode local silencieux — un dispositif qui a l'air de
marcher sans sauvegarder est exactement le défaut qu'on corrige.

    cd ml && python -m bench.gold_crop.annotate.serve --out state/gold_crop/v1
    # puis http://127.0.0.1:8765

Deux passes. `--passe 2` écrit `gold.pass2.json` et ne présente que les images
déjà annotées en passe 1 (échantillonnées par `--n-double`), à ≥ 24 h d'écart :
c'est la reproductibilité intra-annotateur, donc **le plafond du banc**
(cf. `JUGE.md`). Rien ne doit être crédité au-dessus du bruit de la main.

Le serveur est **local et sans authentification** : il n'écoute que sur
127.0.0.1 et n'écrit que dans `<out>`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

ICI = Path(__file__).resolve().parent
ML_DIR = ICI.parents[2]


def _sortie(out: Path, passe: int) -> Path:
    return out / ("gold.json" if passe == 1 else f"gold.pass{passe}.json")


def pousser_au_canonique(annotations: dict, *, version: str, passe: int,
                         base_url: str, token: str,
                         requete_sha256: str | None = None,
                         timeout: float = 20.0) -> dict:
    """`PUT /crop-gold/<version>/annotations`. Rend le compte par statut.

    Ne lève pas : une erreur réseau ne doit pas retenir la séance. Elle est
    RENDUE, affichée dans l'outil, et l'annotation reste sur disque — le renvoi
    suivant la rattrapera puisque la route est idempotente.
    """
    corps = {"annotations": [
        {"asset_id": a["asset_id"], "ellipse": a.get("ellipse"),
         "indecidable": bool(a.get("indecidable")), "passe": passe,
         "strate_tiree": a.get("strate_tiree"),
         "strate_confirmee": a.get("strate_confirmee"),
         "secondes": a.get("secondes"),
         "prefill_modifie": a.get("prefill_modifie")}
        for a in annotations.values() if a.get("ellipse") or a.get("indecidable")
    ], "requete_sha256": requete_sha256}
    req = urlrequest.Request(
        f"{base_url.rstrip('/')}/crop-gold/{version}/annotations",
        data=json.dumps(corps).encode(), method="PUT",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}",
                 # ⚠️ INDISPENSABLE. `eurio-api.musubi.dev` est derrière
                 # Cloudflare, qui refuse l'UA par défaut d'urllib
                 # (`Python-urllib/3.x`) avec un **403 « error code: 1010 »** —
                 # une page HTML, pas du JSON. Mesuré le 2026-08-28 : le même
                 # PUT passe en 200 avec n'importe quel autre UA. `curl` marchait
                 # donc, et l'outil non : la panne ne se voyait que dans l'outil.
                 # Même convention que `client/http.py:_headers`.
                 "User-Agent": "eurio-gold-annotate/1.0"})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as r:
            return {"ok": True, **json.loads(r.read())}
    except urlerror.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        return {"ok": False, "code": exc.code, "detail": detail}
    except Exception as exc:                              # noqa: BLE001
        return {"ok": False, "code": 0, "detail": str(exc)}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, racine: Path, passe: int, n_double: int,
                 version: str, api_url: str | None, api_token: str | None, **kw):
        self.racine, self.passe, self.n_double = racine, passe, n_double
        self.version, self.api_url, self.api_token = version, api_url, api_token
        super().__init__(*a, directory=str(racine), **kw)

    def log_message(self, fmt, *args):            # silence : la console sert au PO
        pass

    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                              # noqa: N802
        if self.path in ("/", "/index.html"):
            self.path = "/__outil__/index.html"
        if self.path.startswith("/__outil__/"):
            nom = self.path.removeprefix("/__outil__/")
            fichier = ICI / nom
            if fichier.parent != ICI or not fichier.is_file():
                self.send_error(404)
                return
            body = fichier.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/session":
            self._json(self._session())
            return
        super().do_GET()

    def _session(self) -> dict:
        manifeste = json.loads((self.racine / "manifest.json").read_text())
        images = [i for i in manifeste["images"] if i["role"] == "tirage"]
        deja = _sortie(self.racine, self.passe)
        annotations = json.loads(deja.read_text())["annotations"] if deja.exists() else {}
        if self.passe > 1:
            p1 = self.racine / "gold.json"
            if not p1.exists():
                return {"erreur": "passe 1 absente : gold.json n'existe pas"}
            faits = json.loads(p1.read_text())["annotations"]
            # échantillon déterministe : les n premiers par ordre de hachage
            ordre = sorted(faits, key=lambda k: hashlib.sha256(k.encode()).hexdigest())
            garde = set(ordre[: self.n_double])
            images = [i for i in images if i["asset_id"] in garde]
        return {"passe": self.passe, "images": images, "annotations": annotations,
                "requete_sha256": manifeste.get("requete_sha256")}

    def do_POST(self):                             # noqa: N802
        if self.path != "/api/save":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            annotations = json.loads(self.rfile.read(n))["annotations"]
        except (ValueError, KeyError, TypeError):
            self._json({"erreur": "corps illisible"}, 400)
            return
        cible = _sortie(self.racine, self.passe)
        tmp = cible.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"version": "v1", "passe": self.passe,
             "ecrit_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "n": len(annotations), "annotations": annotations},
            indent=1, ensure_ascii=False))
        tmp.replace(cible)                          # écriture atomique, filet local

        if not self.api_url or not self.api_token:
            self._json({"ok": True, "n": len(annotations), "fichier": cible.name,
                        "canonique": {"ok": False, "code": 0,
                                      "detail": "EURIO_API_URL/EURIO_API_TOKEN absents "
                                                "— rien n'est sauvegardé"}})
            return
        manifeste = json.loads((self.racine / "manifest.json").read_text())
        canon = pousser_au_canonique(
            annotations, version=self.version, passe=self.passe,
            base_url=self.api_url, token=self.api_token,
            requete_sha256=manifeste.get("requete_sha256"))
        self._json({"ok": True, "n": len(annotations), "fichier": cible.name,
                    "canonique": canon})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ML_DIR / "state" / "gold_crop" / "v1"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--passe", type=int, default=1, choices=(1, 2))
    ap.add_argument("--n-double", type=int, default=10,
                    help="images re-annotées en passe 2 (plafond du banc)")
    ap.add_argument("--version", default=None,
                    help="version d'or ; défaut : celle du manifeste")
    ap.add_argument("--api-url", default=os.environ.get("EURIO_API_URL"))
    ap.add_argument("--api-token", default=os.environ.get("EURIO_API_TOKEN"))
    a = ap.parse_args(argv)

    racine = Path(a.out).resolve()
    if not (racine / "manifest.json").exists():
        print(f"pas de manifeste dans {racine} — lance d'abord "
              f"`python -m bench.gold_crop.sample --out {a.out}`")
        return 1

    manifeste = json.loads((racine / "manifest.json").read_text())
    version = a.version or manifeste.get("version", "v1")
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), partial(
        Handler, racine=racine, passe=a.passe, n_double=a.n_double,
        version=version, api_url=a.api_url, api_token=a.api_token))
    print(f"jeu d'or : {racine}  ·  version {version}")
    print(f"passe {a.passe} → {_sortie(racine, a.passe).name}")
    if a.api_url and a.api_token:
        print(f"canonique : {a.api_url.rstrip('/')}/crop-gold/{version}/annotations")
    else:
        print("🔴 EURIO_API_URL / EURIO_API_TOKEN absents — l'or ne sera écrit "
              "QUE sur disque, donc pas sauvegardé. Charge le devShell.")
    print(f"ouvre  http://127.0.0.1:{a.port}   (Ctrl-C pour arrêter)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\narrêt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
