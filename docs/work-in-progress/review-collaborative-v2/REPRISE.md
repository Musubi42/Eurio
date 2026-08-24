# Reprise — état au 2026-08-23 (soir), et ce qu'il reste pour clore

> À lire en premier dans une nouvelle session. Le reste du chantier est dans
> [`CONSTAT.md`](CONSTAT.md) (mesures), [`DECISIONS.md`](DECISIONS.md) (D1-D11),
> [`ROADMAP.md`](ROADMAP.md) (lots + rig de vérification et ses pièges),
> [`DEPLOIEMENT.md`](DEPLOIEMENT.md), [`NETTOYAGE.md`](NETTOYAGE.md).

## Où on en est

**La boucle est fermée.** Déployé en production (backend puis front, VPS à jour ;
dernier envoi : les correctifs de la première session de review), et utilisé pour de vrai : le PO a un compte reviewer dans
Authentik et tranche des crops depuis `https://eurio-admin.musubi.dev`.

Livrés et vérifiés : lots 0, 1, 1b, 2, 3, 4, 4b, 5, 6a, **D11**, **8**, et **6b**
(déployé, une vérif d'écriture restant à la recette).

Un ami peut aujourd'hui :

- voir la file, le crop et le canonique, lire les suggestions DINO, chercher une
  pièce librement, **trancher** — sa décision partant en quarantaine sans toucher
  le canonique ;
- **recadrer** un crop mal cadré, à distance, servi par le canonique (lot 6b) ;
- sans jamais voir le mot « local », un numéro de port, ni un bouton mort (D11).

Et le PO peut **relire tout ça en lot** : `/review/arbitrage`, désaccords DINO en
tête et non cochés, approuver ou rejeter en un geste (lot 8).

## Ce qui reste

| Lot | Objet | Pourquoi ce n'est pas urgent |
|---|---|---|
| **6b — la vérif d'écriture** | Un vrai recadrage contre le VPS | **La seule vérification technique en suspens** — cf. la recette ci-dessous |
| **Accueil** | La première minute d'un ami | Pas un lot technique : un chantier de conception, brouillon dans [`ACCUEIL-AMI.md`](ACCUEIL-AMI.md). Rien n'est implémenté, et trois questions doivent être tranchées avant de dessiner |
| 7 | Le bail sur la file (`claimed_by`/`claimed_at`) | Se déclenche au **deuxième ami**. Le comportement actuel est pire qu'on ne croyait — à MESURER avant de dimensionner, protocole dans [`ROADMAP.md`](ROADMAP.md) §lot 7 |
| 9 | Full clean | En dernier, quand tout est prouvé. Il fait tomber `eurio-review.musubi.dev` : inventaire dans [`NETTOYAGE.md`](NETTOYAGE.md), à ne pas jouer un jour de recette |

## Inviter un ami — ce qu'il reste vraiment

**La boucle est déjà parcourue en production** : 12 décisions signées
`eurio-test` sont arrivées en quarantaine, canonique intact, relues dans la vue
d'arbitrage. Ce n'était pas un PAT restreint qui simulait un ami — c'était un
vrai compte Authentik sur le front hébergé.

Il reste donc, techniquement :

1. **créer le compte** dans Authentik, dans le **seul** groupe `eurio-reviewer`
   (s'il est aussi dans `eurio-admin`, il arbitre et la quarantaine ne se
   déclenche jamais) — la ligne `users` se crée seule au premier login ;
2. **un recadrage réel** contre le VPS (point 3 de la recette).

Ce qui retient, ce n'est pas la technique : c'est la **première minute**
([`ACCUEIL-AMI.md`](ACCUEIL-AMI.md)).

## La recette, à jouer ensemble

1. **L'ami** se connecte sur `https://eurio-admin.musubi.dev` avec le compte
   reviewer et tranche une dizaine de crops — dont au moins un qu'il **recadre**
   et un où il **contredit DINO** via la recherche libre `F`.
   → Rien de « local » ne doit apparaître. Aucun port. Aucun bouton mort.

2. **Vérifier en base** que le canonique n'a pas bougé et que les lignes sont
   `pending` :
   ```bash
   ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
   import sqlite3
   c=sqlite3.connect(\"file:/var/lib/eurio/eurio.db?mode=ro\",uri=True); c.row_factory=sqlite3.Row
   print([dict(r) for r in c.execute(
     \"select reviewer_name, action, arbitration_status from peer_review_decisions \"
     \"order by decided_at desc limit 10\")])"'
   ```

3. **Le recadrage — la vérif qui manque au lot 6b.** Sur le crop recadré, vérifier
   que l'objet MinIO a bien changé et que la géométrie a suivi. Relever l'ETag
   AVANT le recadrage pour que la comparaison veuille dire quelque chose :
   ```bash
   # avant : ETag + bbox
   ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
   import sqlite3
   c=sqlite3.connect(\"file:/var/lib/eurio/eurio.db?mode=ro\",uri=True); c.row_factory=sqlite3.Row
   print([dict(r) for r in c.execute(
     \"select id, storage_path, detection_method, bbox_json, width, height \"
     \"from image_assets where id = ?\", (\"<asset_id>\",))])"'
   mc stat eurio/enrichment-crops/<storage_path>   # ETag + taille avant
   # … recadrer dans l'UI …
   mc stat eurio/enrichment-crops/<storage_path>   # ETag DIFFÉRENT
   # et en base : detection_method='manual', bbox = le nouveau cercle, 224×224
   ```
   Puis que la prédiction DINO est marquée périmée — **sans avoir disparu**
   (D6 amendée, migration 0013) :
   ```sql
   SELECT top1_eurio_id, stale_since FROM image_asset_dino_predictions
    WHERE asset_id = '<asset_id>';
   -- attendu : la ligne est TOUJOURS là (l'écran continue de la proposer, en
   -- disant « calculée avant ton recadrage ») et `stale_since` est daté.
   -- `go-task ml:dino-predictions:backfill` la recalcule depuis le Mac, SANS
   -- --force, et remet `stale_since` à NULL.
   ```

4. **L'admin** se reconnecte avec son compte, ouvre `/review/arbitrage` (carte
   III du tableau de bord, ou l'entrée « Arbitrage » de la nav), voit les
   décisions de l'ami — crop **recadré** ↔ canonique de la classe —, décoche les
   mauvaises, approuve le reste en un geste.

5. **Vérifier** que les approuvées ont `training_eligible = 1` et
   `review_queue.decided_by` = l'identifiant de l'ami, et que les rejetées sont
   **revenues dans la file**.

## Ce que la première vraie session a appris (2026-08-23, soir)

Le PO a reviewé une douzaine d'images avec son compte test — accept, reject,
skip — puis est allé arbitrer. Trois retours, tous corrigés et déployés.

| Retour | Cause | Ce qui a changé |
|---|---|---|
| « Review Arbitrage n'a pas de lien, il faut taper l'URL » **et** `approve-batch 403` | **Une seule cause** : PAT périmé. Les scopes valent `jeton ∩ rôles` — un jeton émis avant `review:arbitrate` ne l'aura jamais. Or l'entrée de nav ET la carte du tableau de bord sont gatées dessus | Le bandeau de session détecte le cas exact (PAT + rôle owner/admin + scope manquant) et donne le remède. C'était voulu, ce n'est plus muet |
| « on ne voit pas précisément bien l'état : acceptée ou refusée ? » | L'action était noyée dans la ligne de métriques, 10 px gris, à côté de « DINO muet » | État en tête de carte, en display italique coloré. Et la vignette cible vide d'un refus dit POURQUOI elle est vide |
| « si on bouge le cadrage, la suggestion de Dino disparaît » | Le lot 6b marquait « à réencoder » en SUPPRIMANT la prédiction | Migration 0013 : elle reste servie, datée comme périmée. Cf. D6, amendé |

**Le troisième est le plus intéressant** : « le marqueur EST l'absence » était le
design le plus élégant, et le seul à ne rien coûter en schéma. Il supposait
qu'une prédiction périmée ne vaut rien — alors qu'elle vaut souvent encore la
bonne réponse, parce que le recadrage réel est un ajustement au micro. Seul
l'usage pouvait le dire.

### Ton PAT — à régénérer une fois

Tant que c'est un jeton d'avant `review:arbitrate`, l'arbitrage reste invisible
et refusé depuis `localhost`. En hébergé, aucun problème : le cookie OIDC
recalcule ses scopes à chaque login.

```bash
# sur le VPS, ça imprime le jeton UNE fois — à ne pas coller dans un chat
ssh serverOimNixDontpanic
docker exec -it eurio-api python -m serving.auth create-pat \
  --email raphaelthi59@gmail.com --name mac-raph
# puis, sur le Mac : go-task secrets:edit  (poser EURIO_API_TOKEN)
#                    direnv reload && relancer go-task front:dev
```

## Quatre pièges qui ont coûté cher — ne pas les repayer

1. **Un screenshot ne prouve que la branche qu'il traverse.** Le lot 6a a été
   déclaré vert sur un crop `confident` ; la branche `uncertain` plantait.
   Vérifier l'état réel du DOM, et chaque cas, pas un. *(Rejoué au lot 8 : la
   branche « DINO en désaccord » n'existait pas naturellement dans le jeu du rig
   — elle a été fabriquée sur la COPIE avant d'être regardée.)*
2. **`serving/server.py` ≠ `serving/server_serve.py`.** Le layered
   `review_queue/` n'est monté que par le lean (VPS). Tester sur `:8042`
   n'exerce pas le code de production.
3. **Vite met le PAT en cache au transform.** Sans `--force`, le bundle ressert
   l'ancien jeton en silence. Et `pkill -f "vite --port 5174"` ne matche rien :
   la ligne réelle est `vite.js --port 5174` — tuer par PID.
4. **Il y a DEUX banques DINO, et elles ne disent pas la même chose.** Celle du
   VERDICT (`vits14`/`2eur_commemo`) alimente le candidat étiqueté `DINO` sur
   l'écran de review et le tri de D8 ; celle des SUGGESTIONS
   (`vitl14`/`2eur_all`) alimente le panneau « SUGGESTIONS DINO » et la pêche.
   Sur les 82 décisions du rig : 71 concordent avec la première, **1** avec la
   seconde. Comparer contre la mauvaise ferait lire « DINO d'accord » sur la foi
   d'un modèle que personne n'a vu.

Le rig complet (API lean locale + front sur port mort) est décrit dans
[`ROADMAP.md`](ROADMAP.md) §« Le rig de vérification ».

## Dettes ouvertes

- **Le front ne dit pas à l'ami que sa décision attend un arbitrage** — choix
  assumé (« sans les fliquer »). Le serveur renvoie déjà
  `{"status": "pending_arbitration"}` si on change d'avis.
- **La page unitaire `/review/peer-arbitration` survit** à côté de la vue en lot.
  Conservée tant que la vue bulk n'est pas éprouvée ; sa suppression est inscrite
  au lot 9 (D10 : on ne supprime pas au fil de l'eau).
- ~~`referential` est skippé sur le VPS faute de PIL~~ — **soldé au lot 6b** :
  l'import Pillow est descendu dans `encode_webp`, et le router est monté depuis
  le 2026-08-23.
