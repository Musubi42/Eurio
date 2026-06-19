# C6 — Panel : portage des écrans review

> **But (1 phrase)** : reproduire dans `admin/packages/panel/src/views/review/`
> les écrans de `admin/packages/review-admin/` (queue + decide + stats + admin
> flow/publish), branchés sur `/review/*` du nouveau `eurio-api`.
>
> **Ne fait PAS** : décommissionner l'app legacy `review-admin` (C9). Pendant
> ce chunk les deux UI coexistent pour comparaison/parité.

## 0. Pré-requis

- C4 ✅ — routes `/review/*` opérationnelles sur `eurio-api`.
- C5 ✅ — panel shell + auth fonctionnels.
- Branche : `auth-redesign-c6`.

## 1. Inventaire des écrans à porter

Source : `admin/packages/review-admin/src/App.vue` + `api.ts`. Identifier :

- **Liste des items à reviewer** (`/me/items` legacy → `/review/me/items`).
- **Vue de décision** (claim + decide + skip).
- **Stats personnelles** (`/me/stats` → `/review/me/stats`).
- **Vue admin** : flow + decisions historique + publish. Tout est gardé sous `review:write` simple (sous-scope `review:publish` **rejeté** dans DESIGN.md §3.3). La séparation reviewer/admin se fait via le rôle (`reviewer` vs `admin`/`owner`), pas via un scope dédié. Si la publication devient un workflow à deux niveaux plus tard, on revisitera.

## 2. Structure dans le panel

```
admin/packages/panel/src/views/review/
├── ReviewQueue.vue       ← liste + claim
├── ReviewDecide.vue      ← écran de décision sur un item
├── ReviewStats.vue       ← stats perso
└── admin/
    ├── ReviewFlow.vue
    ├── ReviewDecisions.vue
    └── ReviewPublish.vue
```

Routes nestées sous `/review/...`. Les routes `admin/*` ont `meta.scope`
plus restrictif.

## 3. API client

Étendre `admin/packages/panel/src/api/client.ts` avec :

```ts
export const reviewApi = {
  listMyItems: () => get('/review/me/items'),
  claim: () => post('/review/claim'),
  decide: (itemId, decision) => post(`/review/items/${itemId}/decide`, decision),
  skip: (itemId) => post(`/review/items/${itemId}/skip`),
  myStats: () => get('/review/me/stats'),
  // admin
  flow: () => get('/review/flow'),
  decisions: (params) => get('/review/decisions', params),
  ackDecisions: (ids) => post('/review/decisions/ack', { ids }),
  publish: () => post('/review/publish'),
};
```

## 4. Design

- **Reprendre les tokens** `shared/tokens.css` (cf. CLAUDE.md R2).
- **Comparer le rendu** avec le proto Vue+Pinia (`admin/packages/proto/`) si
  des scènes équivalentes y existent. Sinon : suivre l'aspect du legacy
  `review-admin` en l'épurant.

## 5. Critères d'acceptation

- Connexion en `reviewer` → voir uniquement `Queue` + `Stats`. Pas de `Flow` ni `Publish`.
- Connexion en `owner` → voir tous les écrans admin/review.
- Round-trip complet : claim → decide → l'item disparaît de la queue.
- Stats reflète l'action.
- Comparaison parité avec `review-admin` legacy : aucun écran manquant.

## 6. Garde-fous

- Ne pas court-circuiter les guards de scope.
- Garder `review-admin` legacy déployable en parallèle (kill en C9).
- Si un écran a besoin d'une fonctionnalité non couverte par les routes
  `/review/*` portées en C4 : **remonter** vers C4 plutôt que d'ajouter une
  route ad-hoc ici.

## 7. Résumé

```
## C6 — résumé portage review

- Écrans portés : <liste>
- Parité legacy validée : OUI/NON
- Round-trip claim/decide : OK
- Scopes respectés : OK
- Déviations : <…>
```
