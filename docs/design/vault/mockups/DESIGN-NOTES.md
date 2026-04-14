# Coffre — Design notes

> Mockups haute-fidélité du Coffre Eurio. Viewport 390×844. Datés 2026-04-13.
> Fichiers : `01-empty-vault` → `07-remove-confirmation` + `index.html` (landing).
> Stylesheet unique : `_shared.css`. Inspiration éditoriale/musée, "patrimoine silencieux".

---

## 1. Direction aesthétique

| Axe | Choix | Pourquoi |
|---|---|---|
| **Ton** | Éditorial refined, museum catalog | Opposé à Duolingo. L'user est collectionneur, pas gamer. |
| **Display** | Fraunces (serif variable, optical sizing) | Gravitas patrimoniale, chiffres monétaires qui respirent. |
| **UI** | Inter 400/500/600, tabular nums systématique sur les valeurs | Neutre, lisible, chiffres alignés verticalement. |
| **Mono** | JetBrains Mono (landing only) | Numéros de planche dans l'index. |
| **Hiérarchie couleur** | Indigo 700 dominant pour chiffres/titres, or 500 parcimonieux (halos set complet + accents hunt banner), grays warm pour chrome | L'or n'apparaît **que** pour marquer la complétude. C'est la récompense visuelle. |
| **Surface** | Warm off-white `#FAFAF8` → `#F4F3EE`, pas de blanc pur | Sensation papier / vélin, jamais "SaaS Figma". |
| **Motion** | (Non animé dans les mockups mais documenté) Stagger fade-in des tuiles 40ms, haptique sur long-press, sheet spring 300ms | Jamais confetti, jamais bounce exagéré. |

### Le one thing à retenir
La **typographie du 247 €** en Fraunces 60px display avec le `€` réduit à 40px en light weight : c'est la signature du Coffre. Le chiffre devient un objet, pas un label. Équivalent de la façade d'un musée, pas d'un dashboard de banque.

---

## 2. Hiérarchie des composants (structure commune)

```
screen/
├── status-bar (54dp) — jamais cachée
├── content/
│   ├── scroll/
│   │   ├── vault-header       — eyebrow + value-total + delta chip
│   │   ├── stats-strip        — 3 colonnes, séparateurs 1px, tabular nums
│   │   ├── toolbar            — search-bar + chip row filters + sort + segmented toggle
│   │   ├── [group-header]     — "Avril 2026" divider italic fraunces
│   │   ├── coin-grid | coin-list
│   │   └── ...
│   └── bottom-area (absolute, z=10)
│       ├── nav (84dp, blur 18px)    — 4 slots + FAB central
│       └── fab (64dp, top:-26)      — scan, gradient indigo + halo or flou
└── home-indicator
```

Layers spécifiques :
- **sheet** (filters) : `.sheet-backdrop` z=20 + `.sheet` z=21, max-height 85%, radius 24 top only.
- **dialog** (remove) : centered card 24dp margin, red destructive icon bubble.
- **context-menu** (long press) : rendu dark (indigo-900 + backdrop blur 12), distinct du chrome light.
- **toast** : dark indigo, action gold label uppercase. Reste 5s, swipeable.

---

## 3. Interactions documentées

| Geste | Cible | Effet | Feedback |
|---|---|---|---|
| **Tap tuile** | Grid/list | Ouvre fiche pièce (`context = OwnedCoin`) | Scale 0.97 ~80ms |
| **Long press tuile** | Grid | Ouvre context menu flottant : Modifier condition / Ajouter note / Voir la fiche / Retirer | Haptique light + menu fade 120ms |
| **Swipe left sur row** | List | Révèle action rouge "Retirer" derrière | Ouvre directement confirmation dialog |
| **Tap chip filtre** | Toolbar | Ouvre bottom sheet filtres préfocalisé sur la catégorie tappée | Sheet spring in |
| **Tap search bar** | Toolbar | Expand en search actif full-width, reveal bouton Annuler, keyboard up | Sticky header devient search header |
| **Tap segmented grid/list** | Toolbar | Toggle, persist DataStore, LazyVerticalGrid ↔ LazyColumn | Crossfade 200ms |
| **Tap "Voir X pièces"** | Sheet foot | Applique filtres, ferme sheet, scroll top | Sheet slide down |
| **Tap "Annuler" toast** | Toast | Revert delete (insert row avec mêmes IDs) | Toast fade + tuile re-fade in |
| **Tap FAB scan** | Bottom nav | Ouvre écran Scan (tab central) | Overlay caméra |

