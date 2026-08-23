# Déploiement et première invitation

> Ce que le chantier change en production, comment le vérifier, et comment se
> donner un compte « ami » pour l'essayer soi-même.

## Avant de déployer — l'état constaté

Mesuré le 2026-08-23, avant tout envoi :

| Contrôle | Résultat |
|---|---|
| VPS joignable, `/opt/eurio` propre | ✅ `repo-cleanup`, arbre sans modification |
| Commit du VPS | `a5143214`, identique au local avant ce chantier |
| `peer_review_decisions` en prod | **0 ligne**, **0 doublon pending** → la migration 0012 s'applique sans heurt |
| `users` en prod | 1 seul (`raphaelthi59@gmail.com`), rôles `owner` + `admin` + `reviewer` |
| `crop_url` servi par la prod | `/sources/ebay/assets/…/file` — **relatif**, donc mort à distance |

Ce dernier point est le témoin le plus simple : après déploiement il doit devenir
une URL MinIO absolue. C'est le contrôle avant/après du lot 1.

## Ce que le déploiement change

- **Un bug de production disparaît** : `check_same_thread` (lot 1b). Le VPS le porte
  encore — sous concurrence, `/review-queue` répond 500 et le front reste sur
  « chargement de la suite… », sans une ligne en console.
- **Un trou de sécurité se referme** : `peer_arbitration` passe de `review:write` à
  `review:arbitrate` (lot 4b). Aujourd'hui, un compte `reviewer` pourrait approuver
  ses propres décisions. Non exploitable tant qu'aucun ami n'a de compte — **le
  déploiement doit donc précéder la première invitation**.
- Une migration : **0012**, index unique partiel sur `peer_review_decisions`.

## La procédure

⚠️ **Backend d'abord, front ensuite** (règle de la skill `eurio-vps-deploy`).

⚠️ Le clone du VPS suit encore `codeberg`, qui n'est plus alimenté : un `git pull`
nu y ramène un arbre en retard. Passer explicitement par `github`.

```bash
# 1. Depuis le Mac : pousser vers le dépôt de référence
git push github repo-cleanup

# 2. Sur le VPS
ssh serverOimNixDontpanic
cd /opt/eurio && git fetch github repo-cleanup && git merge --ff-only github/repo-cleanup

# 3. Backend
cd infra/eurio-api && sops exec-env ../../secrets/dev.env "docker compose up -d --build"

# 4. Front hébergé
cd ../eurio-admin && sops exec-env ../../secrets/dev.env "docker compose up -d --build"
```

## Vérifier — dans cet ordre

**1. Les routers montés** — le contrôle le plus informatif :

```bash
docker logs eurio-api 2>&1 | grep -E "routers (montés|skippés)" | tail -2
```

Attendu depuis le lot 6b : les 7 candidats montés **sauf `review_queue`**, et pour
`training` — plus pour `cv2`, qui est désormais dans l'image. C'est normal : son
préfixe reste servi par `serving.review_queue`, y compris le recadrage
(`crop_routes`). Si `referential` réapparaît dans les skippés, la dette Pillow est
revenue.

⚠️ Le boot ÉCHOUE désormais si un router est monté sans scopes déclarés
(`_ROUTER_SCOPES`, lot 4b). Un conteneur qui ne démarre pas après ajout d'un router
n'est pas une régression : c'est le garde-fou.

**2. La migration 0012 est passée** :

```bash
docker logs eurio-api 2>&1 | grep db_migrate | tail -2
```

**3. Le témoin du lot 1 — les crops sont absolus** :

```bash
sops exec-env secrets/dev.env 'curl -s -H "Authorization: Bearer $EURIO_API_TOKEN" \
  "https://eurio-api.musubi.dev/review-queue?limit=1&lane=manual"' | head -c 200
```

Attendu : `"crop_url": "https://eurio-s3.musubi.dev/enrichment-crops/…"`.

