# Kickoff frontend — sources refacto

> Brief auto-suffisant pour ouvrir une session dédiée à l'UX du front
> admin (sources + review queue + coin search). À lire en premier dans
> la nouvelle conversation, puis brainstormer avec le plugin
> `frontend-design`.

## Prompt à coller en début de session

```
J'ouvre une session pour implémenter le front admin de la refacto sources.
Lis ce fichier en entier : docs/sources-refacto/frontend-kickoff.md
Puis lis dans l'ordre :
  1. docs/sources-refacto/decisions.md
  2. docs/sources-refacto/orchestration.md (couches 3+4 surtout)
  3. docs/sources-refacto/review-queue.md
  4. docs/sources-refacto/admin-ux.md
  5. shared/tokens.css (palette + variables design)
  6. admin/packages/web/src/features/sources/ (l'existant à étendre)

Charge ensuite la skill frontend-design:frontend-design.
On va designer ET coder les 3 surfaces majeures :
- /sources (liste cards + page détail :id)
- /review (review queue, le morceau critique)
- /coins/search (sélecteur libre embarqué dans review)

Pas de wireframes ASCII : on code directement en Vue dans
admin/packages/web/. On itère visuellement dans le navigateur (web =
modifs faciles, contrairement à l'Android qui justifie un proto HTML).
Pour les morceaux backend pas encore câblés (ex: mode batch review),
on prévoit l'UI dès le début et on affiche "Coming soon" / disabled
state — la logique métier sera branchée plus tard.
```

## Contexte produit en 30 secondes

Eurio est une app Android de collection de pièces euro. L'app cliente
scanne des pièces via la caméra → identifie via ArcFace on-device → les
ajoute au coffre utilisateur.

Le **modèle ArcFace** a besoin d'**énormes volumes d'images réelles
labellisées** pour bien identifier les pièces en conditions réelles
(in-hand, lumière variable, bruit). Aujourd'hui on n'a quasi que les
photos canoniques Numista (1 paire obverse/reverse propre par pièce),
ce qui limite massivement la précision en prod.

**La refacto sources** ouvre la vanne : eBay, Catawiki, NumisCorner,
CGB, etc. → des dizaines de milliers d'images "in the wild" qu'on
ingère, croppe, résout vers un `eurio_id`, et qui alimentent le
training.

## Vision UX : "scrap massif → filtrer → résoudre"

Le pipeline est volontairement **non-destructif** : on scrap tout, on
crop tout, on tente une résolution automatique par nom (50-70 % de
réussite), et **tout ce qui n'est pas résolu auto va en review queue
humaine**. Volume estimé : **15-30k reviews/an, soit ~50-100/jour**.

L'admin est l'outil opérationnel pour piloter ça. Trois rôles :

1. **Observer** ce qui se passe — runs en cours, couverture par source,
   volumes ingérés (`/sources`).
2. **Résoudre** humainement ce que l'auto n'a pas pu (`/review`).
3. **Sélectionner finement** un eurio_id quand le top-5 auto se trompe
   (`/coins/search` embarqué).

Le rôle 2 est de loin le plus important — c'est là que la valeur se
fabrique. Tout le reste sert ce rôle.

## Trois surfaces à designer

### Surface 1 — `/sources` (liste + détail)

**Contexte** : page existe déjà en V0 dans
`admin/packages/web/src/features/sources/`, à étendre.

**Liste** (cards par source) :
- statut santé, quota, dernier run avec déltas (images, quotes)
- "Voir détails" → page :id

**Détail** : 4 onglets — Runs, Données, Couverture, Commandes.
Spec complète : [`admin-ux.md`](./admin-ux.md).

**Polling** : statut "live" d'un run en cours, `GET /sources/:id/runs/:run_id`
toutes les 2s.

### Surface 2 — `/review` (review queue) — **LE MORCEAU CRITIQUE**

**Contexte** : page complètement nouvelle. Spec détaillée :
[`review-queue.md`](./review-queue.md).

**Principes UX figés** :
- **Vitesse > exhaustivité** (50-100 décisions/jour, objectif ≤ 10s
  par décision médiane)
- **L'humain ne tape pas, il sélectionne** (top-5 candidats
  pré-calculés par `auto_name`)
- **L'image canonique Numista est toujours visible** côté droit pour
  comparaison
- **Raccourcis clavier partout** (1-5, Enter, R, N, F, Esc)
- **Pas de retour arrière forcé** dans le flow

**Layout proposé** (ASCII dans `review-queue.md`) :
- Image à résoudre (gauche) + crop avec bbox + métadonnées listing
- Top-5 candidats (droite) : ID + score + thumb canonique Numista
- Sélecteur libre en dessous : pays → dénomination → année →
  thumbs Numista filtrés
- Face détectée (radio obverse/reverse/unknown)
- Actions : Validate (Enter), Reject (R), Skip

**À designer ensemble** :
- Le rythme visuel (densité d'info vs respiration)
- L'animation de transition entre 2 reviews (instantanée ? 200 ms
  fade ? Ne doit JAMAIS ralentir le flow clavier)