---

## 4. Data bindings par écran

### 01 — Empty
- Détection : `COUNT(user_collection WHERE owner_user_id=me) == 0`
- CTA scan → Intent scan screen, no-op DB

### 02 — Starter (1-5 pièces)
- Valeur totale : `SUM(COALESCE(cpo.p50_cents, c.face_value_cents))` (fallback silencieux)
- Hunt banner : query la plus petite série incomplète où l'user a ≥ 1 pièce (PRD §5.4 notifications de chasse). Ici "Série française 2 / 8".
- Delta caché si `SUM(value_at_add_cents) < 50 cents` (trop petit pour être significatif) ou si `< 24h` depuis la première pièce.

### 03 — Grid
- Header stats lus depuis 3 requêtes SQL (ou 1 avec `COUNT(DISTINCT country_iso2)`).
- Tuile : `image_obverse_path` OU fallback SVG doré (cas offline / photo manquante).
- Badge `×N` : calcul côté query `COUNT(*) GROUP BY eurio_id HAVING COUNT(*) > 1`. Affiché uniquement si > 1.
- Halo doré : join avec `achievement_state` where `unlocked_at IS NOT NULL AND set.includes(eurio_id)`.
- Groupement par mois : `strftime('%Y-%m', added_at/1000, 'unixepoch')`. Délimiteur italique Fraunces + hairline.

### 04 — List
- Même source, layout row 64dp. Sort par valeur applique `ORDER BY p50_cents DESC NULLS LAST`.
- Delta individuel row : `(p50_cents - value_at_add_cents) / value_at_add_cents`. Si null, afficher tiret `—` neutre.
- Fallback dash `—` affiché en `ink-400` **uniquement** sur la colonne delta (pas sur la valeur absolue, qui a son fallback `face_value_cents`).

### 05 — Filters
- Les pays disponibles dans la sheet = ceux existant dans `coin` table (21 euro + 4 micro-états) pour ne pas surprendre. Compteurs live ("Voir 11 pièces") recalculés à chaque toggle via requête préparée.
- Range années : min/max dynamique `SELECT MIN(year), MAX(year) FROM coin JOIN user_collection`.

### 06 — Search
- Deux sections : "Dans ton coffre" (query LIKE sur `user_collection` joined) et "Dans le catalogue · à chasser" (query LIKE sur `coin` où pas dans la collection). La 2ème section convertit la search bar en moteur de chasse sans rompre le mental model.
- Highlighting `<mark>` : tokens matchés colorisés en `gold-100` background.
- Mode accent-insensitive (FTS4 ou LIKE avec normalisation `unaccent`).

### 07 — Remove
- Warning "cassera le set" : check pré-delete `achievement_state WHERE unlocked_at IS NOT NULL AND set.contains(eurio_id) AND count_remaining_copies == 1`.
- Undo : soft-hide 5s, hard delete au dismiss du toast. Plus simple que soft-delete flag pour la v1 (PRD roadmap).

---

## 5. États edge traités

| Cas | Traitement |
|---|---|
| **Prix inconnu** | Fallback `face_value_cents` dans la valeur totale ET dans la row. Jamais `—` sur la valeur. `—` uniquement sur la colonne delta. |
| **Delta négatif** | Chip rouge pâle `--red-500` avec flèche bas (pas rouge vif, on ne stresse pas le collectionneur). Ici visible sur 1 € Espagne (-4%). |
| **Multi-exemplaires** | Badge pill top-right en grille, inline `× 3` en liste. Compte unique dans le compteur "pièces" (chaque exemplaire = 1). |
| **Set complet** | Halo `--gold-500` glow + border + overlay gradient sur la tuile. En liste : anneau or sur la mini-coin. |
| **Collection > 500 pièces** | LazyVerticalGrid pagine invisible, groupement par mois rend le scroll parcourable. Question ouverte : virtualization avec indexed scrollbar ? |
| **Photo manquante (ajout manuel)** | SVG de pièce générique (disc doré/cuivre/bicolor selon face_value) avec glyph "€" ou centimes. Pas de placeholder gris vide. |
| **Offline complet** | Tout fonctionne. Seuls les deltas et la fraîcheur prix dépendent du sync, et échouent silencieusement. |
| **Aucune valeur connue** | Header affiche `"à calculer"` + link "Pourquoi ?" (non visible ici, documenté dans vault/README.md). |

