"""Serveur jetable de la séance d'annotation du jeu d'or.

Sert `<out>/` (manifeste + raws) et l'outil, et **écrit `gold.json` à chaque
image validée**. L'écriture incrémentale n'est pas un confort : une séance de
40 minutes perdue sur un onglet fermé, on ne la refait pas.

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
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ICI = Path(__file__).resolve().parent
ML_DIR = ICI.parents[2]


def _sortie(out: Path, passe: int) -> Path:
    return out / ("gold.json" if passe == 1 else f"gold.pass{passe}.json")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, racine: Path, passe: int, n_double: int, **kw):
        self.racine, self.passe, self.n_double = racine, passe, n_double
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
        tmp.replace(cible)                          # écriture atomique
        self._json({"ok": True, "n": len(annotations), "fichier": cible.name})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ML_DIR / "state" / "gold_crop" / "v1"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--passe", type=int, default=1, choices=(1, 2))
    ap.add_argument("--n-double", type=int, default=10,
                    help="images re-annotées en passe 2 (plafond du banc)")
    a = ap.parse_args(argv)

    racine = Path(a.out).resolve()
    if not (racine / "manifest.json").exists():
        print(f"pas de manifeste dans {racine} — lance d'abord "
              f"`python -m bench.gold_crop.sample --out {a.out}`")
        return 1

    srv = ThreadingHTTPServer(("127.0.0.1", a.port), partial(
        Handler, racine=racine, passe=a.passe, n_double=a.n_double))
    print(f"jeu d'or : {racine}")
    print(f"passe {a.passe} → {_sortie(racine, a.passe).name}")
    print(f"ouvre  http://127.0.0.1:{a.port}   (Ctrl-C pour arrêter)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\narrêt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
