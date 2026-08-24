"""Écriture des verdicts de consensus — SQL pur, sans le moteur qui les calcule.

Ce module existe pour une raison précise : **le canonique doit pouvoir écrire un
verdict qu'il ne sait pas calculer.**

`review/validation/persist.py` fait la même chose, mais il importe le moteur
(`review.validation.consensus` → `experts` → `training.foundation`), donc numpy,
donc l'image lean du VPS ne peut pas le charger. Et l'image lean **n'embarque
même pas `training/`** : `docker logs eurio-api` le dit à chaque boot
(« routers skippés : review_queue (No module named 'training') »).

Conséquence mesurée le 2026-08-24 : sous Direction A, les verdicts de consensus
ne pouvaient être recalculés NULLE PART. Le Mac a numpy mais lit une réplique
read-only ; le VPS écrit mais n'a pas le moteur. C'est exactement la situation
que la Direction A résout partout ailleurs — le calcul reste où sont les
dépendances, seules les LIGNES voyagent par `/ingest/*`.

Le schéma de la table vit dans `state/schema.sql` ; l'UPSERT ci-dessous est le
miroir de celui de `persist.py`. S'ils divergent, c'est ce module qui fait foi
côté canonique — et `tests/test_ingest_consensus.py` rougit.
"""

from __future__ import annotations

import sqlite3

_UPSERT = """
INSERT INTO consensus_verdicts
  (image_asset_id, rule_version, outcome, lane, confidence, reason, rule,
   signals_json, computed_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
ON CONFLICT(image_asset_id, rule_version) DO UPDATE SET
  outcome      = excluded.outcome,
  lane         = excluded.lane,
  confidence   = excluded.confidence,
  reason       = excluded.reason,
  rule         = excluded.rule,
  signals_json = excluded.signals_json,
  computed_at  = datetime('now')
"""


def apply_ingest_consensus(
    conn: sqlite3.Connection, rows: list[dict]
) -> dict:
    """UPSERT des verdicts reçus. Rend ``{written, missing}``.

    ``missing`` liste les `image_asset_id` absents de `image_assets` : ils ne
    sont PAS écrits. Sans cette vérification, une faute de frappe côté client
    peuplerait la table de lignes orphelines qu'aucune jointure ne ramènerait
    — une écriture réussie et parfaitement inutile, la pire espèce.
    """
    written, missing = 0, []
    for r in rows:
        aid = r["image_asset_id"]
        if conn.execute(
            "SELECT 1 FROM image_assets WHERE id = ?", (aid,)
        ).fetchone() is None:
            missing.append(aid)
            continue
        conn.execute(
            _UPSERT,
            (
                aid,
                int(r["rule_version"]),
                r["outcome"],
                r["lane"],
                float(r.get("confidence") or 0.0),
                r.get("reason"),
                r.get("rule"),
                r.get("signals_json"),
            ),
        )
        written += 1
    return {"written": written, "missing": missing}