**4. L'image se charge vraiment** — l'API peut répondre 200 avec une URL
parfaitement formée que le navigateur ne résout pas (piège `MINIO_PUBLIC_ENDPOINT`) :

```bash
curl -s -o /tmp/c.png -w "%{http_code} %{size_download}\n" "<crop_url renvoyé>"
file /tmp/c.png     # doit dire « PNG image data »
```

## Fait le 2026-08-23 — ce que les contrôles ont donné

Déployé au commit `419ed6c6` (7 commits), backend puis front.

| Contrôle | Résultat |
|---|---|
| Migration 0012 | ✅ `applied 1 migration(s)` |
| Boot | ✅ `serve-role prêt … auth=True` — donc les 7 routers ont bien leurs scopes déclarés |
| Routers montés | `coin_assets, coins, sets, operations, peer_arbitration` |
| Routers skippés | `referential` (PIL), `review_queue` (cv2) — **préexistant**, ces modules n'ont pas été touchés |
| **`crop_url`** | `/sources/…/file` → **`https://eurio-s3.musubi.dev/enrichment-crops/…`** |
| L'image se charge vraiment | ✅ HTTP 200, 67 017 octets, `PNG image data, 224 x 224` — depuis l'extérieur, sans en-tête d'auth |
| Suggestions DINO | ✅ `dinov2-vitl14 / 2eur_all`, `duration_ms: 0` (lu en base), 5 candidats, seuils d'abstention servis |
| Front hébergé | ✅ 200 ; `review:arbitrate` et « disponible uniquement en local » présents dans les chunks `SingleReviewView`, `LotDetailView`, `ReviewPage` |

### Sur les deux routers skippés

Un routeur skippé **ne veut pas dire que son préfixe est absent** : `/review-queue/*`
reste servi par `serving.review_queue`, monté au niveau module. Ce que la prod perdait,
ce sont les routes LOURDES de ce préfixe (`detect`, `manual-crop`, `crop-edit-context`).

`referential` était skippé faute de `PIL`. Conséquence théorique : le repli relatif
`/referential/canonical/{id}/obverse` répond 404. Mesuré alors — **il ne se déclenchait
jamais** : les 689 pièces du référentiel ont toutes une URL canonique externe absolue.

**Les deux points ci-dessus ont été soldés au lot 6b** (2026-08-23 au soir) :
`manual-crop` et `crop-edit-context` sont servis par le canonique, et `referential`
est monté. Ne reste skippé que `review_queue` legacy, pour `training` — ce qui est
la situation voulue.

## ⚠️ Ta session sera périmée — et c'est voulu

`review:arbitrate` n'existait pas quand ta session a été ouverte. Les scopes d'un
cookie sont figés au login ; ils ne se mettent pas à jour tout seuls.

Conséquence immédiate : **ta première décision après déploiement sera refusée**, avec
un 409 qui dit quoi faire — « Session périmée … déconnecte-toi et reconnecte-toi ».
C'est délibéré : l'alternative aurait été de détourner tes décisions en quarantaine
sans te le dire (cf. la revue, constat n°2).

**Remède : se déconnecter puis se reconnecter.** La session dure 8 h, donc le
problème disparaît de lui-même au plus tard le lendemain.

Même chose pour le PAT local (`EURIO_API_TOKEN`) : les scopes d'un jeton sont figés à
l'émission. Sans régénération, tes décisions depuis `go-task front:dev` partiront en
quarantaine — avec un WARNING serveur explicite, pas en silence.

## Se donner un compte « ami » pour tester

Ton compte porte les trois rôles, donc il a `review:arbitrate` : **tu ne peux pas
vivre l'expérience d'un ami avec ton propre compte** sur le front hébergé. Il faut un
second utilisateur.

Le mapping est direct (`serving/auth_oidc.py`) :

