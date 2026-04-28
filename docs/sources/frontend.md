---
title: Frontend — page admin /sources
date: 2026-04-26
status: draft
---

# Frontend — page admin `/sources`

## Référence design

**Source de vérité** : pages admin existantes (en particulier
`admin/packages/web/src/features/training/pages/TrainingPage.vue`). On
réutilise **strictement** le même langage visuel — aucune nouvelle primitive,
aucune librairie supplémentaire.

### Tokens utilisés (cf. `shared/tokens.css` + `tailwind.config.ts`)

| Usage | Token / classe |
|---|---|
| Surface de page | `bg-background` (Tailwind, mappé `--surface`) |
| Card | `rounded-lg border` + `border-color: var(--surface-3); background: var(--surface)` |
| Title h1 | `font-display text-2xl italic font-semibold` + `color: var(--indigo-700)` |
| Sous-titre | `text-sm` + `color: var(--ink-500)` |
| Label tabulaire | `font-mono text-xs uppercase tracking-wider` + `color: var(--ink-500)` |
| Valeur | `font-mono text-lg font-medium` + `color: var(--ink)` |
| Status pill (success) | `rounded-full border px-3 py-1 text-xs` + `border-color: var(--success); color: var(--success); background: color-mix(in srgb, var(--success) 6%, var(--surface))` |
| Idem warning / danger | substituer `var(--warning)` / `var(--danger)` |
| Bouton primaire | `bg-ink text-surface` (cf. bouton "Réessayer" `TrainingPage.vue:451`) |
| Banner d'alerte | `rounded-lg border-2 border-dashed px-5 py-6 text-center` + `border-color: var(--danger)` |
| Padding page | `p-8` |
| Espacement vertical sections | `mb-6` |

### Composants Vue à réutiliser

- `lucide-vue-next` pour les icônes (`Database`, `RefreshCw`, `AlertTriangle`,
  `TrendingUp`, `TrendingDown`, `Wifi`, `WifiOff`, `Clock`, `Copy`)
- Pattern poller : `usePoller` de `features/training/composables/useTrainingApi.ts`
- État `apiStatus` : `'checking' | 'online' | 'offline'`, banner offline
  identique à `TrainingPage.vue:437-457`

## Layout

8 cartes, grille 2-col, regroupées visuellement par section (sous-titres
`font-mono uppercase tracking-wider`) :

```
┌────────────────────────────────────────────────────────────────────────┐
│ Sources                                            ML API connectée 🟢 │
│ Panneau de contrôle de la chaîne d'ingestion                          │
├────────────────────────────────────────────────────────────────────────┤
│ NUMISTA · QUOTA MENSUEL PARTAGÉ — 1247 / 1800 (69%)                   │
│ ┌─ Match ───────────────┐  ┌─ Enrichissement ────────┐                │
│ │ API · 🟢 healthy      │  │ API · 🟡 warning        │                │
│ │ Cadence cible : 14j   │  │ Cadence cible : 30j     │                │
│ │ ...                   │  │ ...                     │                │
│ └───────────────────────┘  └─────────────────────────┘                │
│ ┌─ Images ──────────────┐                                             │
│ │ ...                   │                                             │
│ └───────────────────────┘                                             │
├────────────────────────────────────────────────────────────────────────┤
│ MARCHÉ                                                                │
│ ┌─ eBay Browse ─────────┐                                             │
│ │ API · 🟢 healthy      │                                             │
│ │ Cadence cible : 30j   │                                             │
│ │ ...                   │                                             │
│ └───────────────────────┘                                             │
├────────────────────────────────────────────────────────────────────────┤
│ ÉDITORIAL & RÉFÉRENCE                                                 │
│ ┌─ LMDLP ───────────────┐  ┌─ Monnaie de Paris ──────┐                │
│ │ Scrape · 🟢 healthy   │  │ Scrape · 🟢 healthy     │                │
│ │ Cadence cible : 90j   │  │ Cadence cible : 90j     │                │
│ └───────────────────────┘  └─────────────────────────┘                │
│ ┌─ BCE ─────────────────┐  ┌─ Wikipedia ─────────────┐                │
│ │ Cadence cible : 90j   │  │ Cadence cible : 365j    │                │
│ └───────────────────────┘  └─────────────────────────┘                │
└────────────────────────────────────────────────────────────────────────┘
```

