# Auto-validation — followups différés

> Sujets identifiés en code review du 2026-05-05 et reportés à des sessions
> futures. Ne traiter qu'après alignement explicite.

## À traiter dans une session dédiée

### LotDetailDrawer.vue (410 lignes) — composant non monté

`admin/packages/web/src/features/review/components/LotDetailDrawer.vue` implémente
un drawer complet avec les 3 panels (Texte / Dino / Auto-validate) tels que
décrits dans `vision.md` §"Cible UX d'arrivée". Il n'est importé nulle part :

- `LotReviewDetailPage.vue` utilise un layout full-page différent (2 colonnes)
- `LotReviewView.vue` navigue vers la page via `openLot(key)` au lieu de monter
  le drawer

Décision en suspens : (a) intégrer le drawer en remplaçant le layout page,
(b) supprimer le drawer et porter sa logique dans la page, (c) garder les
deux pour des contextes différents.

À ré-évaluer quand on attaquera le **chunk 8** (combinatoire Dino × texte →
auto-accept), parce que la cible UX 3-panels deviendra concrète à ce moment-là.

Composables impactés (non utilisés dans la page actuelle, montés uniquement
dans le drawer) :
- `useDinoSuggestions.ts` — fetch dino suggestions
- `useTextSignals.ts` — fetch text signals
- `useLotReview.ts` — méthodes lot decide
- `useLotReviewKeybinds.ts` — keybinds spécifiques lot

### Statuts `auto_dino` et `auto_dino_text`

Mentionnés dans `vision.md` §"Cible end-state" et `vision.md` §P3, et
`progress.md` chunk 2 §"Endpoint test" → mais **pas implémentés en schema**.
Les valeurs `image_assets.resolution_status` actuelles n'incluent pas ces
statuts (cf `ml/state/schema.sql` et CHECK constraints).

C'est cohérent : le chunk 8 (auto-accept multi-signal) n'est pas livré, donc
ces statuts n'ont rien à écrire pour l'instant. Reporter l'ajout au schema +
au CHECK + à la matrice `_route_decision_for_source_image()` dans `enqueue.py`
quand le chunk 8 sera attaqué.

À ce moment, audit complet des callers `resolution_status == 'auto_*'` pour
s'assurer que le front sait les afficher (badge `auto` côté page Coin selon
vision.md).

## À discuter (pas urgent)

### `status_cli.py` accède `Store._connection()` privé

`ml/sources/ebay/status_cli.py` instantie un `Store` et appelle `store._connection()`.
Convention `_method` = privé, donc couplage fragile. Soit exposer
`Store.connection()` public, soit créer une méthode `Store.ebay_freshness()`
qui encapsule la requête. À voir au prochain refacto de `ml/state/store.py`.

### CLI `__main__` par step ?

Aujourd'hui, les steps `discover/persist/download/detect_crop/resolve/text_signal/
auto_validate/enqueue` sont runnable via Python import + call, mais aucun n'a
d'entrypoint `if __name__ == "__main__"`. Seul `auto_validate` a un script
backfill (`ml/scripts/backfill_dino_predictions.py`).

Si on veut "indépendance des étapes" au sens "je peux re-run un step sur un run
existant en une commande", il faudrait soit (a) un script générique
`ml/scripts/run_step.py STEP_NAME --run-id ...`, soit (b) ajouter `__main__`
à chaque step. À trancher si le besoin se présente.

### Asymétrie du flag `--force`

- `text_signal.py` et `auto_validate.py` ont `force: bool = False`
- `discover, persist, download, detect_crop, resolve, enqueue` n'en ont pas

Pour `download/detect_crop/resolve` l'idempotence est gérée via vérification
disque ou DB, donc `force` n'aurait du sens que pour invalider des artefacts
existants. À uniformiser uniquement si on découvre un cas d'usage concret.

### Nommer mieux `route_decision`

Le nom suggère un statut général d'acheminement, mais le code n'écrit cette
colonne que pour `'rejected_text'` (chunk 6.c). Risque de confusion future
quand on ajoutera des décisions auto (`auto_dino_text`, etc.).

À renommer en `pre_ingestion_route` ou enrichir la sémantique avec une matrice
explicite quand chunk 8 arrive.

### `auto_validate.py` — singletons sans thread-safety

`_encoder_cache` et `_bank_cache` sont module-level sans lock. `progress.md`
chunk 2 dit "multi-thread OK avec ce pattern" mais c'est techniquement faux
(double-load possible si 2 threads entrent simultanément). Pas un bug réel
aujourd'hui (l'orchestrateur est mono-thread), à fixer si on parallélise.

## Ne pas traiter (false positives identifiés)

Pour mémoire, la code review a généré des findings qui se sont avérés
incorrects après vérification manuelle :

- Les endpoints `/sources/{id}/runs/{run_id}/{breakdown,listings,searches,discarded}`
  ne sont **pas orphelins** — utilisés par `useRun*.ts` dans
  `features/sources/composables/`.
- Les endpoints `/sources/ebay/{quota-status,freshness}` ne sont **pas
  orphelins** — utilisés par `useSourceDetail.ts:348-356`.
- `get_run_listings` ne lit **pas** des colonnes vides : `download_status`,
  `crop_status`, `n_crops_detected` etc. sont écrites par `download.py` et
  `detect_crop.py`.
- `ml/api/distance_logic.py` est **utilisé** par `lab_routes.py:1303`.
- `ebay/adapter.py record_discarded` a bien un guard `item_id` dans les deux
  branches (theme_dropped et accept_listing).