- L'état "empty queue" et "stats du jour" (pour gamifier un peu)
- Le mode batch : **prévu dès V1 dans l'UI** (multi-select, toolbar
  d'action groupée), même si le câblage backend arrive plus tard. On
  affiche les actions batch en disabled + tooltip "Coming soon" tant
  que l'API n'est pas branchée. Layout single-item conçu pour
  cohabiter avec le multi-select sans refonte.
- L'état "image clairement inutilisable" (1-clic Reject vs confirmation)

### Surface 3 — `/coins/search` (embarqué dans review)

Pas une page en propre — un composant dropdown/modal cascade :
pays → dénomination → année (optionnel) → grille de thumbs canoniques
Numista cliquables.

C'est le filet quand le top-5 auto est complètement à côté de la plaque
(métadonnées listing trop mauvaises). 10-20 % des cas. Doit rester
**rapide** — l'humain a déjà perdu sa bataille avec l'auto, ne pas
ajouter de friction.

## Stack et conventions du repo

- **Vue 3** + Vite, dans `admin/packages/web/`
- **TypeScript** strict
- **pnpm** workspace (cf. mémoire `project_admin_workspace`)
- **Source de vérité design** : [`shared/tokens.css`](../../shared/tokens.css)
  (couleurs, espacements, rayons, durées, typo). Ne JAMAIS hardcoder.
- Pages existantes pour s'inspirer du style maison :
  `admin/packages/web/src/features/{sources,lab,augmentation,confusion}/`
- Backend : FastAPI (`ml/api/`), endpoints listés dans
  [`orchestration.md`](./orchestration.md) §"API surface (V1)"

**Déploiement** : Vercel pour `packages/web`. Quelques pages dégradent
gracefully si le backend ML local est off (cf. mémoire
`project_admin_workspace`).

## Données disponibles côté API (rappel)

```
GET  /sources/status                          # cards
GET  /sources/:id                             # header
GET  /sources/:id/runs?limit=50
GET  /sources/:id/runs/:run_id
GET  /sources/:id/raws?status=...&page=...    # source_images
GET  /sources/:id/crops?status=...&page=...   # image_assets
GET  /sources/:id/quotes?page=...

GET  /review-queue?status=open&limit=20&order=priority
GET  /review-queue/:id                        # crop + raw + top-5 + context
POST /review-queue/:id/decide                 # body: eurio_id, face, variant, notes
POST /review-queue/:id/skip
POST /review-queue/:id/reject

GET  /coins/search?country=BE&denomination=2&year=&limit=24
```

Les endpoints `/sources/...` étendus + `/review-queue/...` + `/coins/search`
n'existent pas encore — leur design backend va se faire en parallèle de
l'UX (couplé). C'est OK : on peut concevoir les vues avec mocks puis
brancher.

## États visuels à couvrir

Pour chaque surface, le designer doit prévoir :

- **Loading** (skeleton ou spinner ?)
- **Empty** (queue vide = félicitations + stats ?, source sans run ?)
- **Error** (API down, image manquante sur disque, eurio_id invalide)
- **Partial** (run interrompu, certaines images sans crop)
- **Stale** (poll > 5s sans update, état "?")

## Volume et performance

- Liste sources : ~10 sources max, no pagination needed.
- Liste runs : pagination 50/page, last 200 visibles.
- Liste raws/crops : peut atteindre 50k+ rows par source, **virtualisation
  obligatoire** (vue galerie 24 thumbs/page suffit).
- Review queue : peut atteindre 1k-30k pending, virtualisation aussi.
- Coin search dropdown : 21 pays × ~10 dénominations × ~25 années =
  borné, pas de souci.

## Ce qu'on NE fait PAS dans cette session

- Backend. Les endpoints sont listés mais leur implémentation est
  côté `phase-1-foundations.md`. On mocke côté front (fixtures locales
  ou MSW) tant que l'API n'existe pas.
- Design tokens nouveaux inventés à la volée. Si un composant a besoin
  d'un token absent, on l'ajoute proprement dans `tokens.css` (R2),
  pas en dur dans le composant.

## Sortie attendue de la session frontend

Du code Vue dans `admin/packages/web/src/features/` :

- `features/sources/` étendu : liste cards + page détail `:id` (4 onglets)
- `features/review/` créé : review queue (single-item + multi-select V1
  côté UI, actions batch disabled tant que backend pas câblé)
- composants partagés : `CoinSearchModal.vue`, `CandidateGrid.vue`,
  `CanonicalThumb.vue`, etc. — placement à décider en session
  (`features/_shared/` ou `components/`)

Pas de docs intermédiaires (wireframes, components.md) : le code Vue +
les commentaires inline + le diff git font foi. Si un point mérite une
trace durable (raccourcis clavier figés, décision d'archi), on la met
dans `decisions.md`.

## Contraintes héritées

- **R1 proto-first ne s'applique PAS ici.** R1 vise l'app Android
  (Compose lent à itérer → besoin d'un proto HTML préalable). Admin
  est du web Vue : les modifs sont triviales, on code direct et on
  itère dans le navigateur. Le proto HTML reste réservé à l'Android.
- **R2 tokens** : `tokens.css` est la source canonique. Ne jamais
  hardcoder une couleur/espace dans un composant Vue — passer par les
  variables CSS ou ajouter le token manquant dans `tokens.css`.
- Pas d'emojis dans le code (CLAUDE.md).
