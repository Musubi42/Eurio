# Nettoyage — inventaire du lot 9

> Tenu à jour **au fil des lots**, exécuté à la fin. Découvrir cet inventaire le
> dernier jour, c'est en oublier la moitié (cf. D10).

## À supprimer une fois les lots 1-8 vérifiés

### Code — le tampon et ses deux fronts

| Chemin | Quoi | Remplacé par |
|---|---|---|
| `ml/review_service/` | 9 fichiers (app, auth, db, manage, routes_*) | `serving/review_queue/` sur le canonique |
| `ml/serving/review_routes.py` | claim/publish/decisions/ack/flow (tampon en OIDC) | lot 7 (bail) + écriture directe |
| `ml/serving/review_db.py` | wrapper `review.db` | — |
| `ml/review/publish_cli.py` | pont publish / reconcile | — (D1) |
| `admin/packages/review/` | mini-app reviewer standalone | `studio-local` (D2, D4) |
| `infra/review/` | conteneur `eurio-review.musubi.dev` | `eurio-admin.musubi.dev` |

⚠️ **`infra/review/` est EN SERVICE.** Arrêter le conteneur et retirer les labels
Traefik **avant** de supprimer les fichiers, sinon Traefik garde une route vers un
backend mort.

### Tâches

`ml/tasks.yml:667-690` — les 5 tâches `review:serve`, `review:reviewer:add`,
`review:reviewer:list`, `review:publish`, `review:reconcile`.

### Front — ce que le lot 8 a rendu redondant

| Chemin | Quoi | Remplacé par |
|---|---|---|
| `admin/.../review/pages/PeerArbitrationPage.vue` | arbitrage UNITAIRE (une décision à la fois, + table par reviewer) | `ArbitrageBulkPage.vue` (`/review/arbitrage`) |
| route `review/peer-arbitration` (`app/router.ts`) | — | rediriger vers `/review/arbitrage` |

⚠️ Conservée **délibérément** jusqu'ici (D10 : on ne supprime pas au fil de l'eau,
on supprime quand le remplaçant est prouvé). Sa page d'état vide pointe déjà vers
la vue en lot. Au moment de la retirer, vérifier qu'elle n'est plus le seul accès
à `/peer-arbitration/reviewers` (les onglets de la vue bulk la consomment aussi).

### Champs devenus constants

| Chemin | Quoi | Depuis |
|---|---|---|
| `serving/crop_edit_api.py` · `ManualCropResponse.minio_ok` | Vaut désormais **toujours `true`** : un échec d'écriture MinIO lève un 502 et n'écrit rien (revue du 2026-08-24). Le champ ne porte plus d'information | 2026-08-24 |
| `useReviewApi.ts` · `ManualCropResult.minio_ok` | Typé, jamais lu — il ne l'a jamais été, c'est précisément ce qui rendait l'échec muet | — |

Conservé pour l'instant : le retirer touche trois routers (review, coins, et la
réponse add-crop du legacy) pour un gain nul tant que le contrat ne bouge pas
par ailleurs. À faire en même temps que le reste du lot 9, pas avant.

### Références résiduelles

| Fichier | Ligne | Quoi |
|---|---|---|
| `ml/tests/test_verdict_anchors_scope.py` | `:35` | `"review/publish_cli.py"` dans la liste de scope |
| `ml/shared/verdict_scope.py` | `:10` | mention de `review/publish_cli.py` en commentaire |
| `ml/eurio_ml.egg-info/` | — | régénéré au build, rien à faire à la main |

### Documentation

| Chemin | Sort |
|---|---|
| `docs/work-in-progress/collaborative-review/` | 11 fichiers — supprimés, supersédés par ce chantier |
| `docs/work-in-progress/auth-redesign/ROADMAP.md` | K2 passe de ⬜ à ✅, pointe ici |
| `docs/work-in-progress/auth-redesign/ARCHITECTURE.md` | §7 « Spec friends review (à statuer plus tard) » — tranché, à réécrire ou supprimer |
| `CLAUDE.md` | §Secrets — la phrase « `infra/review/` reste **en service** » devient fausse |
| mémoire `project_friends_review_deferred` | plus vraie — à retirer |

### Secrets devenus inutiles

`infra/review/secrets/` (`review_admin_token`, `review_session_secret`, les deux clés
MinIO) — pattern Docker secrets déjà déprécié. Vérifier qu'aucun n'est référencé
ailleurs avant suppression.

## Trouvé en revue adversariale le 2026-08-24 — préexistant, à traiter au lot 9

### `GET /review/me/stats` — une seconde définition de « ce que j'ai trié »

`ml/serving/review_routes.py:197`. Elle compte les décisions dans les tables
`decisions` / `review_items` du **tampon `review.db`** — celui que D1 fait
mourir — pendant que `GET /me/review-stats` (accueil d'un ami) compte les mêmes
décisions dans le canonique.

Vérifié : `grep -r "review/me/stats\|review/me/items\|review/claim"` sur
`admin/packages/studio-local/src` → **aucune occurrence**. La route n'a plus
d'appelant, mais elle est toujours montée sur les deux serveurs. Ce n'est pas un
bug aujourd'hui ; c'en devient un le jour où quelqu'un la rebranche et obtient un
autre chiffre pour le même fait.

Part avec le reste du tampon. Tout le bloc `/review/me/*`, `/review/claim`,
`/review/items/*/decide|skip` est dans le même cas.

### `_coin_helpers.canonical_obverse_url` — une TROISIÈME règle pour choisir une image canonique

`ml/serving/_coin_helpers.py:13`. Elle alimente les `canonical_thumb_url` de
l'écran de review (`serving/review_queue/repository.py`), et elle diverge des
deux autres sur deux points :

1. son `CASE` ne connaît que `numista_api` (1) et `bce_official` (2) — les tags
   courts `numista`, `bce_comm`, `unknown` tombent tous dans `ELSE 9`, **non
   départagés**, là où `_lookup_source` les ordonne explicitement ;
2. elle ne lit qu'**une seule ligne** : si la mieux classée n'a ni `url` ni
   `local_path`, elle rend `None` alors qu'une autre ligne porte peut-être une
   image parfaitement chargeable. Les deux autres chemins parcourent tous les
   candidats avant d'abandonner.

`referential_routes` n'a plus qu'une règle depuis le 2026-08-24 (`_candidats` +
`_cle_bucket`, partagés par la route qui SERT l'image et celle qui rend son
ADRESSE). Celle-ci est la dernière qui reste à part. **Non touchée
délibérément** : elle est dans le chemin chaud de l'écran de review, qui marche ;
l'aligner mérite sa propre vérification, pas un passage en marge d'un autre lot.

## Ce qu'on NE supprime pas

- `ml/review/peer_arbitration_routes.py` — **réutilisé** par le lot 8
- `peer_review_decisions` — la table de quarantaine (D7)
- `ml/review/review_queue_routes.py` — le legacy lourd reste la voie locale du Mac
  (recadrage, auto-crop, détection) tant que `:8042` existe

## Garde-fou

⚠️ **Ne jamais `git clean -xdf`** dans ce dépôt : `infra/backup/staging/` contient
6,6 Go de données gitignorées (sur le VPS).
