"""L'ordre de montage des routeurs est un contrat, pas une préférence.

FastAPI résout dans l'ordre d'enregistrement. `coins_routes` déclare
`GET /coins/{eurio_id}` : monté avant `coin_assets_routes`, il capture
`/coins/enrichment-counts` et répond « coin enrichment-counts not found ».

Ce 404 est le pire des symptômes — il est *crédible*. Il ressemble exactement à
une route absente, alors que le routeur est monté et fonctionnel. Constaté en
production le 2026-08-16, après un déploiement dont tous les autres signaux
étaient au vert.

On vérifie la source plutôt que l'app : importer `server_serve` déclenche le
boot complet (DB canonique, auth, MinIO), hors de portée d'un test unitaire.
"""

from __future__ import annotations

import re
from pathlib import Path

ML_DIR = Path(__file__).parent.parent


def _mount_order(source: str, names: tuple[str, ...]) -> dict[str, int]:
    """Position de la première mention de chaque routeur dans le fichier."""
    return {n: source.index(n) for n in names if n in source}


def test_serve_mounts_coin_assets_before_coins():
    src = (ML_DIR / "serving" / "server_serve.py").read_text(encoding="utf-8")
    block = re.search(r"_CANDIDATES = \[(.*?)\]", src, re.S)
    assert block, "_CANDIDATES introuvable — le mécanisme de montage a changé"
    order = _mount_order(block.group(1), ("serving.coin_assets_routes", "serving.coins_routes"))
    assert order["serving.coin_assets_routes"] < order["serving.coins_routes"], (
        "coin_assets doit être monté AVANT coins, sinon /coins/{eurio_id} "
        "capture /coins/enrichment-counts et le canonique répond 404"
    )


def test_local_server_mounts_coin_assets_before_coins():
    """Le ML API local doit appliquer le même ordre — sinon le défaut ne se
    manifeste que sur le VPS, c'est-à-dire le plus tard possible."""
    src = (ML_DIR / "serving" / "server.py").read_text(encoding="utf-8")
    order = _mount_order(src, ("coin_assets_routes.router", "coins_routes.router"))
    assert order["coin_assets_routes.router"] < order["coins_routes.router"]