Grille : `grid grid-cols-1 lg:grid-cols-2 gap-4`. À 1400px+ (container
shadcn `2xl: 1400px`) on garde 2 colonnes — pas de 3-col, ça compresse trop le
contenu de chaque carte.

### Bandeau quota partagé Numista

Les 3 cartes Numista partagent le même quota mensuel. Plutôt que d'afficher
trois fois la même progress bar, on met **un bandeau au-dessus de la
section** qui montre la consommation globale, et chaque carte Numista affiche
juste sa cadence + son delta (pas de progress bar dans la carte). Cohérent
avec le `quota_group: 'numista'` dans le contrat backend.

Pour les 5 autres cartes (eBay, LMDLP, MdP, BCE, Wikipedia), la progress bar
quota reste **dans** la carte (eBay) ou est remplacée par "Pas de quota"
(scrapes HTML).

## Anatomie d'une carte source

Hauteur : ~280px par carte (toutes les cartes ont la même hauteur, alignement
visuel propre).

```
┌─────────────────────────────────────────────────────┐
│ [icon] Numista                          🟢 healthy  │  ← header carte
│        API · monthly quota                          │
├─────────────────────────────────────────────────────┤
│ QUOTA MENSUEL · AVR 2026                            │  ← bloc 1
│ ████████████████████░░░░░░░░░  69%                  │  ← progress bar
│ 1247 calls · 553 restants                           │
├─────────────────────────────────────────────────────┤
│ DERNIER FETCH                       COUVERTURE      │  ← bloc 2 (2 colonnes)
│ il y a 13 jours                     562 / 1240      │
│ 2026-04-13 · match                  45%             │
│ ↗ +3 pièces détectées                               │
├─────────────────────────────────────────────────────┤
│ go-task ml:numista:match            [ 📋 Copier ]   │  ← bloc 3 (CLI hint)
└─────────────────────────────────────────────────────┘
```

### Status pill (top-right)

3 variantes :

| State | Couleur | Texte |
|---|---|---|
| `healthy` | `--success` | "healthy" |
| `warning` | `--warning` | reason court (ex: "quota 92%") |
| `error` | `--danger` | reason court (ex: "quota épuisé") |

Hover → tooltip avec `health_reason` complet.

### Progress bar quota

- Track : `bg-surface-2` ou similaire
- Fill : couleur dégradée selon `pct_used` :
  - 0–70% : `var(--success)`
  - 70–90% : `var(--warning)`
  - 90+% : `var(--danger)`
- Hauteur 8px, `rounded-full`
- Pour Numista, hover → breakdown par clé (2 clés actuellement)

### Delta indicator

Pour eBay :
```
↗ +1.2% P50 (médiane)        ← icône TrendingUp + couleur success/danger
112 stables · 4 nouvelles
```

Pour les autres (delta de pièces uniquement) :
```
↗ +3 nouvelles pièces
```

Si `delta = null` (premier run, ou pas de run précédent comparable) :
```
— pas de delta calculable
```

### CLI hints — section multi-commandes (V1 read-only)

Le bloc CLI **n'est pas une commande unique** : chaque source a typiquement
plusieurs scripts pertinents (run, dry-run, list, status, reset). On les
liste tous, organisés en accordéon ou liste verticale dans le bas de la
carte.

Format pour chaque entrée :

```
┌─────────────────────────────────────────────────────┐
│ ▶ Run complet                          [ 📋 Copier ]│
│   go-task ml:scrape-ebay                            │
│   Enrichit toutes les commémos avec numista_id      │
│   → Insère N lignes dans coin_market_prices         │
│   → Écrit ml/state/price_snapshots/ebay_<period>.json│
├─────────────────────────────────────────────────────┤
│ ▶ Dry run (test)                       [ 📋 Copier ]│
│   go-task ml:scrape-ebay -- --limit 5 --dry-run     │
│   Test sur 5 pièces, n'insère rien en base          │
│   → Affiche les stats agrégées en stdout            │
├─────────────────────────────────────────────────────┤
│ ▶ Status quota                         [ 📋 Copier ]│
│   go-task ml:quota:status -- --source=ebay          │
│   Dump JSON du quota courant                        │
└─────────────────────────────────────────────────────┘
```

