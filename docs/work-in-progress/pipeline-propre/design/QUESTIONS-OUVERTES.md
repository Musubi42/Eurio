# Questions ouvertes — design `/besoin`

> Ce que la session du **2026-08-22** n'a pas tranché, avec une recommandation
> pour chaque point. Complément de [`DESIGN.md`](DESIGN.md).
> Banque de référence : `a55e6594da3247ec80bc609f93342f51` (22/08 18:06).

---

## Q1 · La courbe « exactement 1 exemplaire partout » — **bloquant pour D7**

**Le problème.** D7 (deux paliers) repose sur l'A/B médoïde : +10,8 points entre
N=0 et N=1, +1,2 point entre N=1 et N=10. Mais le `N` de `bench_refs_curve` est
**plafonné par ce que chaque classe possède** : à N=1, seules les 250 classes
qui ont au moins un exemplaire changent. Les 421 à zéro sont identiques dans les
deux colonnes. On ne peut donc pas conclure directement que « donner 1 exemplaire
aux 421 classes vides vaut plus que d'amener 90 classes de 5 à 8 ».

**Ce qu'il faut mesurer.** Une courbe où chaque classe reçoit **exactement** un
exemplaire (médoïde), comparée à la banque actuelle. Idéalement aussi le
découpage du gain : ce que les classes nouvellement couvertes gagnent, contre ce
que les classes déjà couvertes perdent (une classe de plus dans la banque est
aussi un distracteur de plus).

**Recommandation.** Demander la mesure à la session ML **avant** d'implémenter
le tri par palier. En attendant, D7 se conçoit et se maquette — le tri est un
paramètre, pas une structure. Si la mesure infirme, on retombe sur le tri d'O2
(`min(need, pending_scoped)` décroissant) sans rien redessiner.

**Ce qui ne change pas quoi qu'il arrive** : les 421 classes à zéro existent,
147 ont des candidats, et le fait de les rendre visibles est un progrès net.

---

## Q2 · Le palier 1 est-il atteignable ? 73 classes sur 147 ont une marge < 0,05

```
147 classes à have=0 avec au moins un candidat
   43 avec une marge max ≥ 0,10   (palier d'auto-acceptation)
   74 avec une marge max ≥ 0,05   (seuil du verdict)
   73 avec une marge max < 0,05   ← le modèle n'est net sur AUCUN candidat
```

Sur ces 73, il est probable qu'une bonne partie des candidats soient des faux
positifs — la file existe, mais elle ne contient rien d'utilisable. Si c'est le
cas, le palier 1 « à portée » ne fait pas 147 classes mais quelque chose entre
74 et 147, et les autres basculent en `scrape`.

**Recommandation.** Ne pas trancher à l'aveugle : **trancher les 43 classes à
marge ≥ 0,10 en premier** (une petite session), et mesurer le taux d'acceptation
réel. Ce chiffre dira si les 73 valent le déplacement. C'est aussi le meilleur
premier test grandeur nature de la session palier 1.

---

## Q3 · La review hébergée — chantier séparé, périmètre mesuré

**Constat.** La review est `meta.heavy` pour deux raisons seulement :

| ce qui accroche | où |
|---|---|
| résolution des URLs d'images vers `${ML_API}` | `useReviewApi.ts:210`, `useLotReview.ts:165`, `useCoinsSearch.ts:120` |
| édition de lots (`add-crop` / `sync-crops`) — seul code à toucher cv2 | `useLotReview.ts:273` |

Les **décisions** partent déjà au canonique (`eurioApi.post`,
`serving/review_queue/writes.py`). Et les crops vivent dans MinIO
(`eurio-s3.musubi.dev`), public en HTTPS.

**Ce que ça vaudrait.** Le palier 1 fait ~338 décisions : c'est du travail qu'on
abat par tranches de dix minutes, dans le train, sur téléphone. Aujourd'hui il
faut un Mac allumé.

**Recommandation.** Ne pas l'inclure dans les lots de `/besoin`. L'ouvrir comme
chantier propre, avec une première question à vérifier : **est-ce que
`eurio-api` sait déjà servir une URL présignée MinIO pour un `image_asset` ?**
Si oui, le chantier est petit (une fonction de résolution d'URL pilotée par
`deploy-target`) ; sinon il commence par une route au canonique. L'édition de
lots reste locale dans tous les cas.

---

## Q4 · Que devient le bouton « enfiler les orphelins » de la pêche ?