---

## 6. Tokens (extraits de `_shared.css`)

```
--indigo-700: #1A1B4B   primary
--gold-500:   #C8A864   halo sets complets, accents hunt banner
--surface-0:  #FAFAF8   fond écran
--surface-1:  #F4F3EE   chips, search bar inactive, dialog coin card
--ink-400:    #7A7B90   labels secondaires
--green-600:  #2FA971   delta positif
--red-500:    #D87878   delta négatif (pâle, pas alarmant)
--red-600:    #D14343   destructive actions uniquement

--font-display: Fraunces (opsz auto, 300-600)
--font-ui:      Inter (300-700)
--r-sm:  8px   tiles
--r-md:  12px  cards, buttons default
--r-xl:  24px  bottom sheets
```

---

## 7. Spec composants à porter en Compose

- **`ValueTotal`** : reçoit `cents: Long`, format via `NumberFormat` fr-FR, sépare la partie entière du `€` en 2 Text composables.
- **`StatsStrip`** : Row avec 3 `Stat(value, label)`, séparateurs 1px via `Modifier.drawBehind`.
- **`CoinTile`** : `Box(Modifier.aspectRatio(1/1.15f).clip(RoundedCornerShape(8)))` avec `AsyncImage(obversePath)` fallback sur `CoinDiscPlaceholder(faceValue)`. Halo set complet via `Modifier.border(1.dp, Gold500) + outer drawShadow` custom.
- **`VaultTopBar`** : colonne header + stats strip, collapse partiel au scroll (le chiffre rétrécit de 60→40 en Fraunces, option v1.1).
- **`FiltersSheet`** : `ModalBottomSheet` M3, contenu = `LazyColumn` par sections, CTA footer sticky `Surface(tonalElevation=3)`.
- **`UndoToast`** : `Snackbar` custom host, action label en gold, 5s, dismissible par swipe.

---

## 8. Questions ouvertes à trancher avec Raphaël

1. **Vue par set** : doit-on introduire un 3ème mode de vue "par set" en plus de grid/list ? Risque : surcharge UX du toggle ; bénéfice : gamification organique. Recommandation : pas v1, accessible via un achievement card dans le Profil.
2. **Groupement grille** : garder le groupement par mois ou le rendre configurable (par pays / par valeur faciale / par date) ? Actuellement hardcodé par mois — simple et lisible, mais peu utile au-delà de 200 pièces.
3. **Hunt banner placement** : en starter vault seulement, ou systématique en top de la grille tant qu'il y a un set incomplet à < 3 pièces manquantes ? Recommandation : systématique avec condition seuil.
4. **Delta négatif chip** : rouge pâle ou juste gris ? On a choisi rouge pâle pour rester factuel sans stresser. À valider.
5. **Prix inconnu delta** : afficher `—` ou cacher complètement la colonne ? Mockup liste utilise `—` neutre. Compose devrait ajouter `ContentDescription` "prix inconnu" pour a11y.
6. **Context menu long-press** : documenté en section Interactions mais non mockupé (il apparaîtrait au-dessus de la tuile en flottant). À ajouter en mockup si le skill Kotlin rencontre des frictions à l'impl.
7. **FAB scan** : toujours central et surélevé, ou se cache au scroll down pour libérer l'écran ? Recommandation : sticky permanent, respecte PRD §6 "scan à un tap".
8. **Export PDF / Share** : l'icône download top-right du header déclenche quoi exactement — sheet bottom avec choix (PDF / image / lien) ou direct PDF + share sheet Android ? À trancher avec la stratégie marketplace v2.

---

## 9. Ce qui n'est **pas** dans les mockups (hors scope)

- **Onboarding** (autre agent) — on suppose que le Coffre est accédé après première ouverture réussie.
- **Scan** — seulement le FAB et le CTA empty state sont présents ; l'écran caméra est hors scope.
- **Fiche pièce** — on pointe vers elle via tap/row mais on ne la dessine pas.
- **Profil** — bottom nav item présent, écran non dessiné.
- **Explorer** — hors scope v1 selon `docs/design/README.md`.

---

Fichiers HTML totalement standalone (une seule dépendance CSS partagée). Aucun JS. Device frame simulé pour preview desktop ; le rendu final Compose sera edge-to-edge sans la mockup de bezel.
