"""Qui a le droit d'appeler quoi, sur le serve-role (review-collaborative-v2, lot 4b).

POURQUOI CE MODULE EXISTE À PART
--------------------------------
La table vivait dans ``server_serve.py``, dont l'import ouvre la base, applique
les migrations et monte l'app. Une politique d'accès doit pouvoir être LUE et
TESTÉE sans démarrer un serveur : stdlib pure, aucun effet de bord.

CE QU'ELLE REMPLACE
-------------------
Ces routers étaient montés avec ``require_principal`` — *tout principal
authentifié*, sans aucun scope. Le filtrage de nav (lot 4) cachait les pages à un
ami en rôle ``reviewer``, mais il pouvait encore les appeler à la main. Le
filtrage est du confort ; ceci est la garde.

LE COUPLE, PAS UN SCOPE UNIQUE
------------------------------
Tous ces routers mélangent lecture et écriture (``coins_routes`` : 17 GET, 1
PATCH, 1 POST, 1 PUT, 1 DELETE). Un scope unique serait soit trop lâche pour les
écritures, soit trop strict pour les lectures. Le verbe HTTP porte exactement la
distinction que le vocabulaire de scopes encode déjà — cf.
``auth_principal.require_scope_by_method``.
"""
from __future__ import annotations

from typing import Final

#: `nom de router → (scope de LECTURE, scope d'ÉCRITURE)`.
#:
#: ⚠️ `peer_arbitration` exige **`review:arbitrate`** en écriture, et c'est le
#: point important de ce lot. Il exigeait `review:write` — que le rôle `reviewer`
#: possède — donc un ami pouvait appeler
#: `POST /peer-arbitration/{id}/approve` sur SA PROPRE décision en quarantaine et
#: la pousser dans le canonique. La quarantaine du lot 3 était contournable en un
#: appel. Vérifié en conditions réelles le 2026-08-23 avant correctif : 200, puis
#: `arbitration_status = 'approved'`.
#:
#: La LECTURE reste ouverte au reviewer : voir où en sont ses propres décisions
#: n'est pas arbitrer, et c'est ce qui rend la quarantaine honnête plutôt
#: qu'opaque.
ROUTER_SCOPES: Final[dict[str, tuple[str, str]]] = {
    "coin_assets":      ("coins:read", "coins:write"),
    "coins":            ("coins:read", "coins:write"),
    "sets":             ("coins:read", "coins:write"),
    # Télémétrie d'entraînement (pulse, readiness, diversité, cohortes) — que des
    # GET. `training:run` et non `lab:read` : un ami a `lab:read` (la page Besoin
    # en dépend), et la nav lui cache déjà Operations. Les deux gardes doivent
    # dire la même chose, sinon l'une des deux ment.
    "operations":       ("training:run", "training:run"),
    "referential":      ("coins:read", "coins:write"),
    "peer_arbitration": ("review:read", "review:arbitrate"),
    # La file de review est le SEUL endroit où un ami écrit — et ses écritures
    # partent en quarantaine (lot 3), elles n'atteignent pas le canonique.
    "review_queue":     ("review:read", "review:write"),
}

#: Recettes d'augmentation : métadonnée de lab, montée hors `_CANDIDATES`.
RECIPE_SCOPES: Final[tuple[str, str]] = ("lab:read", "training:run")
