# Data model — KV (Vercel) + un toggle Supabase

Deux mondes **séparés et non synchronisés** :

- **Vercel KV** : claims des amis (volatile, opérationnel).
- **Supabase `coins.lent_to_me`** : signal binaire pour l'admin Eurio,
  toggle **manuel** quand je reçois physiquement une pièce. Pas de
  sync auto.
- **Notion** (externe) : tracking physique (qui a prêté quoi, quand,
  rendu ou non). Hors-repo.

## Vue d'ensemble

```
┌─────────────────────┐
│ Supabase (source)   │
│ table `coins`       │ ← curated par moi (admin Eurio)
│ + personal_owned    │
│ + lent_to_me ◀────────── toggle manuel admin /coins
└──────────┬──────────┘
           │ (build local, clé service role)
           ▼
┌────────────────────────────┐
│ catalog.json + /public/coins/*.jpg │ ← embarqué dans bundle Next
└────────────┬───────────────┘
             │ vercel deploy --prebuilt
             ▼
   ┌────────────────┐
   │ Vercel (CDN)   │
   │ + Vercel KV    │ ← claims (visiteurs) + admin overrides
   └────────────────┘

(Pas de flèche entre KV et Supabase. Volontaire.)

┌──────────────────┐
│ Notion (externe) │ ← tracking physique
└──────────────────┘
```

## 1. `catalog.json` (build artifact)

Généré au build local par `loan/scripts/build-catalog.ts`. Contient
exactement ce dont la page a besoin sans recontacter Supabase.

Filtre source :
```sql
SELECT … FROM coins
WHERE face_value = 2
  AND cross_refs->>'numista_id' IS NOT NULL
  AND jsonb_array_length(images) > 0
ORDER BY country, year, eurio_id;
```

Schéma JSON (par pièce) :
```ts
type CatalogCoin = {
  eurio_id: string
  country: string
  year: number
  face_value: 2
  is_commemorative: boolean
  issue_type: IssueType | null
  theme: string | null
  design_description: string | null
  mintage: number | null
  images: string[]            // chemins relatifs : /coins/{eurio_id}/0.jpg
  cross_refs: {
    numista_id?: string
    wikipedia?: string
    lmdlp?: string
    [k: string]: string | undefined
  }
  personal_owned: boolean     // figé au build
  market_prices?: {
    ebay_median?: number
    monnaie_de_paris?: number
    fetched_at: string
  }
}

type Catalog = {
  generated_at: string
  count: number
  coins: CatalogCoin[]
}
```

### Images

**Copie locale** dans `loan/public/coins/{eurio_id}/{idx}.{ext}` au
build, **telles quelles**, sans resize ni recompression. Pour chaque
coin :

1. Télécharger depuis Supabase Storage avec la clé service role.
2. Écrire dans `loan/public/coins/{eurio_id}/0.{ext}` (extension
   préservée), `1.{ext}`, …
3. Réécrire `images: [...]` en chemins relatifs
   `/coins/{eurio_id}/0.{ext}`.

Avantage : zéro egress Supabase Storage côté visiteurs. Tout est
servi par le CDN Vercel. Les images sources sont déjà raisonnablement
légères, l'expérience reste correcte même en mauvaise connexion — on
ne s'embête pas avec une chaîne de transformation `sharp`.

## 2. Vercel KV — claims + admin overrides

KV ne supporte pas de schéma — on définit nos clés à la main.

### Clés

| Clé | Type | Valeur |
|---|---|---|
| `users` | set | `{ userId, … }` (index global) |
| `user:{userId}` | hash | `{ id, name, emoji, created_at }` |
| `user:{userId}:claims` | set | `{ eurio_id, … }` (les pièces que **l'ami** dit avoir) |
| `user:{userId}:lent` | set | `{ eurio_id, … }` (pièces que l'ami m'a **effectivement prêtées**, coché par moi admin) |

`claims` = ce que l'ami a déclaré (lui seul l'écrit).
`lent` ⊆ `claims` en pratique mais on n'enforce pas : c'est un calque
admin que je manipule depuis `/admin`, redondant avec Notion mais
pratique pour avoir une vue rapide par ami.

### Mutations visiteur

- **Créer un user** :
  ```
  HSET user:abc123 id abc123 name "Thomas" emoji "🦊" created_at <iso>
  SADD users abc123
  ```
