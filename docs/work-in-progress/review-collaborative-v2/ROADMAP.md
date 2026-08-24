# Roadmap — review collaborative v2

> Statut tenu à jour à chaque lot. Un lot n'est ✅ que **vérifié en base ou dans
> MinIO** — jamais sur un 200 HTTP (cf. skill `eurio-verify`).

| Lot | Objet | Statut |
|---|---|---|
| 0 | Document de chantier | ✅ 2026-08-23 |
| 1 | Les crops visibles à distance | ✅ **vérifié au navigateur** |
| 1b | `check_same_thread` — bug de prod trouvé en chemin | ✅ **vérifié** (8/8 en concurrence) |
| 2 | Signer les décisions | ✅ **vérifié en base** |
| 3 | La quarantaine (`review:arbitrate`) | ✅ **vérifié au navigateur** |
| 4 | Nav filtrée par scope | ✅ **vérifié au navigateur** |
| 4b | Durcir les routers montés sans scope | ✅ **vérifié en conditions réelles** |
| 5 | Page review taillée pour un ami | ✅ **vérifié au navigateur, 2 profils** |
| 6a | `dino-suggestions` en lecture pure sur le lean | ✅ **vérifié au navigateur** |
| D11 | Ne plus rien montrer de « local » à un ami | ✅ **vérifié au DOM, 2 profils** |
| 8 | La vue bulk d'arbitrage | ✅ **vérifié en base** (65 approuvées, 3 rejetées) |
| 6b | Le recadrage à distance (cv2-headless) | 🟡 **déployé et vérifié en lecture** — l'écriture MinIO se joue à la recette |
| 7 | Le bail sur la file | ⬜ — **à mesurer avant de dimensionner** (§lot 7) |
| 9 | Full clean | ⬜ |

> **Déployé en production le 2026-08-23**, deux fois : d'abord les lots 0-6a, puis
> D11 + 8 + 6b au commit `071312d9`. Résultats des contrôles :
> [`DEPLOIEMENT.md`](DEPLOIEMENT.md). Reprise et recette :
> **[`REPRISE.md`](REPRISE.md)**.

## D11 — fait (2026-08-23)

La règle de rendu vit maintenant dans **un seul endroit**,
`shared/composables/useHeavyGate.ts` :

```
showHeavyGesture = canRunHeavy || canArbitrate
```

Grisé pour l'arbitre (son poste, il sait ce qu'est `:8042` et il peut y aller),
**absent** pour un ami. Les deux axes du lot 5 restent distincts ; ce qui change,
c'est le RENDU du second quand la machine ne peut pas.

Six endroits corrigés : la nav (les entrées lourdes ne sont plus proposées), les
routes lourdes (`LocalOnlyNotice` a désormais deux rendus, technique et neutre),
la **carte AUTO-ACCEPT du tableau de bord** — la cause exacte du défaut —, les
gestes lourds de la review single et de la vue de lot, et sur `/besoin` la moitié
ACHETER (qui lit `eurio.local.db`).

⚠️ **Un gate périmé trouvé en chemin** : `/besoin` barrait le geste « pêcher » à
qui n'a pas l'API ML, avec une infobulle qui parlait d'un port et d'un Mac. Or
`/review/peche` n'est plus lourde depuis le lot 1. Le gate barrait donc à un ami
— et à lui seul — la file que cette page venait de lui désigner. Dégaté.

### Vérifié au DOM, deux profils, ML sur port mort

| Profil ami (PAT restreint) | Profil arbitre (PAT complet) |
|---|---|
| 0 occurrence de « local », `:8042`, ou d'un nom de machine | Auto-crop et Recadrer **grisés** avec leur infobulle |
| nav à 5 entrées (Tableau de bord · Pièces · Besoin · Review queue · Pêche) | nav complète, pastilles « local » sur les items lourds |
| une seule carte au tableau de bord (Queue manuelle) | trois cartes (dont AUTO-ACCEPT et Arbitrage) |
| `/review/auto-accept` en direct → « Cette page n'est pas disponible » | même URL → la notice technique avec `go-task ml:api` |
| `/besoin` : pas de panneau ACHETER, 200 liens « pêcher » vivants | panneau ACHETER présent |

## Lot 8 — fait (2026-08-23)

