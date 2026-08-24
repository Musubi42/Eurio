# C6 — Panel : portage des écrans review

> **But (1 phrase)** : reproduire dans `admin/packages/panel/src/views/review/`
> les écrans de `admin/packages/review-admin/` (queue + decide + stats + admin
> flow/publish), branchés sur `/review/*` du nouveau `eurio-api`.
>
> **Ne fait PAS** : décommissionner l'app legacy `review-admin` (C9). Pendant
> ce chunk les deux UI coexistent pour comparaison/parité.

## 0. Pré-requis

- C4 ✅ — routes `/review/*` opérationnelles sur `eurio-api` (cf. `ml/serving/review_routes.py`, smoke-testé E2E le 2026-06-19).
- C5 ✅ — panel shell + auth fonctionnels (`admin/packages/panel/`, build 38KB gzip).
- Lire d'abord : [`RESUME-NEXT-SESSION.md`](./RESUME-NEXT-SESSION.md) — findings et décisions arrivées en cours de route.
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

Créer `admin/packages/panel/src/api/review.ts`. **`api/client.ts` expose `api.get/post/put/delete<T>(path, body?)`** (pas `get/post`).

```ts
import { api } from './client'

export interface ReviewItem {
  id: string
  image_asset_id: string
  crop_url: string
  source: string | null
  listing_title: string | null
  candidates: Array<Record<string, unknown>>
  target_eurio_id: string | null
  dino_top1: Record<string, unknown> | null
}

export interface DecidePayload {
  action: 'accept' | 'reject'
  eurio_id?: string
  face?: string
  variant_kind?: string
  quality_reason?: string
  notes?: string
}

export const reviewApi = {
  listMyItems: () => api.get<{ items: ReviewItem[]; window: number }>('/review/me/items'),
  claim: () => api.post<{ items: ReviewItem[]; window: number }>('/review/claim'),
  decide: (itemId: string, decision: DecidePayload) =>
    api.post<{ status: string; id: string }>(`/review/items/${itemId}/decide`, decision),
  skip: (itemId: string) =>
    api.post<{ status: string; id: string }>(`/review/items/${itemId}/skip`),
  myStats: () => api.get<{ total: number; today: number; user_id: string }>('/review/me/stats'),
  // admin
  flow: () => api.get('/review/flow'),
  decisions: (unreconciled = 1) => api.get(`/review/decisions?unreconciled=${unreconciled}`),
  ackDecisions: (ids: string[]) => api.post('/review/decisions/ack', { ids }),
  publish: (items: unknown[]) => api.post('/review/publish', { items }),
}
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