- **Claim une pièce** :
  ```
  SADD user:abc123:claims FR-2024-EU-CIRC
  ```
- **Un-claim** :
  ```
  SREM user:abc123:claims FR-2024-EU-CIRC
  ```

L'utilisateur ne touche **jamais** au set `:rejected`.

### Mutations admin (`/admin`)

- **Marquer comme prêtée** (l'ami me l'a effectivement remise IRL) :
  ```
  SADD user:abc123:lent FR-2024-EU-CIRC
  ```
- **Démarquer** (rendue, ou erreur de saisie) :
  ```
  SREM user:abc123:lent FR-2024-EU-CIRC
  ```

Note : on ne supprime jamais d'un user `:claims`. C'est sa propre
déclaration. Le set `:lent` est un calque admin distinct.

Workflow combiné, par exemple pour Thomas (12 claims) :
- Il déclare 12 pièces dans `:claims`.
- IRL il m'en prête 7 → je coche 7 lignes dans `/admin` →
  `:lent` contient 7 ids.
- Header `/admin` affiche `7/12 prêtées` pour Thomas.
- Pour chaque pièce que je reçois physiquement, je vais aussi
  cocher `lent_to_me` dans Eurio admin `/coins` (côté Supabase) —
  c'est ce qui alimente le filtre training.

### Lecture

- Visiteur (`GET /api/me/claims`) : `SMEMBERS user:{me}:claims`.
- Admin (`GET /api/admin/overview`) :
  - `SMEMBERS users` → liste des userIds
  - Pour chaque user : `HGETALL user:{id}` + `SMEMBERS user:{id}:claims`
    + `SMEMBERS user:{id}:lent`
  - Renvoie une vue groupée par ami pour l'UI `/admin`, avec un
    compteur `lent_count / claims_count` par ami pour le header.

### Volume

- 508 pièces × ~30 amis × 5 claims = ~150 entries.
- Free tier Vercel KV : 30k commands/mois. Très large.

## 3. Supabase — `coins.lent_to_me`

**Pas** de table `coin_loans`. Une simple colonne booléenne sur
`coins`, dans le même esprit que `personal_owned`.

### Migration

`supabase/migrations/YYYYMMDD_coins_lent_to_me.sql` :

```sql
-- Migration: coins.lent_to_me (admin signal "I have access to test this coin")
-- Date: TBD
--
-- Context:
--   Friends lend 2€ coins via the public /loan Vercel site, but the
--   loan tracking (who lent what, returned or not) lives in Notion,
--   not here. The admin /coins page only needs a binary signal:
--   "do I currently have physical access to this coin for ML training
--   or testing?". Toggled by hand on the coin card, alongside
--   personal_owned.
--
--   Combined semantics: personal_owned OR lent_to_me => "testable".

ALTER TABLE coins
  ADD COLUMN IF NOT EXISTS lent_to_me boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_coins_lent_to_me
  ON coins(eurio_id) WHERE lent_to_me;

COMMENT ON COLUMN coins.lent_to_me
  IS 'True iff a friend has physically lent this coin to the admin.
      Toggled manually from /coins admin card (third checkbox alongside
      personal_owned). Loan tracking (lender, dates, return) lives in
      Notion — this column is only the binary "currently testable" flag.';
```

### Filtre admin `/coins`

Dans `admin/packages/web/src/features/coins/pages/CoinsPage.vue`, on
ajoute :

- Une 3e checkbox sur la card (à côté de `personal_owned`).
- Un chip filtre `loan: 'with' | 'without' | null`.
- Un chip filtre dérivé `testable: 'yes' | 'no' | null` =
  `personal_owned OR lent_to_me`. Pratique pour la composition des
  rounds d'entraînement.

## 4. Pourquoi pas de table `coin_loans`

Initialement prévue, abandonnée parce que :

1. Les claims KV sont des **déclarations volontaristes** des amis ;
   les rapatrier dans Supabase donnerait l'illusion d'un état canonique
   alors qu'il faut encore valider IRL.
2. Le tracking physique est mieux servi par Notion (j'y ai déjà
   l'habitude, c'est un workflow ops, pas du data ML).
3. Une seule colonne `lent_to_me` suffit pour le besoin réel
   (composition du candidate pool training).
4. Moins de code, moins de scripts, moins de désynchros possibles.
