"""Origine machine — mac / pc / vps depuis le hostname (pur, léger).

Source de vérité de « sur quelle machine tourne ce process », alignée sur le
dispatch ``.envrc`` (``hostname -s`` → profil devShell). Sert à :
- stamper ``experiment_iterations.created_on`` à la création (R3, Model B) —
  pour savoir où une itération a été calculée (et où vivent ses artefacts) ;
- répondre ``/whoami`` (le front gate les actions lourdes sur la machine
  d'origine).

Stdlib uniquement (``socket``) — importable sur l'image lean du VPS.
"""

from __future__ import annotations

import socket

# hostname → origine canonique. Miroir du ``case`` de ``.envrc`` (garder aligné).
_HOST_MAP: dict[str, str] = {
    "Musubi42s-MacBook-Air-Oim": "mac",
    "desktop": "pc",
    "nixos": "vps",
}


def machine_origin() -> str:
    """Origine canonique de cette machine : ``mac`` / ``pc`` / ``vps``.

    Fallback = le hostname court brut (jamais None) pour qu'une machine inconnue
    reste identifiable plutôt que masquée. ``EURIO_MACHINE_ORIGIN`` permet un
    override explicite (CI, conteneur, machine renommée).
    """
    import os

    override = os.environ.get("EURIO_MACHINE_ORIGIN", "").strip()
    if override:
        return override
    host = socket.gethostname().split(".", 1)[0]
    return _HOST_MAP.get(host, host)
