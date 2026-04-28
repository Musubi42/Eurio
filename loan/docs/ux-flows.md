# UX flows — mobile-first

Tous les écrans sont pensés **portrait, mobile**. Desktop = container
centré max-w-md (sauf `/admin` qui est plus large).

## Tokens

Import direct de `shared/tokens.css` du monorepo (même charte que
l'admin Eurio), via Tailwind `@theme` ou import CSS global. **Pas de
couleurs hardcodées.**

## Flow d'arrivée (visiteur)

```
┌─────────────────────────┐
│ Arrivée sur https://    │
│ eurio-loan.vercel.app   │
└────────────┬────────────┘
             ▼
   ┌──────────────────┐
   │ localStorage a   │ oui  ┌─────────────┐
   │ un userId ?      │ ───▶ │ /catalog    │
   └────────┬─────────┘      └─────────────┘
            │ non
            ▼
       /  (identification)
```

## Page `/` (identification)

```
┌─────────────────────────────────┐
│  Eurio · Prête-moi tes 2€       │
│                                 │
│  Salut ! Raphaël collectionne   │
│  des pièces de 2€ pour          │
│  entraîner son app de scan.     │
│                                 │
│  Comment tu t'appelles ?        │
│  ┌───────────────────────────┐  │
│  │ Thomas                    │  │
│  └───────────────────────────┘  │
│                                 │
│  Choisis un emoji :             │
│  ┌─┬─┬─┬─┬─┬─┐                  │
│  │🦊│🐢│🦉│🐙│🐝│🦋│              │
│  ├─┼─┼─┼─┼─┼─┤                  │
│  │🌻│🍒│🍑│🌶│⚡│🌙│              │
│  └─┴─┴─┴─┴─┴─┘                  │
│                                 │
│  [   On y va  →   ]             │
└─────────────────────────────────┘
```

Submit : `POST /api/users` → localStorage write → redirect
`/catalog`.

## Page `/catalog`

```
┌─────────────────────────────────┐
│ 🦊 Thomas             [↻ filtres]│
│ ┌─────────────────────────────┐ │
│ │ 🔎 Rechercher…              │ │
│ └─────────────────────────────┘ │
│ Filtres :                        │
│  [Pas chez Raph ✓] [×]          │  ← chip par défaut
│  [+ Filtres]                    │
└─────────────────────────────────┘
```

### Filtres (drawer)

- **Pas chez Raph** (par défaut ON, dérivé de `personal_owned=false`)
- **Pays** (multi-select, 25 chips)
- **Type** : Circulation / Commémo nationale / Commémo commune
- **Recherche** texte

### Card pièce

```
┌────────────────────────────┐
│ ┌────────┐  Italie · 2002  │
│ │  IMG   │  2 €            │
│ │        │  Circulation    │
│ └────────┘  Dante Alighieri│
│                            │
│ ✓ Tu l'as          ☐       │
│ Raph l'a déjà ✅            │  ← seulement si personal_owned
└────────────────────────────┘
```

Tap sur la card → `/coins/[eurio_id]`.

## Page `/coins/[eurio_id]`

Coin Detail allégé.

```
┌─────────────────────────────────┐
│ ←  Retour                       │
│                                 │
│  ┌───────────────────────────┐  │
│  │      [image principale]    │  │
│  └───────────────────────────┘  │
│  • • •                          │
│                                 │
│  Italie · 2002 · 2 €            │
│  Circulation                    │
│                                 │
│  ┌─────────────────────────┐    │
│  │ ☐ Tu l'as              │    │
│  └─────────────────────────┘    │
│                                 │
│  À propos                       │
│  Représente Dante Alighieri…    │
│                                 │
│  Tirage : 130 000 000           │
│                                 │
│  Cote                           │
│  · eBay (médiane) : 2,80 €      │
│  · Monnaie de Paris : 3,00 €    │
│                                 │
│  En savoir plus                 │
│  → Numista                      │
│  → Wikipédia                    │
└─────────────────────────────────┘
```

**Pas affiché** : confusion_zone, voisins visuels, scores ML,
design_group_id, model_classes, needs_review.

## Page `/admin` (basic auth)

Vue desktop-friendly (mais reste utilisable mobile). **Toutes les
listes par ami sont rétractées par défaut.** Le header de chaque
liste suffit à scanner l'état global.

```
┌──────────────────────────────────────────┐
│ Loan admin · 4 amis · 27 claims · 9/27 prêtées │
│                                          │
│ ▶ 🦊 Thomas    7 / 12 prêtées            │
│ ▶ 🐢 Pierre    0 / 8  prêtées            │
│ ▶ 🦉 Marie     2 / 5  prêtées            │
│ ▶ 🐙 Léo       0 / 2  prêtées            │
└──────────────────────────────────────────┘
```

Déplié :

```
▼ 🦊 Thomas    7 / 12 prêtées
   ☑ FR-2024-… France 2024 Olympiades
   ☑ IT-2002-… Italie 2002 Dante
   ☐ DE-2008-… Allemagne 2008 Hambourg
   ☐ ES-2007-… Espagne 2007 Traité de Rome
   …
```

Interaction :

- Click sur le header `▶/▼` ami → fold/unfold la liste.
- Click sur la checkbox d'une pièce → toggle « prêtée » (SADD/SREM
  `user:{id}:lent`). Mise à jour optimiste.
- Le header recalcule son ratio à chaque toggle.
- Pas de delete user ni de delete claim : tout est append/toggle.

API :

- `GET /api/admin/overview` →
  `[{ user, claims: string[], lent: string[] }, …]`
- `POST /api/admin/lent` `{ userId, eurio_id }` → SADD
- `DELETE /api/admin/lent` `{ userId, eurio_id }` → SREM

**Important** — cocher la checkbox `/admin` ne touche **pas** à
`coins.lent_to_me` côté Supabase. C'est intentionnel : les deux flags
ont un usage distinct (admin Vercel = vue par ami, Supabase = filtre
training global). Je les maintiens en parallèle à la main.

## API routes

| Route | Auth | Description |
|---|---|---|
| `POST /api/users` | — | Crée un user (KV) |
| `GET /api/users/me` | header `x-user-id` | Récupère le user courant |
| `GET /api/me/claims` | header `x-user-id` | Liste des claims du user |
| `POST /api/claim` | header `x-user-id` | SADD `user:{id}:claims` |
| `DELETE /api/claim` | header `x-user-id` | SREM `user:{id}:claims` |
| `GET /api/admin/overview` | basic auth | Tous users + claims + lent |
| `POST /api/admin/lent` | basic auth | SADD `user:{id}:lent` |
| `DELETE /api/admin/lent` | basic auth | SREM `user:{id}:lent` |

Toutes les routes côté serveur lisent uniquement KV.

## Décisions UX clés (résumé)

| Sujet | Décision |
|---|---|
| Auth visiteur | Aucune. Identification prénom + emoji + nanoid. |
| Auth admin | Basic auth via env vars Vercel. |
| Claim | Multi, sans policy. UI ne montre pas qui d'autre a claim. |
| Filtre par défaut | « Pas chez Raph » activé, chip visible et désactivable. |
| URL Coin Detail | `/coins/[eurio_id]` (aligné admin pour partage futur). |
| Langue | Français. |
| Mobile-first | Strict (sauf `/admin` desktop-friendly). |
| Page `/me` | Supprimée — redondante avec checkboxes du catalog. |