Style :
- Chaque entrée séparée par `border-t` léger
- Titre kind (`Run complet`, `Dry run`, etc.) en `text-sm font-medium`
- Commande en `font-mono text-xs` fond `var(--surface-1)` `rounded-sm px-2 py-1`
- Description en `text-xs` color `var(--ink-500)`
- Outcome en `text-xs` color `var(--ink-500)` préfixé `→`
- Bouton "Copier" : icône `Copy` de lucide, tooltip "Copié ✓" pendant 2s
  après clic

En V2 chaque entrée gagne en plus un bouton "Lancer →" qui pousse un job —
voir `v2-triggering.md`.

### Indicateur de cadence visible

Sous le bloc "DERNIER FETCH", on rend explicite la cadence cible :

```
DERNIER FETCH
il y a 13 jours · 2026-04-13
Cadence cible : tous les 30 jours
```

Si `overdue` (= `days_since_last_run > 1.5 × expected_cadence_days`), le
texte "Cadence cible" passe en `var(--warning)` et un badge "⚠ overdue"
apparaît à côté du status pill principal.

## Routing & nav

### Ajout dans `app/nav.ts`

Section "Système" (existante avec "Audit log") :

```typescript
{
  title: 'Système',
  items: [
    { id: 'audit', label: 'Audit log', icon: ClipboardList, route: '/audit' },
    { id: 'sources', label: 'Sources', icon: Database, route: '/sources' },
  ],
},
```

Icône `Database` de `lucide-vue-next` (cohérent : sources = bases de
données externes).

### Route

`app/router.ts` :

```typescript
{
  path: '/sources',
  component: () => import('@/features/sources/pages/SourcesPage.vue'),
  meta: { title: 'Sources' },
}
```

## Structure de fichiers

```
admin/packages/web/src/features/sources/
├── pages/
│   └── SourcesPage.vue          # page principale
├── components/
│   ├── SourceCard.vue            # une carte
│   ├── QuotaProgressBar.vue      # barre + breakdown par clé (Numista)
│   ├── DeltaIndicator.vue        # ↗/↘ + texte
│   └── CliHintBlock.vue          # commande + bouton copier
└── composables/
    └── useSourcesApi.ts          # fetch, polling, types TS
```

## Composables

```typescript
// useSourcesApi.ts
import { ML_API } from '@/features/training/composables/useTrainingApi'

export type SourceStatus = { ... }  // mirror du type backend

export async function fetchSourcesStatus(): Promise<SourceStatus[]> {
  const resp = await fetch(`${ML_API}/sources/status`)
  if (!resp.ok) throw new Error(`status ${resp.status}`)
  return resp.json()
}
```

Polling 10s avec `usePoller` réutilisé depuis `useTrainingApi.ts`.

## États edge

| État | Affichage |
|---|---|
| ML API offline | Banner identique `TrainingPage.vue:437-457` (rouge dashed) |
| Source jamais fetchée (`last_run_at = null`) | "Pas encore de fetch · `[copy command]`" |
| Quota épuisé | Status pill rouge "exhausted", progress bar rouge full |
| Delta `swing_warning` | Status pill orange + tooltip "swing de ±X% détecté" |
| Couverture 0% | Pas d'erreur, juste affiché tel quel |

## Pas de mock séparé — génération directe en Vue

R1 (proto-first) ne s'applique qu'au design Compose Android. L'admin n'a pas
cette contrainte. L'agent `frontend-design` produit donc **directement les
composants Vue finaux** dans `admin/packages/web/src/features/sources/` avec
des données mockées inline (constants en TS) — le backend `/sources/status`
viendra ensuite et remplacera juste l'origine des données.

Bénéfice : pas de double-implémentation HTML → Vue, pas de drift entre mock
et code final.

L'agent doit :
- Reprendre strictement les tokens et patterns admin existants (cf. plus haut)
- Produire la page + les composants listés en "Structure de fichiers"
- Inclure des données mockées couvrant les 8 cartes et les 3 états santé
- Démontrer un delta de prix positif (eBay) et un overdue (par ex. Wikipedia
  qui n'a pas été refetché depuis 400j)

## Travail à faire

1. **Agent frontend-design** : génère page + composants Vue avec données
   mockées dans `admin/packages/web/src/features/sources/`
2. Ajout nav + route (`Database` icône lucide)
3. Endpoint `/sources/status` côté backend (cf. `backend.md`)
4. Branchement composable sur le vrai endpoint (remplace les mocks par
   `fetchSourcesStatus()`)
5. Test manuel : `go-task admin:dev` + `go-task ml:api`, vérifier 8 cartes
   avec données réelles
