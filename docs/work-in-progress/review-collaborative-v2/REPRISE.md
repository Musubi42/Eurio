# Reprise — état au 2026-08-23, et ce qu'il reste pour clore

> À lire en premier dans une nouvelle session. Le reste du chantier est dans
> [`CONSTAT.md`](CONSTAT.md) (mesures), [`DECISIONS.md`](DECISIONS.md) (D1-D11),
> [`ROADMAP.md`](ROADMAP.md) (lots + rig de vérification et ses pièges),
> [`DEPLOIEMENT.md`](DEPLOIEMENT.md), [`NETTOYAGE.md`](NETTOYAGE.md).

## Où on en est

**Déployé en production** (commit `7654cbf7`, VPS à jour) et **utilisé pour de vrai** :
le PO a créé un compte reviewer dans Authentik, s'est connecté sur
`https://eurio-admin.musubi.dev`, et la review fonctionne.

Livrés et vérifiés : lots 0, 1, 1b, 2, 3, 4, 4b, 5, 6a.
Un ami peut aujourd'hui : voir la file, voir le crop et le canonique, lire les
suggestions DINO, chercher une pièce librement, trancher — sa décision partant en
quarantaine sans toucher le canonique.

## Le défaut trouvé à l'usage — à corriger en premier

Le PO, avec son compte reviewer : *« pour faire la review, on nous dit que c'est en
local »*.

**Cause exacte, déjà diagnostiquée** — pas besoin de la rechercher :
`ReviewDashboardPage` (la page `/review`, celle où l'ami arrive) propose deux entrées,
`/review/manual` et `/review/auto-accept`. La seconde porte encore `meta: heavy` **et**
relève de l'arbitre. L'ami clique et tombe sur la page pleine « Cette vue tourne en
local » (`shared/ui/LocalOnlyNotice.vue`).

Le lot 5 avait masqué le *bouton* `AUTO-ACCEPT` de la barre de review, mais pas la
*carte* du tableau de bord. `/review/recover` est dans le même cas (heavy + arbitre).

**Ce qu'il faut faire** : cf. [`DECISIONS.md`](DECISIONS.md) **D11**. En résumé, pour un
principal sans `review:arbitrate` : ne pas proposer les entrées `heavy`, **masquer**
(et non griser) les contrôles gatés par la machine, et ne jamais afficher « local » ni
`:8042`. Le grisé reste pour l'arbitre sur son poste.

⚠️ C'est un revirement partiel d'une décision du lot 5, assumé et motivé dans D11 —
ne le re-tranche pas dans l'autre sens sans lire pourquoi.

## Ce qui reste, dans l'ordre conseillé

| Lot | Objet | Pourquoi cet ordre |
|---|---|---|
| **D11** | Ne plus rien montrer de « local » à un ami | Le PO le voit **aujourd'hui**, en prod. Court. |
| **8** | La vue bulk d'arbitrage | Sans elle le PO ne peut pas relire ce que son ami a produit. C'est la moitié manquante de la boucle. |
| **6b** | Le recadrage à distance (`opencv-python-headless`) | 18,4 % des crops sont recadrés à la main : sans ça, l'ami ne fait que la moitié du travail. Rend D11 en partie caduc. |
| 7 | Le bail sur la file | Utile seulement à partir de 2 amis simultanés. |
| 9 | Full clean | En dernier, quand tout est prouvé. |

Le détail de chaque lot est dans [`ROADMAP.md`](ROADMAP.md).

### Sur le lot 8 — ce qui est déjà écrit

`AutoAcceptReviewPage.vue` fait **déjà** exactement ce que le PO a décrit : grille
`lg:grid-cols-2` de `ReviewCard` (props `crop-url` + `canonical-url` + `selected` +
`@toggle`), **tout coché par défaut**, garde `BULK_CONFIRM_THRESHOLD`. La vue
d'arbitrage, c'est cette page avec une autre source : onglets par personne, scroll
infini, et `POST /peer-arbitration/approve-batch` (à ajouter — la boucle sur
`approve()` existe déjà, `peer_arbitration_routes.py:156`, y compris le cas
`superseded` quand une voie locale a tranché entre-temps).

**Tri décidé (D8)** : désaccords avec DINO **en tête et non cochés**, le reste coché.
Mesuré : 62,6 % des décisions rejoignent DINO top-1 (67,3 % avec le re-rank pays).
Sans ce tri, un scroll tout-coché est un tampon en caoutchouc.

## Le scénario de recette, à jouer ensemble en fin de session

1. **L'ami** se connecte sur `https://eurio-admin.musubi.dev` avec le compte reviewer
   et tranche une dizaine de crops — dont au moins un qu'il **recadre** (donc après 6b)
   et un où il **contredit DINO** via la recherche libre `F`.
   → Rien de « local » ne doit apparaître à l'écran. Aucun port. Aucun bouton mort.
2. **Vérifier en base** que le canonique n'a pas bougé et que les lignes sont `pending` :
   ```bash
   ssh serverOimNixDontpanic 'docker exec eurio-api python -c "
   import sqlite3
   c=sqlite3.connect(\"file:/var/lib/eurio/eurio.db?mode=ro\",uri=True); c.row_factory=sqlite3.Row
   print([dict(r) for r in c.execute(
     \"select reviewer_name, action, arbitration_status from peer_review_decisions \"
     \"order by decided_at desc limit 10\")])"'
   ```
3. **L'admin** se reconnecte avec son compte, ouvre la **vue bulk d'arbitrage**, voit
   les décisions de l'ami (crop recadré ↔ canonique de la classe), décoche les
   mauvaises, approuve le reste en un geste.
4. **Vérifier** que les approuvées ont bien `training_eligible = 1` et
   `review_queue.decided_by` = l'identifiant de l'ami, et que les rejetées sont
   **revenues dans la file**.

## Trois pièges qui ont coûté cher — ne pas les repayer

1. **Un screenshot ne prouve que la branche qu'il traverse.** Le lot 6a a été déclaré
   vert sur un crop `confident` ; la branche `uncertain` plantait. Vérifier l'état réel
   du DOM, et chaque cas, pas un.
2. **`serving/server.py` ≠ `serving/server_serve.py`.** Le layered `review_queue/` n'est
   monté que par le lean (VPS). Tester sur `:8042` n'exerce pas le code de production.
3. **Vite met le PAT en cache au transform.** Sans `--force`, le bundle ressert l'ancien
   jeton en silence. Et `pkill -f "vite --port 5174"` ne matche rien : la ligne réelle
   est `vite.js --port 5174` — tuer par PID.

Le rig complet (API lean locale + front sur port mort) est décrit dans
[`ROADMAP.md`](ROADMAP.md) §« Le rig de vérification ».

## Deux dettes ouvertes, mesurées

- **`referential` est skippé sur le VPS** (`ModuleNotFoundError: No module named 'PIL'`).
  Sans effet aujourd'hui : les **689 pièces sur 689** ont une URL canonique externe
  absolue, donc le repli relatif ne se déclenche jamais. À reprendre avec `cv2` au
  lot 6b.
- **Le front ne dit pas à l'ami que sa décision attend un arbitrage** — choix assumé
  (« sans les fliquer »). Le serveur renvoie déjà `{"status": "pending_arbitration"}`
  si on change d'avis.