`PecheBar` propose aujourd'hui d'enfiler les crops que la banque rattache à une
classe mais qui n'ont **aucune ligne de review ouverte** (`n_orphans`,
`reflagAssetsNeedsReview`). C'est une écriture, correctement isolée sur un clic.

Sous D9 (`need_only` par défaut), il devient ambigu : faut-il enfiler des
orphelins d'une classe **pleine** ? Non — mais l'écran ne le dit pas.

**Recommandation.** Le bouton reste, et il **hérite du filtre** : il n'enfile que
les orphelins dont le top-1 tombe dans une classe en besoin, et il annonce le
compte écarté (« 12 enfilés · 40 parqués »). C'est cohérent avec D2/D3, et ça ne
demande qu'un filtre côté appelant.

⚠️ À vérifier avant : `POST /coins/assets/reflag-needs-review` est l'un des
**deux résiduels de rerouting mesurés** (CLAUDE.md §Infra) — il n'a pas de jumeau
au canonique. Sous D9 ce bouton devient plus utilisé, donc le résiduel devient
plus visible. Lire `eurio-data-writes` avant de le toucher.

---

## Q5 · Le thème sombre n'existe pas dans `studio-local`

Les maquettes de ce dossier sont livrées en clair **et** en sombre, comme
demandé. Mais `shared/tokens.css` ne définit **aucun jeu sombre**, et
`studio-local/src/styles/index.css` ne porte aucun `prefers-color-scheme`.

Le sombre des maquettes est donc une **proposition**, obtenue en remappant les
tokens sémantiques (`--surface*` ↔ `--ink*`), pas un existant.

**Recommandation.** Ne pas livrer le sombre avec `/besoin`. Si le PO le veut,
c'est un geste à part et il passe par **R2** : le jeu sombre s'écrit dans
`shared/tokens.css`, `go-task tokens:generate` propage vers Android, et les deux
fichiers partent dans le même commit. Faire du sombre local à une page créerait
exactement la dette que R0 interdit.

---

## Q6 · Qui déclenche le rebuild, et depuis où ?

D8 dit que la page **propose** le rebuild et ne le déclenche jamais seule. Reste
à trancher **d'où** part le geste :

| option | pour | contre |
|---|---|---|
| bouton dans le bandeau REBUILD, `heavy` | le geste est là où l'information est | un rebuild dure des minutes et change tous les verdicts — un bouton trop accessible |
| ligne de commande seulement (`build_dino_anchors`) | c'est l'existant, zéro travail | la boucle reste invisible, ce que FLOW-ADMIN §3 reproche déjà |
| bouton + confirmation qui **liste l'effet** (« 76 exemplaires, 8 classes pleines, 14 verdicts changeront ») | l'effet est connu avant le clic | il faut calculer l'effet, ce qui est déjà fait par `accepted_pending` |

**Recommandation :** la troisième. Le calcul est gratuit une fois D8 en place, et
« un geste dont on voit l'effet avant de le faire » est exactement ce qui manque
partout ailleurs dans ce dépôt.

---

## Q7 · Le seuil de `pending_scoped` pour la dénomination

O4b propose `denom_2eur_score ≥ 0,4`, **inactif par défaut** (il coûte ~5 % de
vrais positifs). La page compte donc `pending_scoped` **sans** ce filtre.

Si un opérateur l'active dans la pêche, le compte de la ligne et le compte de la
file divergent — le défaut qu'on cherche à éviter.

**Recommandation.** Les filtres de la page et ceux de la pêche sont **le même
état, porté par l'URL**. Activer la dénomination dans la pêche remonte à la page
au retour. Un seul jeu de réglages, un seul compte. Corollaire : le réglage
appartient à la **session**, pas à la classe.

---

## Q8 · Les 274 classes jamais scrapées : quelles requêtes ?

Le PO a demandé « des requêtes peut-être un peu plus abouties ». La page peut
montrer le besoin par pays (LU 37, SM 28, VA 27, MT 26, PT 26, GR 22…) et
estimer le coût, mais **la qualité de la requête eBay elle-même est hors de son
périmètre** — elle vit dans l'allocateur (`scripts/allocate_ebay_scrape.py`) et
son grain est le groupe de découverte (pays · dénomination · année).

**Recommandation.** Ne rien inventer ici. Ouvrir la question côté allocateur
avec un fait mesuré à lui donner : parmi les 7 662 annonces déjà achetées, **2
281 n'ont toujours aucun crop après O7**, et le taux de réussite par groupe de
découverte n'est mesuré nulle part. Savoir **quelles requêtes rendent des crops**
est le prérequis d'une meilleure requête, et c'est de l'entonnoir O3, pas de
`/besoin`.