Page `/review/arbitrage` (`ArbitrageBulkPage.vue`), plus une carte **III —
Arbitrage** au tableau de bord (le CSS `.card-indigo` l'attendait depuis toujours)
et une entrée de nav sous `review:arbitrate`.

**Le tri est fait en SQL**, pas côté client : trié page par page, il ne survivrait
pas au scroll infini — la page 2 rejouerait des concordances déjà vues et
laisserait des désaccords derrière. `ORDER BY concords, decided_at, id`.

**Trois états, pas deux.** `dino_state` vaut `concords` | `disagrees` | `absent` :
un SILENCE de DINO appelle le même geste qu'un désaccord (ne pas cocher) mais ne
se lit pas pareil à l'écran. Les deux passent devant.

⚠️ **Contre quelle banque DINO l'accord se mesure-t-il ?** Contre celle du
**VERDICT** (`dinov2-vits14` / `2eur_commemo`) — c'est-à-dire exactement la
prédiction que l'écran de l'ami étiquette `DINO`, et celle sur laquelle repose le
chiffre de D8 (67,3 % avec le re-rank pays). Pas contre la banque des
**SUGGESTIONS** (`dinov2-vitl14` / `2eur_all`), qui alimente le panneau du même
nom et le tri de la pêche. Les confondre ferait lire « DINO d'accord » sur la foi
d'un modèle que personne n'a vu. Mesuré sur les 82 décisions du rig : 71 concordent
avec le verdict, 1 seule avec les suggestions — les deux banques ne disent pas la
même chose, et le tri de D8 changerait du tout au tout selon celle qu'on lit.

Back : `_approve_one` extrait du handler unitaire (une seconde implémentation de
l'écriture canonique aurait dérivé sans que rien n'échoue), `approve-batch` et
`reject-batch` bouclent dessus, **chaque décision dans sa propre transaction** —
un 409 « déjà arbitrée » est un cas normal, pas une panne, et ne doit pas emporter
les 99 autres.

**`reject-batch` n'est pas un confort** : sans lui, ce que l'arbitre décoche reste
`pending`, donc hors de la file pour toujours — le crop disparaîtrait sans que
personne ne l'ait tranché.

### Vérifié EN BASE, pas sur un 200

Rig : 82 décisions posées **par l'API avec le jeton d'un ami** (pas par SQL), puis
65 approuvées en un geste depuis l'UI.

| Contrôle | Résultat |
|---|---|
| `review_queue` des approuvées | `status=done`, `decision_engine_version=peer@v1` |
| Qui a tranché | `decided_by` = l'ami, jointure `users` OK sur les 65 |
| Le canonique | `training_eligible=1`, `resolution_status=manual`, `eurio_id` = sa décision (65/65) |
| Les non approuvées | 17 toujours `pending`, `review_queue.status=open`, `decided_by NULL` |
| Rejet en lot (3) | `status=open`, `training_eligible=0`, `eurio_id NULL` — canonique intact |
| **Les rejetées reviennent dans la file** | **3/3 servies par `GET /review-queue`** (0/3 avant le rejet) |
| Un ami sur `approve-batch` / `reject-batch` | **403** · l'arbitre : 200 |

9 tests neufs (`test_peer_arbitration_bulk.py`).

## Lot 6b — déployé (2026-08-23)

`opencv-python-headless` + numpy dans l'image ; `vision/` et `sources/` copiés
pour `_crop_mask_resize_float` (LE format de prod) et `phash`.

**Ce qui débloquait vraiment l'affaire n'était pas cv2.** Le CONTRAT du recadrage
(trois modèles pydantic + l'habillage) vivait dans `review/review_queue_routes` :
l'importer traînait `sources.ebay`, `review.validation` et leur suite. Extrait
dans `serving/crop_edit_api.py`. Du coup `coin_assets_routes` enregistre enfin ses
propres routes de recadrage sur le lean, en plus du nouveau
`serving/review_queue/crop_routes.py`.

Scope `review:write` : **recadrer n'est pas arbitrer**. C'est la DÉCISION qui part
en quarantaine, pas le cadrage — et le cadrage prend effet tout de suite (D9).

**DINO à réencoder** : après un recadrage sans encodeur, les prédictions du
cadrage d'AVANT sont marquées `stale_since` (migration 0013) — servies quand
même, et annoncées comme telles à l'écran. `backfill_dino_predictions` les traite
comme absentes, donc `go-task ml:dino-predictions:backfill` les recalcule sans
`--force` ni commande neuve, et le ré-encodage lève le marqueur.

> ⚠️ Le premier jet SUPPRIMAIT ces prédictions — « le marqueur EST l'absence »,
> sans colonne ni table. Réfuté le soir même par l'usage : cf. l'amendement
> ci-dessous, et D6.

**Dette soldée** : `referential` n'est plus skippé sur le VPS. L'import Pillow est
descendu dans `encode_webp`, le seul à en avoir besoin — l'API, elle, ne demandait
à ce module que des helpers de CHEMIN. Boot du 2026-08-23 :
`routers montés : [… 'referential', 'peer_arbitration']`.

### Amendement du soir même : la suggestion DINO ne disparaît plus

Le marquage par SUPPRESSION a tenu une demi-journée. Première vraie session de
review, le PO : *« je commence toujours par faire le recadrage et après je pick
la bonne pièce. Souvent, la suggestion de Dino de base est bonne. »*

Migration **0013** (`stale_since`) : la prédiction reste servie, datée comme
périmée ; `DinoSuggestions.vue` affiche « calculée avant ton recadrage » ;
`_existing_keys` la traite comme absente donc le backfill la réencode **sans
`--force`** ; l'upsert remet la colonne à NULL — fraîche parce que RECALCULÉE.

⚠️ **Le piège que 32 tests ont attrapé** : un `ALTER TABLE ADD COLUMN` doit être
doublé d'un `_ensure_column` dans `store/connection.py`. Sur une base ANTÉRIEURE,
`CREATE TABLE IF NOT EXISTS` ne rajoute pas la colonne, et l'index partiel de
`schema.sql` qui la référence échoue en « no such column » **avant que quoi que
ce soit d'autre tourne**. Exactement le patron déjà écrit pour `run_id` (0004)
sur cette même table — la deuxième fois qu'il mord.

### Vérifié — et ce qui reste à vérifier

✅ 8 tests (format 224 de prod, géométrie et phash en base, écrasement sur la MÊME
clé MinIO, cercle hors raw en 422, attribution NON touchée, prédiction périmée
supprimée sous `ImportError`, routes montées sur le lean **et pas deux fois**,
contrat sans import lourd, `referential` importable sans Pillow).

✅ Rig, ML sur port mort : l'éditeur de cercle s'ouvre **avec un jeton d'ami**, le
raw se charge (960 px, HTTP 200 depuis l'extérieur) — servi par le seul canonique.

✅ Production : `/review-queue/{id}/crop-edit-context` répond des URLs MinIO
présignées qui se chargent réellement de l'extérieur.

🟡 **Ce qui manque pour passer le lot en ✅ : un vrai recadrage contre le VPS**,
puis vérifier que l'objet MinIO a changé et que `detection_method` vaut `manual`.
Volontairement laissé à la recette : un recadrage **écrase l'objet en place**
(D9), et choisir un cercle au hasard depuis un rig abîmerait une vraie image de
production. C'est au PO de désigner un crop qui en a besoin.

## Revue du 2026-08-24 — 7 constats, dont 2 bloquants

Une revue de code sur `c79bef82..HEAD` (D11 + lots 8 et 6b + le correctif
d'usage). Les deux bloquants passaient à travers **la suite complète ET le
typecheck** — c'est ce qui les rend intéressants.

| # | Constat | Pourquoi c'était muet |
|---|---|---|
| 1 | `SingleReviewView.vue` : `type="button""`, une guillemet en trop posée avec le `v-if` de D11 | Le compilateur SFC rend **0 erreur** et émet un attribut dont le NOM est une guillemet. Au montage, `setAttribute('"', '')` lève `InvalidCharacterError` → l'écran de review ne rend plus. Et le bouton n'existe que pour l'ARBITRE : la recette côté ami ne pouvait pas le voir |
| 2 | `stale_since` n'était jamais levé par un ré-encodage | Le correctif n'était que dans `auto_validate._flush`, branche `store is None` — **du code mort en prod**. Les deux vrais chemins passent par `store/dino.py`. Résultat : bandeau « calculée avant ton recadrage » à vie sur une prédiction fraîche, et réencodage sans fin du même crop |
| 3 | Le canonique était réécrit sur une décision `superseded` | Le commentaire disait « on annule le reste », le code écrivait `image_assets` AVANT le garde puis committait. La classe du PAIR partait à l'entraînement pendant que `review_queue` gardait la décision LOCALE |
| 4 | Un recadrage pouvait décrire un objet MinIO inexistant | L'échec d'upload était avalé (`minio_ok=False`), la géométrie écrite quand même, 200 rendu — et `minio_ok` n'était lu **nulle part** côté front |
| 5 | La vue bulk servait une `canonical_url` potentiellement relative | Résolue contre le nginx statique → 404. Latent : 0 pièce sur 1235 aujourd'hui |
| 6 | « DINO en désaccord » sur un REFUS | `concords` y vaut 0 par construction : il n'y a rien à comparer |
| 7 | La nav clignotait au boot | Le filtre D11 s'appliquait avant que `/me` réponde |

### Ce que le n°2 enseigne, et qui vaut plus que le correctif

Le test censé le verrouiller était :

```python
source = (ML_DIR / "sources/_base/steps/auto_validate.py").read_text()
assert "stale_since            = NULL" in upsert
```

Un `grep` sur un fichier. Il était **vert**, sur une branche qui ne tourne
jamais. Le catalogue d'`eurio-verify` a un nom pour ça : *un garde posé, testé,
muté — et jamais appelé*. Remplacé par deux tests qui passent par
`store.upsert_dino_predictions` et `apply_ingest_dino`, et **vérifiés A/B** :
ils échouent tous les deux quand on retire le correctif.

La règle qui en sort : **un test qui lit du code au lieu de l'exécuter ne prouve
rien sur le chemin de production.** Il prouve qu'une chaîne de caractères existe
quelque part.

### Et le n°1 : ce que `vue-tsc` ne regarde pas

`vue-tsc --noEmit` ne valide pas les noms d'attributs statiques d'un template, et
`compileTemplate` accepte silencieusement `type="button""`. Aucun outil de la
chaîne ne le voyait. Le contrôle qui l'aurait attrapé tient en trois lignes :
compiler le SFC et chercher un nom d'attribut illégal dans le code émis —
c'est ainsi que le correctif a été prouvé, dans les deux sens.

## Le rig de vérification (à réutiliser à chaque lot)

Il reproduit le mode hébergé **sans rien déployer** : l'app LEAN du VPS tourne en local
contre une **copie** de la réplique, et l'API ML pointe sur un port mort.

```bash
# 1. copie cohérente de la réplique (jamais la réplique elle-même : server_serve écrit)
python -c "import sqlite3;s=sqlite3.connect('file:ml/state/eurio.replica.db?mode=ro',uri=True);d=sqlite3.connect('/tmp/lean.db');s.backup(d)"

# 2. l'app LEAN (celle du VPS), pas serving/server.py
cd ml && EURIO_DB_PATH=/tmp/lean.db EURIO_DB_READONLY= EURIO_API_AUTH_REQUIRED=1 \
  EURIO_API_CORS_ORIGINS="http://localhost:5174" \
  MINIO_PUBLIC_ENDPOINT=eurio-s3.musubi.dev MINIO_PUBLIC_USE_SSL=true \
  ./.venv/bin/python -m uvicorn serving.server_serve:app --host 127.0.0.1 --port 8043

# 3. le front, ML sur un port MORT — c'est ça qui prouve l'indépendance au Mac
cd admin/packages/studio-local && VITE_EURIO_PAT="<pat>" \
  VITE_EURIO_API_BASE=http://127.0.0.1:8043 VITE_ML_API=http://127.0.0.1:9 \
  ./node_modules/.bin/vite --port 5174 --strictPort --force
```

Pièges rencontrés, tous coûteux :

- **`serving/server.py` ≠ `serving/server_serve.py`.** Le layered `review_queue/` n'est
  monté QUE par le lean. Tester sur `:8042` n'exerce pas le code du VPS.
- **Le PAT est injecté au TRANSFORM**, et vite le met en cache : sans `--force`, le
  bundle sert l'ancien jeton en silence. Vérifier :
  `curl -s localhost:5174/src/shared/api/eurio-api.ts | grep -o 'eurio_[A-Za-z0-9_-]\{14\}'`
- **`pkill -f "vite --port 5174"` ne matche rien** : la ligne de commande réelle est
  `vite.js --port 5174`. Le vieux serveur survit et on lui parle sans le savoir.
  Tuer par PID (`lsof -nP -iTCP:5174 -sTCP:LISTEN`).
- **Cloudflare renvoie `error code: 1010`** sur une URL MinIO présignée demandée par
  `urllib` : c'est un blocage de user-agent, PAS une signature invalide. Rejouer avec
  un UA de navigateur avant de conclure.
- **Un PAT restreint se pose dans la COPIE** (`pat_tokens`), jamais en prod : les scopes
  effectifs étant `jeton ∩ rôles`, on obtient exactement l'expérience d'un ami (D7).

---

## Lot 1 — Les crops visibles à distance ⇦ débloque tout le reste

`ml/serving/review_queue/repository.py` — les `crop_url=f"/sources/…/file"` (`:407`,
`:790`, `:1632`) deviennent des URLs MinIO présignées, comme le fait déjà
`review_routes.py:61` (`signed_url("enrichment-crops", storage_path)`). Idem vignettes
canoniques.

Rien à changer côté front : `promoteUrl` laisse passer les URLs absolues
(`url.startsWith('http')`).

**Vérif.** Front lancé avec `VITE_ML_API` sur un port mort → les crops s'affichent
quand même. C'est le test qui prouve que plus rien ne dépend du Mac.

## Lot 1b — `check_same_thread` (bug de prod trouvé en vérifiant le lot 1)

`serving/deps.py` ouvrait la connexion sans `check_same_thread=False`. FastAPI exécute
une dépendance génératrice **synchrone** dans un worker du threadpool
(`contextmanager_in_threadpool`) puis la route dans un **autre** worker
(`run_in_threadpool`) : la connexion change de thread, et sqlite3 refuse.

Pourquoi ça n'avait jamais explosé : anyio réutilise souvent le même worker quand le
serveur est au repos. Un test séquentiel passe (6/6 en prod), le navigateur casse — il
tire `/review-queue` et `/review-queue/stats` en même temps.

**Panne parfaitement muette** : le front reste sur « chargement de la suite… », zéro
ligne en console, et le 500 ne vit que dans les logs serveur.

Vérif : 8 requêtes simultanées → 8× 200. Avant le correctif, le navigateur prenait un
500 à chaque chargement.

⚠️ **Le VPS porte encore le bug** — le correctif n'y sera qu'au prochain déploiement.

## Lot 2 — Signer les décisions

`decided_by = 'admin'` → `principal.user_id` dans `serving/review_queue/writes.py`
(`decide`, `reject`, `restore`) et dans les `detail_fields` d'`emit_state_event`.

Les 3 809 lignes existantes restent `admin` : on ne réécrit pas l'histoire.

## Lot 3 — La quarantaine

Scope `review:arbitrate` ajouté à `owner` et `admin` (`auth_principal.py:33`). Dans
`decide` / `reject` : si le principal ne l'a pas → `peer_review_decisions` en `pending`,
sans toucher `review_queue` ni `image_assets`. La table existe déjà (`reviewer_token`
accueille `users.id`, pas de FK).

**Vérif.** Avec un PAT restreint (cf. D7), trancher un crop puis :
```sql
SELECT reviewer_token, arbitration_status FROM peer_review_decisions
 ORDER BY decided_at DESC LIMIT 5;
```
→ la ligne est `pending` et `review_queue` n'a pas bougé.

### Ce que les lots 2 et 3 ont donné, vérifié

Scénario joué sur le rig, jeton par jeton :

| Geste | Attendu | Obtenu |
|---|---|---|
| Ami tranche (`decide`) | `pending_arbitration`, canonique intact | ✅ `status=open`, `decided_by=NULL`, `training_eligible=0` |
| La quarantaine | une ligne `pending` avec le nom | ✅ `authentik Default Admin · accept · pending` |
| Le crop en quarantaine | sort de la file | ✅ absent des 200 items servis |
| Deuxième décision sur le même crop | 409 | ✅ 409 |
| `restore` avec un jeton reviewer | 403 | ✅ 403 |
| Arbitre tranche | écriture directe + signature | ✅ `status=done`, `decided_by=e51955657a…`, `training_eligible=1` |
| Bout en bout depuis l'UI | l'ami décide, l'écran avance | ✅ ligne en quarantaine, canonique intact, crop suivant affiché |

Et « qui a validé quoi » devient une jointure :

```sql
SELECT u.name, u.email, count(*) FROM review_queue rq
  JOIN users u ON u.id = rq.decided_by GROUP BY 1,2;
-- authentik Default Admin | raphaelthi59@gmail.com | 1
```

Couvert par `ml/tests/test_review_quarantine.py` (11 tests) : le canonique intact,
la ligne signée, le 409 du doublon, le skip non mis en quarantaine, le 403 sur
`restore`, l'écriture directe de l'arbitre, la jointure `users`, et l'exclusion de la
file — y compris le retour du crop dans la file quand l'arbitrage rejette.

### ⚠️ Piège de déploiement : les identifiants antérieurs

`review:arbitrate` n'existait pas quand les PAT actuels ont été émis. Les scopes
effectifs valant `jeton ∩ rôles`, **un jeton ne gagne jamais un scope tout seul** —
c'est voulu. Conséquence immédiate et contre-intuitive : avec son PAT actuel,
**Raphaël lui-même est traité comme un ami** et ses décisions partent en quarantaine.

- **En hébergé, aucun problème** : le cookie OIDC recalcule les scopes depuis les rôles
  à chaque login (`auth_routes.py:206`, `sign_session_cookie(scopes=principal.scopes)`).
- **En local (PAT)** : régénérer le PAT après déploiement.

La bascule ne peut pas être silencieuse : un principal qui porte le rôle `owner`/`admin`
sans le scope ne peut être qu'un identifiant périmé, et `writes.py` le journalise en
WARNING avec le remède. Vérifié :

```
WARNING [review] principal e51955657a… a le rôle ['admin','owner','reviewer'] mais PAS
le scope review:arbitrate — identifiant périmé (api_token). Ses décisions partent en
QUARANTAINE. Remède : se reconnecter, ou régénérer le PAT.
```

### À trancher au lot 5

Le front ignore le corps de la réponse (`decideReviewItem: Promise<void>`), donc l'ami
ne voit PAS que sa décision est en attente — l'écran défile normalement. C'est peut-être
mieux ainsi (« sans les fliquer »), mais c'est un choix produit, pas un oubli : le
serveur renvoie déjà `{"status": "pending_arbitration", "pending": "true"}` si on veut
l'afficher.

## Lot 4 — Nav filtrée par scope

`app/nav.ts` : `scope?: string` sur `NavItem`. `AppLayout.vue` filtre via
`session.hasScope` (`stores/eurio-session.ts:49`, déjà écrit).

Retirer `meta: heavy` des routes review que le lot 1 a libérées (`/review`,
`/review/manual`, `/review/peche`, `/review/lot/:key`) ; le garder sur l'éditeur de
crop jusqu'au lot 6.

## Lot 4b — Durcir les routers montés sans scope ✅

`server_serve.py` montait les routers de `_CANDIDATES` avec `require_principal` —
**tout principal authentifié**, sans scope. Le filtrage de nav du lot 4 cachait les
pages à un ami ; il pouvait encore les appeler à la main.

### Le trou grave, ouvert par la quarantaine elle-même

`peer_arbitration` exigeait `review:write` — que le rôle `reviewer` **possède**. Donc
un ami pouvait appeler `POST /peer-arbitration/{id}/approve` sur **sa propre** décision
en quarantaine et la pousser dans le canonique. La quarantaine du lot 3 était
contournable en un appel.

Vérifié en conditions réelles avant correctif, le 2026-08-23 :

```
POST /peer-arbitration/{id}/approve  (jeton reviewer) → 200
SELECT arbitration_status …                           → approved
```

### La forme retenue : une garde par VERBE

Tous ces routers mélangent lecture et écriture (`coins_routes` : 17 GET, 1 PATCH,
1 POST, 1 PUT, 1 DELETE). Un scope unique par router serait soit trop lâche pour les
écritures, soit trop strict pour les lectures ; les annoter route par route, c'est une
centaine d'endroits où en oublier un. Le verbe HTTP porte déjà exactement la
distinction que le vocabulaire de scopes encode.

`auth_principal.require_scope_by_method(read, write)` + une table de politique dans
**`serving/router_scopes.py`** — module à part, stdlib pure, *parce qu'une politique
d'accès doit se lire et se tester sans démarrer un serveur* :

| Router | lecture | écriture |
|---|---|---|
| `coins`, `coin_assets`, `sets`, `referential` | `coins:read` | `coins:write` |
| `operations` | `training:run` | `training:run` |
| `peer_arbitration` | `review:read` | **`review:arbitrate`** |
| `review_queue` | `review:read` | `review:write` |
| `recipe_routes` | `lab:read` | `training:run` |

Un router monté sans couple déclaré **fait échouer le boot** — un défaut permissif
rouvrirait le trou en silence le jour où quelqu'un ajoute un router.

### Vérifié, jeton par jeton

| Un ami PEUT | | Un ami NE PEUT PAS | |
|---|---|---|---|
| trancher un crop (→ quarantaine) | 200 | approuver sa propre décision | **403** |
| chercher une pièce (recherche libre) | 200 | modifier le référentiel | **403** |
| lire les suggestions DINO | 200 | lire la télémétrie d'entraînement | **403** |
| suivre où en sont ses décisions | 200 | restaurer un crop rejeté | **403** |

L'arbitre, lui, approuve (200). Verrouillé par `ml/tests/test_scopes_de_montage.py`
(8 tests), dont un qui interdit à quiconque d'ajouter un router sans trancher ses
scopes, et un qui refuse un scope inventé — un scope mal orthographié
n'appartiendrait à aucun rôle et rendrait la route **inatteignable**, panne muette à
l'envers.

### Correction d'un garde-fou posé au lot 3

Le refus « identifiant périmé » se déclenchait sur le **rôle** owner/admin. Il ne
distinguait donc pas un jeton *périmé* d'un jeton *volontairement restreint* — or
c'est exactement le mécanisme de D7 (rejouer un ami depuis un compte owner). Il
bloquait le PAT de test. Le bon discriminant est la **méthode d'authentification** :

- **cookie OIDC** sans le scope → périmé sans ambiguïté (ses scopes viennent des rôles
  au login, il ne peut pas être restreint) → **refus 409** ;
- **PAT** sans le scope → restriction volontaire, légitime → quarantaine + WARNING.
  Son porteur est un développeur devant ses logs, pas un ami devant un écran.

### Hors périmètre, assumé

`serving/server.py` (le ML local sur `127.0.0.1:8042`) monte tout **sans auth** : il
n'est pas exposé, et le durcir casserait toutes les tâches locales qui l'appellent.

La nav reste plus stricte que le serveur sur deux pages en lecture seule (Sets,
Référentiel gatées `coins:write`, lisibles en `coins:read`). C'est la direction sûre :
un ami ne les voit pas, et les lire ne lui apprendrait rien qu'il ne puisse déjà voir
via la recherche de pièces.

À faire : étendre `_SCOPE_OVERRIDES` avec le scope juste pour chaque router, en
séparant lecture et écriture là où le router mélange les deux.

## Lot 5 — Page review taillée pour un ami ✅

### Deux axes, et surtout ne pas les confondre

C'est le point de conception du lot. Les deux gardes répondent à des questions
différentes, et les mélanger serait la vraie dette :

| Axe | Question | Rendu | Ce qu'il gate |
|---|---|---|---|
| **DROIT** — `hasScope('review:arbitrate')` | « cette personne a-t-elle le droit ? » | **absent** | `REQUALIFIER EN LOT`, sélecteur `COHORT`, `AUTO-ACCEPT`, bloc marché, « Pas un lot » |
| **MACHINE** — `capabilities.hasLocalMlApi` | « ce poste peut-il ? » | **grisé + infobulle** | `RECADRER`, `AUTO-CROP`, `Re-détecter`, `Sync crops`, `Crop manuel`, `Éditer le crop` |

La différence de rendu porte le sens : ce qui est **interdit** disparaît, ce qui est
seulement **hors de portée** reste visible et grisé. Un recadrage n'est pas refusé à un
ami — il redeviendra possible pour lui au lot 6b, sans que ses droits changent.

Le grisé + infobulle reprend le motif d'`AppLayout` pour les items de nav lourds ; pas
de `LocalOnlyNotice` inline (ce serait un rendu nouveau au milieu d'une barre de
boutons, donc du design non proto'é — cf. R1).

### Ce qui reste visible pour tous

Crop, canonique, candidats (standards, pièce proposée, top-5 auto-name, suggestions
DINO), recherche libre `F`, Valider/Reject/Skip, compteurs du bandeau, et **le titre du
listing** — souvent ce qui tranche (cas observé : DINO classe premier le mauvais
millésime à 0,732 contre 0,714, le titre dit « 2 EURO **2022** »).

La carte listing se retitre « Listing » au lieu de « Listing & marché » quand le volet
marché est masqué : une section titrée « marché » et vide se lit comme une panne.

### Masquer un bouton ne désarme pas son raccourci

Piège qui aurait tout annulé : `L` (requalifier), `S` (pas un lot), `E` (recadrer) et
`A` (auto-crop) restaient armés derrière les boutons masqués ou grisés. Sans garde, `L`
requalifiait encore un listing entier pour un ami, et `E`/`A` partaient vers un `:8042`
injoignable. Les quatre handlers portent désormais la même condition que leur bouton.

### Vérifié — DOM, pas capture

Leçon du lot 6a appliquée : chaque élément contrôlé un par un via le DOM, sur les deux
profils, plutôt que sur l'apparence d'une capture.

**Profil ami** (PAT restreint aux scopes `reviewer`) :

```
requalifier_en_lot ABSENT   auto_accept ABSENT   cohort_selector ABSENT
bloc_marche_prix   ABSENT   bloc_marche_p50 ABSENT   titre_carte « Listing »
auto_crop GRISÉ   recadrer GRISÉ
validate actif   reject actif   skip actif
titre_listing PRÉSENT   compteurs PRÉSENT   suggestions_dino PRÉSENT
```

Et le geste central marche : clic sur un candidat puis `Validate` → quarantaine de 1 à
2 lignes, `authentik Default Admin · accept · pending`.

**Profil arbitre** (PAT complet) : les cinq éléments de l'axe droit sont de retour
(`requalifier actif`, `auto_accept actif`, `cohort PRÉSENT`, `bloc marché PRÉSENT`,
titre « Listing & marché », « Pas un lot » actif) — **tandis que `auto_crop` et
`recadrer` restent GRISÉS**. C'est la preuve que les deux axes sont indépendants :
tous les droits, mais la machine ne peut toujours pas.

### Le trou trouvé en vérifiant

`LotDetailView` contient **trois** appels à `openRecropActive` (barre compacte, plateau
de détection, barre d'action du crop) et **deux** boutons libellés « Éditer le crop »,
aux infobulles différentes. Le premier passage n'en avait gaté qu'un : le bouton est
resté `ACTIF` au navigateur alors que `hasLocalMlApi` était faux. Repéré parce que la
vérification portait sur l'état réel du DOM, pas sur une capture.

Contre-vérification automatisée après correction, sur le bundle **réellement servi par
vite** (et non le source) :

```
GATÉ Re-détecter · GATÉ Sync crops · GATÉ Crop manuel · GATÉ Éditer/Recadrer ×3
→ 6/6 boutons lourds portent :disabled=…canRunHeavy
```

Plus l'inventaire côté source des deux vues : **8/8 gestes lourds gardés**.

### Décision produit conservée

Le front continue d'ignorer le corps de la réponse de `decide`
(`decideReviewItem: Promise<void>`) : l'ami ne voit pas que sa décision part en
quarantaine, l'écran défile normalement. Demande explicite du PO — ne pas « fliquer »
les amis.

## Lot 6a — `dino-suggestions` en lecture pure sur le lean

Constaté au navigateur : le panneau « SUGGESTIONS DINO » affiche « Pas de prédiction
Dino pour ce crop » alors que l'API en a une. La cause n'est pas la donnée —
`useDinoSuggestions.ts:107` fait un `fetch(\`${ML_API}${path}\`)` **brut**, sans auth,
vers le ML local. Le message d'erreur du front accuse la base ; le coupable est
l'adresse.

Deux moitiés :
- **Front** : `useDinoSuggestions` passe sur `eurioApi` (donc avec l'auth).
- **Back** : la route vit dans le legacy `review/review_queue_routes.py` (import `cv2`
  en tête → skippée sur l'image lean). Extraire la partie LECTURE de
  `_build_dino_response` dans un module stdlib+sqlite partagé, que le legacy garde
  comme cœur et que le layered appelle en 404-si-absent. Pas de duplication.

### Ce que le lot 6a a demandé, et pourquoi

Le bug côté front était le plus court à dire : `useDinoSuggestions.ts` faisait un
`fetch(\`${ML_API}${path}\`)` **brut, sans auth**. Hors de la machine du ML, l'échec
réseau donnait `TypeError` → `null` → le panneau affichait « Pas de prédiction Dino
pour ce crop · hors scope ou pas encore backfillé ». Un message qui accuse la BASE
alors que le coupable était l'ADRESSE — l'API avait bel et bien la prédiction.

Côté serveur, il a fallu porter la route sur l'image lean. Découpage retenu :

| Où | Quoi |
|---|---|
| `shared/listing_titles.py` (neuf) | la regex « lot multi-pays », **déplacée** du legacy — une seule définition, les deux voies l'importent |
| `serving/review_queue/service.py` | `auto_validate_view` (level + reason + critères), `abstention_state`, l'assemblage `dino_suggestions` |
| `serving/review_queue/repository.py` | SQL pur : `dino_prediction`, `verdict_signals`, `consensus_verdict_row`, `enrich_top_k`, `asset_id_for_review` |
| `serving/review_queue/router.py` | 2 routes, déclarées **avant** `/{review_id}` |

⚠️ **`service` importe déjà `repository`** : mettre l'assemblage dans `repository`
aurait créé un cycle ET inversé les couches. Première version écrite comme ça, corrigée.

**Ce que la voie lean ne fait PAS**, délibérément :
- pas d'encodage à la demande quand la prédiction manque → 404 (0 crop concerné sur
  12 823, cf. CONSTAT) ;
- pas de recalcul du consensus depuis les experts (`training.foundation`, numpy/torch)
  → `null`, valeur que le contrat front prévoit déjà ;
- le POST `/dino-suggestions/recompute` reste sur le ML local : il ENCODE.

Vérifié au navigateur, ML sur port mort : `SPREAD 0.087 · NET`, bande « PAYS CIBLE BE ·
38 ANCRES », top-1 `be-2016-2eur-summer-olympics-2016-in-rio-de-janeiro` à 0,794 — la
bonne pièce. Et par l'API : `duration_ms: 0`, donc lu en base.

`ml/tests/test_dino_suggestions_lean.py` (19 tests) verrouille en particulier les deux
divergences qui seraient MUETTES : les seuils lean == ceux de `training.foundation`, et
l'ordre des routes.

## Revue du 2026-08-23 — 8 constats, 6 corrigés

Une revue de code sur le diff complet a trouvé huit choses. Toutes vérifiées avant
d'agir ; six corrigées, deux documentées.

| # | Constat | Sort |
|---|---|---|
| 1 | Le contrat lean perdait `abstention_thresholds` — le front le déréférence **sans garde** quand l'état est `uncertain` → exception de rendu, panneau entier disparu | ✅ champ ajouté + test de la branche `uncertain` + test de couverture du contrat |
| 2 | Un identifiant périmé **détournait les décisions du PO en quarantaine avec un 200** — le front jette le corps, il aurait reviewé une session entière pour rien | ✅ **refusé** par un 409 explicite, plus détourné |
| 3 | `restore` en 403 pour les PAT antérieurs | ✅ conséquence assumée, notée dans le piège de déploiement |
| 4 | Pages dégrisées appelant encore le ML local : recherche libre (`useCoinsSearch`), raws de lot | ✅ recherche libre portée sur eurio-api ; `raw_url` présigné comme les crops |
| 5 | Le fallback de `_crop_url` n'a plus de destination | ✅ docstring corrigée — la promesse « ne peut rien casser » était trop forte |
| 6 | La quarantaine excluait la file mais **pas les compteurs** → bandeau à 4 au-dessus d'une file de 3 | ✅ `NOT_QUARANTINED_SQL` partagé, appliqué aux 4 compteurs + test |
| 7 | Indexation directe des seuils → `KeyError` **à l'import** si l'encodeur des suggestions change | ✅ `defaults_for()` avec son FALLBACK |
| 8 | Course sur la quarantaine : deux décisions `pending`, l'arbitrage en jette une en **`superseded` sans erreur** | ✅ migration 0012, index unique partiel + 409 + 2 tests |

### La leçon du n°1

Ma vérification manuelle du lot 6a était tombée sur un crop `confident`. Le crop
`uncertain` — celui où le panneau sert le plus — n'a jamais été affiché, et c'est
exactement celui qui plantait. **Un screenshot vert ne prouve que la branche qu'il
traverse.** La correction a été revérifiée en rendant incertain le crop servi
(`UPDATE … SET spread = 0.005` sur la copie du rig) : le panneau affiche bien
« Spread 0.005 sous le seuil 0.02 », le `0.02` étant précisément le déréférencement
en cause.

## Lot 6b — Le recadrage à distance

🟡 Déployé le 2026-08-23 — le détail est en tête de ce fichier. Reste **la vérif
d'écriture** : recadrer contre le VPS (pas `:8042`), puis vérifier que l'objet
MinIO a changé et que `detection_method` vaut `manual`. Elle se joue à la recette,
parce qu'un recadrage écrase l'objet en place (D9) et que le cercle doit être
choisi par quelqu'un qui regarde la pièce.

## Lot 7 — Le bail sur la file

`claimed_by` / `claimed_at` sur `review_queue` (migration `db_migrate`) +
`POST /review-queue/claim` (fenêtre de N, TTL 30 min). La logique existe dans
`review_routes.py:100` — la rejouer sur la table canonique. Le 409 de `decide`
(`WHERE status='open'`) reste le filet.

### Ce qui se passe AUJOURD'HUI quand deux amis se marchent dessus

À lire avant de dimensionner le lot : le comportement actuel est **pire que
« le second perd »**, et pour une raison née de la quarantaine elle-même.

`GET /review-queue?limit=20` sert **la même tête de file à tout le monde** : deux
amis connectés en même temps travaillent les mêmes crops, dans le même ordre.
Ensuite, deux garde-fous se déclenchent :

1. `decide` porte `WHERE status='open'` → le second prend un **409** ;
2. l'index unique partiel de la migration 0012 interdit **deux décisions
   `pending` sur le même crop** → 409 aussi, même si le premier n'a pas encore
   été arbitré.

Le second (2) est la nouveauté : avant la quarantaine, la course ne se jouait
qu'au moment où le canonique bougeait. Maintenant, **deux décisions parfaitement
légitimes se disputent la même place**, et la seconde est jetée alors que
personne n'a encore rien validé.

⚠️ **Et le front rend ce 409 hors contexte.** Les décisions partent en *commit
différé* (fenêtre d'undo, `commitPending`) : le POST arrive APRÈS que l'écran a
avancé au crop suivant. En cas de collision, l'ami voit passer un bandeau
« Échec de l'enregistrement… » qui parle d'un crop qu'il a déjà quitté, sans
savoir lequel, ni quoi refaire. Son travail est perdu **et** illisible.

### Le protocole pour le provoquer exprès — sans mobiliser deux personnes

Deux jetons suffisent : la course est côté serveur, pas côté humain.

```bash
# Sur le RIG (jamais en prod) : deux PAT reviewer distincts, même file.
RID=$(curl -s "$API/review-queue?limit=1&lane=manual" -H "Authorization: Bearer $PAT_A" \
      | python3 -c "import json,sys;d=json.load(sys.stdin);print((d['items'] if isinstance(d,dict) else d)[0]['id'])")

# Les deux tranchent le MÊME crop, en parallèle.
for P in "$PAT_A" "$PAT_B"; do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST "$API/review-queue/$RID/decide" \
    -H "Authorization: Bearer $P" -H "Content-Type: application/json" \
    -d '{"eurio_id":"<une classe>","face":"obverse","action":"accept"}' &
done; wait
```

Attendu aujourd'hui : `200` et `409`. Ce qu'il faut MESURER, et qui n'est pas
écrit :

- laquelle des deux gardes a mordu (`status='open'` ou l'index 0012) — la
  réponse change le remède ;
- combien de lignes `peer_review_decisions` existent après (doit être 1) ;
- **au navigateur**, avec deux fenêtres et deux jetons : ce que voit réellement
  le perdant, et à quel moment. C'est la mesure qui décide s'il faut un bail ou
  simplement rendre le 409 lisible.

### La question de conception que ça pose

Un bail (`claim`) empêche la collision, mais introduit un état à expirer, donc un
crop qui peut rester bloqué 30 minutes parce que quelqu'un a fermé son onglet.

L'alternative moins chère : **servir des fenêtres disjointes**. `GET
/review-queue` prend déjà un `offset`-like par le tri ; donner à chaque principal
une tranche décalée réduit la collision à presque rien sans aucun état à
nettoyer. Ça ne la supprime pas — mais avec deux ou trois amis, « presque rien »
et « rien » ont le même goût, et l'un des deux ne s'entretient pas.

À trancher sur la mesure ci-dessus, pas avant.

## Lot 8 — La vue bulk d'arbitrage

✅ Fait le 2026-08-23 — le détail et les mesures sont en tête de ce fichier.

## Lot 9 — Full clean

Voir [`NETTOYAGE.md`](NETTOYAGE.md).

---

## Intervention humaine attendue

Aucune avant le lot 8 — le PAT restreint suffit (D7). Au moment d'inviter le premier
ami : création du compte Authentik + attribution du rôle `reviewer`.

## Déploiement

```bash
cd /opt/eurio && git fetch github repo-cleanup && git merge --ff-only github/repo-cleanup
cd infra/eurio-api && sops exec-env ../../secrets/dev.env "docker compose up -d --build"
```

⚠️ Le clone `/opt/eurio` suit encore `codeberg`, qui n'est plus alimenté — un `git pull`
nu y ramène un arbre en retard.
