# 07 — Store SQLite : atomicité des écritures multi-DML

> Fiche de remédiation auto-portée — audit hardening 2026-07. Périmètre : `ml/store/`,
> `ml/serving/lab_routes.py`, `ml/sources/_base/steps/enqueue.py`. Toutes les preuves en `file:line`.

## Résumé en une phrase

`StoreBase` ouvre ses connexions en `isolation_level=None` (**autocommit**) : chaque
`conn.execute()` est committé individuellement, donc un handler qui enchaîne 2-3 écritures
**sans `BEGIN` explicite** n'est **pas atomique** — une exception au milieu laisse la DB dans
un état partiel définitif. Le contrat (« le caller pose le `BEGIN` ») est respecté dans
`review/review_queue_routes.py` et `serving/ingest_routes.py`, mais **pas** dans les 5 handlers
homologues de `lab_routes.py`.

## Findings

| Sév. | Fichier:ligne | Défaut |
|---|---|---|
| **high** | `ml/serving/lab_routes.py` (set_asset_training_eligible ~2437, reopen_asset_review, accept_asset_training, reassign_asset, intruder_dismiss ~2547) | 5 handlers appellent `_get_store()._connection()` + `apply_*`/`emit_field_event` **sans `BEGIN`**, puis `conn.commit()` (no-op en autocommit) sans try/rollback |
| medium | `ml/sources/_base/steps/enqueue.py:241-247` (+ 3 sites INSERT) | Idempotence par `SELECT 1 … WHERE image_asset_id` **puis** `INSERT` sans `ON CONFLICT` : check-then-act racy → `IntegrityError` sur la contrainte `UNIQUE(image_asset_id)` en cas de concurrence |
| medium | `ml/sources/_base/steps/enqueue.py` vs `ml/store/decisions.py:157-176` | Deux stratégies d'idempotence divergentes sur la **même** contrainte : `apply_reopen_review` fait `INSERT … ON CONFLICT DO UPDATE` (correct), `enqueue` fait SELECT-then-INSERT (racy) |
| low | `ml/store/connection.py` `_bootstrap()` | `ALTER TABLE` additifs vulnérables à une race TOCTOU inter-process au démarrage concurrent (deux `Store()` créés en même temps) |

## Cause racine

`ml/store/connection.py:106-113` : `sqlite3.connect(..., isolation_level=None)` dans les deux
branches (ro/rw). Documenté dans `ml/store/decisions.py:14-19` : les fonctions `apply_*` **ne
font ni `BEGIN` ni `COMMIT`** — le caller possède la transaction. Le seul wrapper transactionnel
exposé est `StoreBase._writing()` (`BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`). Les handlers de
`lab_routes.py` (les plus récents, « Jeu d'entraînement ») ont ré-implémenté le call-site en
oubliant le `BEGIN` — régression d'atomicité par rapport aux endpoints jumeaux.

**Scénario d'échec concret** (`reassign_asset`) : `UPDATE image_assets SET eurio_id=…` est committé
immédiatement ; si `emit_field_event` (audit) ou `training_scan_dismiss_intruder` échoue ensuite
(DB busy, erreur applicative), l'`eurio_id` de la pièce est changé **définitivement sans trace
d'audit**. Idem `accept_asset_training` : `training_eligible=1` (repris au prochain bake) alors que
`review_queue.status` reste `open` (toujours visible en review) si le 2ᵉ UPDATE échoue.

## Plan de correction

### Chunk A — envelopper les 5 handlers `lab_routes.py` (high, ~1h)

Pour chacun des 5 handlers, remplacer le pattern actuel :

```python
conn = _get_store()._connection()
apply_xxx(conn, …)
emit_field_event(conn, …)
conn.commit()          # no-op en autocommit
```

par le pattern déjà utilisé dans `review_queue_routes.py:1840-1848` :

```python
conn = _get_store()._connection()
conn.execute("BEGIN")
try:
    apply_xxx(conn, …)
    emit_field_event(conn, …)
    conn.execute("COMMIT")
except Exception:
    conn.execute("ROLLBACK")
    raise
```

Mieux : exposer et utiliser un **context manager partagé** `store.writing()` (déjà présent sur
`StoreBase._writing()`) plutôt que le `BEGIN`/`COMMIT` manuel dupliqué — cf. fiche 06
(duplication du pattern transactionnel, 6+ occurrences). Décider : promouvoir `_writing()` en
API publique `writing()` et migrer **tous** les call-sites en une passe.

**Critère de vérification** : test qui monkeypatch la 2ᵉ écriture d'un handler pour lever, puis
assert que la 1ʳᵉ écriture a été **rollback** (l'`eurio_id`/`training_eligible` n'a pas changé).
Aucun tel test n'existe aujourd'hui.

### Chunk B — idempotence atomique de `enqueue.py` (medium, ~1h30)

Les 3 sites `INSERT INTO review_queue` sont précédés d'un `SELECT 1 … already`. **Attention** :
le `review_id` inséré est réutilisé en aval (`_reject_crop_terminal(review_id=…)`, consensus) —
un `ON CONFLICT DO NOTHING` naïf laisserait le code aval opérer sur un `review_id` non inséré.
Deux options :

1. **Recommandée** — transformer chaque `INSERT` en `INSERT … ON CONFLICT(image_asset_id) DO
   NOTHING` **et** tester `cur.rowcount == 0` → traiter comme le cas `already` (skip du bloc
   complet, `n_skipped += 1`, `continue`) au lieu de poursuivre vers `_reject_crop_terminal`.
2. Poser un `BEGIN IMMEDIATE` sur toute la boucle d'enqueue pour sérialiser (verrou d'écriture),
   ce qui ferme la fenêtre check-then-act sans changer la structure — mais réduit la concurrence.

**Critère de vérification** : test qui lance deux `run_enqueue` concurrents sur le même
`source_image_id` (ou simule la course en insérant la ligne entre le SELECT et l'INSERT) et
assert « zéro crash, une seule ligne » — le docstring du module (`enqueue.py:4-6`) promet déjà ce
comportement (« re-running… inserts zero new rows »), il faut le verrouiller.

### Chunk C — `_bootstrap()` TOCTOU (low, optionnel)

Envelopper les `ALTER TABLE` additifs dans une transaction + `PRAGMA` de lock, ou sérialiser le
bootstrap via un verrou fichier. Faible priorité (fenêtre étroite au démarrage concurrent).

## Effort & priorité

1. **Chunk A** (high, data-integrity) — à faire en premier, mécanique, pattern connu.
2. **Chunk B** (medium) — à coupler avec la promotion de `store.writing()` (fiche 06).
3. **Chunk C** (low) — opportuniste.

Total ~3h. À traiter avec la fiche 06 (duplication du pattern transactionnel) : la vraie cible
est **un seul** context manager `store.writing()` consommé partout, ce qui règle A, B (option
BEGIN) et la duplication d'un coup.