| Groupe Authentik | Rôle Eurio |
|---|---|
| `eurio-owner` | `owner` |
| `eurio-admin` | `admin` |
| `eurio-reviewer` | `reviewer` |

Dans l'interface d'administration d'Authentik :

1. créer l'utilisateur (par exemple `paolo`) et lui poser un mot de passe ;
2. l'ajouter au **seul** groupe `eurio-reviewer` — s'il est aussi dans `eurio-admin`,
   il arbitrera et la quarantaine ne se déclenchera pas ;
3. lui envoyer `https://eurio-admin.musubi.dev`.

Au premier login, `eurio-api` crée la ligne `users` et ses `user_roles` tout seul
(`upsert_user_and_sync_roles`) — rien à faire côté base.

**Ce que tu dois voir avec ce compte** : la nav réduite à Tableau de bord · Pièces ·
Besoin · Review queue · Pêche, et les décisions qui atterrissent en quarantaine :

```bash
ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
import sqlite3
c=sqlite3.connect(\"file:/var/lib/eurio/eurio.db?mode=ro\",uri=True); c.row_factory=sqlite3.Row
print([dict(r) for r in c.execute(
  \"select reviewer_name, action, arbitration_status from peer_review_decisions \"
  \"order by decided_at desc limit 5\")])"'
```

Si tu y vois des lignes `pending`, la boucle complète fonctionne : l'ami a tranché,
le canonique n'a pas bougé, et il te reste à arbitrer.

La vue d'arbitrage en lot existe depuis le lot 8 : **`/review/arbitrage`**, carte
III du tableau de bord ou entrée « Arbitrage » de la nav (sous `review:arbitrate`,
donc invisible à l'ami). La page unitaire `/review/peer-arbitration` reste servie
en attendant que la vue en lot soit éprouvée (suppression inscrite au lot 9).

## Second déploiement — 2026-08-23 au soir (`071312d9`)

D11 + lot 8 + lot 6b, backend puis front. Ce que les contrôles ont donné :

| Contrôle | Résultat |
|---|---|
| Migrations | ✅ `no pending migration (12 already applied)` |
| Boot | ✅ `serve-role prêt … auth=True` |
| **Routers montés** | `coin_assets, coins, sets, operations, **referential**, peer_arbitration` |
| Routers skippés | `review_queue` seul — et **pour `training`**, plus pour `cv2` |
| **`referential` n'est plus skippé** | ✅ la dette PIL est soldée (lot 6b) |
| Routes du lot 8 | ✅ `/peer-arbitration/approve-batch` et `/reject-batch` dans l'OpenAPI |
| `GET /peer-arbitration` | ✅ 200, `{"items":[],"total":0,…}` — la pagination répond |
| Routes du lot 6b | ✅ `/review-queue/{id}/crop-edit-context` **et** `/coins/assets/{id}/…` |
| **Contexte de recadrage servi par la prod** | ✅ URLs MinIO présignées ; le raw se charge vraiment depuis l'extérieur (HTTP 200, 172 331 octets, JPEG 960×720) |
| Front | ✅ 200 ; `ArbitrageBulkPage`, `useHeavyGate` et la variante neutre de `LocalOnlyNotice` présents dans les chunks |

⚠️ **Ce que ce déploiement ne prouve PAS** : qu'un recadrage ÉCRIT correctement.
La lecture est vérifiée de bout en bout, l'écriture ne l'est pas — elle écrase
l'objet MinIO en place (D9) et demande qu'un humain choisisse le cercle. C'est le
point 3 de la recette dans [`REPRISE.md`](REPRISE.md).

### Le témoin qui a changé de sens

Au premier déploiement, le témoin était `crop_url` : relatif avant, absolu après.
Ici c'est **la liste des routers skippés** : `referential` en est sorti. Un router
skippé ne fait pas d'erreur — il se contente de ne pas exister, et ses routes
répondent 404 sans que rien ne le dise. C'est la première ligne à lire après un
build, avant même de tester une route.
