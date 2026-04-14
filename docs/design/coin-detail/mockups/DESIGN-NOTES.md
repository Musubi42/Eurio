# Fiche pièce — Design notes

> Notes d'accompagnement des mockups `coin-detail/mockups/`. Ces notes ne remplacent pas le README.md de la vue (qui reste l'ADR) — elles documentent les choix visuels, les bindings de chaque champ, et les comportements dynamiques.
>
> **Date** : 2026-04-13
> **Viewport cible** : 390 × 844 (iPhone 14/15 logical)
> **Framework cible** : Jetpack Compose

---

## 1. Direction esthétique

**Museum catalogue meets precision numismatics.** La fiche est posée comme une carte de cartel de musée : hiérarchie sobre, typographie éditoriale, hairlines au lieu de cadres, beaucoup de vide autour de la pièce, jamais de criard.

- **Hero** : fond indigo nuit (`#0E0E1F` → `#15163A`) pour faire ressortir la pièce comme un objet sous vitrine. Variante crème (`#F5F3EC`) uniquement pour `ReferenceOnly` — signalement subtil que ce n'est pas une instance possédée.
- **Body** : papier crème `#FAFAF8` avec rythme de sections séparées par des hairlines 1px (`rgba(14,14,31,0.08)`). Numéro de section en JetBrains Mono doré — rappel spécimen.
- **Accent or brossé** `#C8A864` — utilisé avec parcimonie : badge « Nouvelle pièce », marqueur médiane, point actuel sur la courbe, set débloqué. Jamais sur le CTA d'ouverture (indigo) sauf `ScanResult` où l'or indique le moment-clé.
- **Grain très léger** en overlay du hero (SVG feTurbulence) — texture de papier ancien.

## 2. Typographie

| Usage | Police | Size / weight |
|---|---|---|
| Nom de la pièce (display) | **Fraunces italic 500** | 32/1.05 letterspacing -0.02em |
| Valorisation chiffres | **Fraunces tabular 400** | 44/1, italic pour les tildes |
| Étiquettes de section | Inter 600 | 10/1.4 uppercase letterspacing 0.22em |
| Labels spec-sheet | Inter 600 | 10 uppercase letterspacing 0.14em |
| Valeurs data | Inter 500 tabular | 13 |
| Numérotation sections / fresh / axes | **JetBrains Mono 500** | 9–10 letterspacing 0.08–0.18em |
| Citations / projection text | **Fraunces italic 400** | 14 |

Le mélange Fraunces (serif éditorial avec variant SOFT/WONK) + Inter + JetBrains Mono donne trois voix distinctes : le nom respire, les données sont propres, les méta chuchotent.

## 3. Structure 7 sections (vue canonique)

```
┌─ HERO ─────────────────────────┐
│ specimen N° · context pill      │  74px from top, z-index 3
│ corner crosshairs               │  decorative museum crop marks
│ coin stage (centered)           │  220–230px disc, radial gradient metal
│ user polaroid (if ScanResult /  │  absolute, rotation ±3°, z-index 4
│   OwnedCoin, tilted)            │
│ face-toggle (recto/verso)       │  glass pill, bottom-right
└─────────────────────────────────┘

┌─ BODY (paper) ─────────────────┐
│ 01 Identité     · flag + meta + name display + rarity
│ 02 Valorisation · range P25-P75 + delta + distribution bar
│ 03 Historique   · sparkline + stats + extend CTA
│ 04 Projection   · indigo card + range + disclaimer
│ 05 Sets liés    · list 44px rows + progress bars
│ 06 Détails      · dl specification sheet
└─────────────────────────────────┘

[CTA bar — floating, blur backdrop, safe-area bottom]
```

La numérotation `01 / 02 / …` est affichée (pas seulement commentaire) — vocabulaire museum card. Elle persiste dans tous les contextes.

## 4. Variations par contexte

Même structure, paramétrée. Compose pseudocode :

```kotlin
@Composable
fun CoinDetailScreen(vs: CoinDetailViewState) {
    Scaffold(bottomBar = { CtaBar(vs.context) }) {
        LazyColumn {
            item { CoinHero(vs) }
            item { IdentitySection(vs) }
            // only OwnedCoin : ownership strip
            if (vs.context is Context.OwnedCoin) item { OwnershipStrip(vs.context) }
            // only OwnedCoin : photo compare
            if (vs.context is Context.OwnedCoin) item { PhotoCompareSection(vs) }
            item { ValuationSection(vs.market) }
            item { PriceHistoryChart(vs.priceHistory, vs.faceValueCents) }
            item { ProjectionCard(vs.priceHistory, vs.rarityTier) }
            // only commemorative common : country variants grid
            if (vs.nationalVariants.isNotEmpty()) item { CommonIssueSection(vs) }
            item { LinkedSetsSection(vs.linkedSets) }
            item { DetailsSpecSheet(vs) }
        }
    }
}
```

Tableau de différences :

| Élément | ScanResult | OwnedCoin | ReferenceOnly |
|---|---|---|---|
| Hero background | indigo nuit | indigo nuit | crème paper |
| Specimen tag N° | affiché | affiché | affiché |
| Context pill | `Nouvelle pièce` (gold pulse) | `Dans votre coffre` (glass check) | `Fiche référence` (muted) |
| User polaroid | tilted -3° center-bottom | tilted +5° bottom-right | absent |
| Ownership strip (date/état/delta) | absent | affiché | absent |
| Photo compare (user vs BCE) | absent | affiché | absent |
| `ajout` marker sur sparkline | absent | cercle or + label à la date d'ajout | absent |
| Stats sparkline | min/médian/max | à l'ajout / médian 12m / actuel | min/médian/max |
| CTA primary | **gold** `Ajouter au coffre` | ghost `Retirer du coffre` | indigo `Ajouter manuellement` |
| CTA secondary | re-scan | share | — |
| Statusbar tint | on-dark | on-dark | on-light |

## 5. Spécifications composants

### 5.1 Coin stage
- Disque 220–230px, `radial-gradient` à 30% 28% pour la highlight, rim `inset dashed`, inner disc à 26px de l'extérieur.
- Ombre portée `0 30px 60px -10px rgba(0,0,0,0.55)` + `0 10px 20px` secondaire pour l'ancrage.
- Motif central : Fraunces 76px italic, la face value en gros + sub-label `EURO · 2012` en Inter mono uppercase.
- Deux variantes métal : `or nordique` (2€/1€) et `copper` (10c/5c/2c/1c). Commuter la classe `.copper`.

En Compose : une `Canvas` pour le disque (dégradé radial + cercle dashed) + un `Image` par-dessus pour l'asset BCE/Numista quand disponible. Le placeholder Fraunces ne sert que quand les deux sources échouent.

### 5.2 User polaroid
- 112 × 140 px, padding `8 8 24 8` pour la zone « blanche » du bas.
- Rotation `transform: rotate(-3deg)` sur `ScanResult`, `+5deg` sur `OwnedCoin` (asymétrie voulue).
- Label `JetBrains Mono 8px` en bas — fait penser à un Polaroid SX-70.
- Ombre 2 couches (proche + lointaine) pour le détacher du fond indigo.

### 5.3 Face toggle
- Pill glass-morphism `backdrop-blur(18px)` sur fond `rgba(14,14,31,0.55)`.
- État actif : pastille or `#C8A864`, label indigo.
- Si une seule face est disponible (cas Numista partiel), l'autre bouton passe en `opacity: 0.35` + `pointer-events: none` (grisé, pas caché — pour que l'user sache qu'il manque quelque chose).

### 5.4 Valuation range
- Les chiffres sont en Fraunces tabular pour éviter le jitter entre `8 € — 15 €` et `14 € — 22 €`.
- Le tilde « — » entre les deux chiffres est un `–` em-dash italique, petit (20px), couleur `ink-4`. Ce n'est pas juste un espace.
- `€` en couleur `gold-deep` `#8F7637` — rappelle que la monnaie est le sujet.
- Badge delta « +X % vs faciale » : fond `rgba(200,168,100,0.15)`, le delta « +X% /3m » : fond `rgba(47,169,113,0.1)`. Deux palettes distinctes pour deux deltas distincts.

### 5.5 Distribution bar
- Rail 2px `cream-3`, fill 2px `ink`, médiane = pastille or 8px bordée de crème 2px.
- Labels P25/P75 en JetBrains Mono 9px alignés aux extrêmes. Range complet (ex : 2→22€) en dessous.
- Rappel visuel que la médiane n'est pas au milieu géométrique — la distribution eBay est souvent asymétrique.

### 5.6 Sparkline (PriceHistoryChart · Loaded ≥ 6 points)
- SVG inline, `viewBox="0 0 340 68"`, `preserveAspectRatio="none"` pour s'étirer.
- Ligne : indigo `#1A1B4B` 1.5px round. Fill sous la courbe en dégradé indigo 14% → 0%.
- Dernier point : cercle 3px or bordé de crème 1.5px — ancre le « maintenant ».
- Sur `OwnedCoin`, un cercle bordé or au point « ajout » + texte JetBrains Mono 7px avec la valeur.
- Axes X en 4 labels `MMM YY` JetBrains Mono uppercase.
- Stats dessous : grille 3 colonnes `min / médian / max` dans une pilule `cream-2 radius 12`.

### 5.7 PriceHistoryChart · états gérés

```
state                    visuel
─────────────────────────────────────────────────────────
Loading                  skeleton shimmer, hauteur identique
Empty                    card dashed cream-2 + icône info + "Pas encore de données de marché" + lien "Qu'est-ce que c'est ?"
Loaded(n<6)              sparkline en 3 dots faibles + bandeau explicatif "N points disponibles, 6 minimum"
Loaded(n>=6)             sparkline complète (voir 5.6)
```

Le **skeleton ne doit jamais provoquer de layout shift** — la carte fait 88 + 14 + 44 (stats) + 14 + 44 (bouton) de hauteur constante.

### 5.8 Projection card
- Carte `radius: 24px`, fond `linear-gradient(135deg, #1A1B4B, #15163A)`.
- Cercle or radial en top-right (`-40px` offset) — rappelle la pièce dans son halo.
- Titre « Dans 5 ans » en Inter 9px gold uppercase letterspacing 0.22em.
- Texte d'introduction en Fraunces italic 14px cream-muted — ton de cartel.
- Valeur principale : Fraunces tabular 36px cream, tilde or.
- **Disclaimer obligatoire en bas**, séparé par hairline cream 12% : « Estimation indicative fondée sur N observations eBay. Ceci ne constitue pas un conseil financier. » → directement dérivé de PRD §5.5.
- Si `historySize < 6` : remplacer par une card `cream-2 dashed` avec le texte « Projection disponible après plus d'observations » — pas de demi-projection hasardeuse.

### 5.9 Ownership strip (OwnedCoin only)
- Trois colonnes : Ajoutée | État | Delta, séparées par hairlines verticales 1px 32px.
- Delta coloré selon signe : vert `#2FA971` si positif, rouge pâle `#D87878` si négatif, gris `#8A8A96` si stable.
- Délibérément placé entre le hero et le corps — c'est la première chose qu'on voit après la photo.

### 5.10 Linked sets
- Lignes 44px hauteur, icône `set-icon` 44×44 radius 12, fond crème-2, glyph Fraunces 20px.
- Set débloqué : fond `linear-gradient(gold, gold-bright)`, glyph indigo.
- Barre de progression 60 × 4px à droite, fill indigo (ou gold pour sets débloqués).
- Progression en JetBrains Mono tabular `7 / 21 pièces`.

### 5.11 Details spec-sheet
- `dl` HTML : `dt` label uppercase Inter 10px ink-4, `dd` valeur tabular 13px ink, séparateur hairline 1px en dessous.
- Valeurs inconnues : `dd` en Fraunces italic 400 `ink-4` « Non communiqué » — signalement typographique clair que ce champ est absent. **Jamais de tiret vide.**

### 5.12 Pays participants (émission commune)
- Grille 7 colonnes × 3 rangées = 21 cases.
- Chaque case : drapeau 24×16 + ISO2 JetBrains Mono 8px.
- Drapeau possédé : outline or 2px autour du drapeau, ISO2 vert + bold.
- Progress bar fin dégradé or au-dessus de la grille.
- Section entière sur fond dégradé gold 8% → transparent, full-bleed (marges négatives -24px).
- Footer JetBrains Mono « Bulgarie rejointe le 1ᵉʳ janvier 2026 » — geste éducatif.

### 5.13 CTA bar
- Position fixed bottom, padding `16 20 30` (safe-area), z-index 600.
- Masque `backdrop-blur(14px)` avec mask-gradient pour que le flou s'estompe en haut — pas de frontière nette.
- Boutons pill (radius 100px), hauteur ~52px.
- Primary indigo `#1A1B4B` avec highlight gold interne `linear-gradient(135deg, rgba(200,168,100,0.3), transparent 50%)` pour pas qu'il soit plat.
- Variante gold complète uniquement sur `ScanResult` (le moment-clé).
- Secondary circle 54px cream-2 bordure hairline.

## 6. Data bindings

| UI | Champ ViewState | Source |
|---|---|---|
| `specimen N°` | `eurioId` (formatté uppercase) | Room `coin.eurio_id` |
| Flag | `countryIso2` | Room `coin.country_iso2` |
| Ident meta | `country`, `year`, `faceValueLabel` | Room `coin.country_name`, `.year`, `.face_value_cents/100` |
| Nom display | `theme` ou fallback sur la face value | Room `coin.theme` |
| Description | `designDescription` | Room `coin.design_description` |
| Rarity badge | `rarityTier` | calculé depuis `coin.mintage_total` + règles |
| Valuation range | `market.p25Cents / p75Cents` | Room `coin_price_observation` |
| Median | `market.p50Cents` | idem |
| Samples count | `market.samplesCount` | idem |
| Delta face | `market.deltaVsFaceValuePercent` | calculé `(p50 - faceValue)/faceValue` |
| Delta 3m | `market.trend3m` | idem, pct computed |
| Freshness | `market.sampledAt` | formatté relative time |
| Hero images | `imageObverseSource` / `imageReverseSource` | cascade Room → Supabase Storage → Placeholder |
| Sparkline points | `priceHistory.points[]` | Supabase `source_observations` fetchée à l'ouverture |
| Projection range | calcul régression linéaire sur `priceHistory.points` | `horizon * slope + intercept` ± 2σ × rarityFactor |
| Ajouté le (owned) | `context.addedAt` | Room `user_collection.added_at` |
| État (owned) | `context.condition` | Room `user_collection.condition` |
| Delta (owned) | `market.p50 - context.valueAtAddCents` | calculé |
| Note perso (owned) | `context.note` | Room `user_collection.note` |
| User photo (owned/scan) | `context.userPhotoPath` / `capturedPhotoPath` | FS local |
| National variants | `nationalVariants[]` + intersection avec `user_collection` | Room join |
| Linked sets | `linkedSets[]` | calcul `achievement_state` |
| Spec-sheet | `mintageTotal`, etc. | Room `coin.*` |

Tous les états inconnus sont pris en charge côté ViewModel — les composables ne voient jamais de `null` ambigu.

## 7. États edge (synthèse)

| Cas | Comportement |
|---|---|
| Pas de prix observés | Section valorisation remplacée par empty-card `cream-2 dashed` avec icône + lien « Qu'est-ce que c'est ? ». **La section ne disparaît pas** — elle explique. |
| Historique n < 6 | Sparkline affichée avec 3 dots faibles décoratifs + bandeau « Historique insuffisant. N points · 6 minimum ». |
| Historique n = 0 | Bandeau unique « Pas encore de données de marché ». Projection masquée. |
| Image obverse/reverse absente | Cascade : Room → Supabase → Placeholder generique (disc dashed + face value Fraunces). Specimen tag toujours présent. |
| Une face seulement | Face-toggle montre l'autre face en `opacity: 0.35 pointer-events: none`. Tooltip au long-press « Image non disponible ». |
| Tirage inconnu | `dd` en Fraunces italic `Non communiqué`. |
| Théme null (circulation standard) | Nom display = la face value seule (« 2 euros ») en Fraunces. |
| Émission commune | Section dédiée `02` full-bleed avec grille 21 drapeaux. Sets liés font référence au set « Europa · 21 variantes ». |
| Projection impossible (< 6 points) | Remplacée par card dashed « Projection disponible après plus d'observations ». |

## 8. Interactions

- **Scroll** : toute la page scroll, y compris le hero. La topnav est `sticky` mais transparente (`icon-btn` avec blur).
- **Face toggle (recto/verso)** : tap → swap l'image du coin-stage avec une cross-fade 180ms. En Compose : `AnimatedContent(targetState=selectedFace)`.
- **Tap sur la photo utilisateur (polaroid)** : ouvre un viewer plein écran zoom (pinch-to-zoom).
- **Tap sur « Étendre 5 ans »** : push de `PriceHistoryExpandedScreen` (modal `.modal-screen`), transition `slideInVertically` + fade. Bouton close renvoie en arrière, scroll position conservée.
- **Tap sur une ligne `linked-set`** : push la vue Set (hors scope de ce dossier).
- **Tap sur le CTA « Retirer du coffre »** : bottom-sheet de confirmation (Compose `ModalBottomSheet`). Pas d'irreversible sans confirmation.
- **Long-press sur le specimen tag `N° FR-…`** : copie l'eurio_id dans le presse-papier. Easter egg pour devs/power users.
- **Partage** : share sheet natif Android avec screenshot auto de la fiche (rendu d'un `ComposableView` offscreen).

## 9. Motion & micro-interactions

- **Apparition à l'ouverture** : hero fade-in 250ms, corps stagger de sections 40ms chacune (easing `fastOutSlowIn`).
- **Pastille « Nouvelle pièce »** : pulse du dot toutes 1.6s (déjà en CSS). Stoppe après 3 cycles pour ne pas distraire.
- **Sparkline** : à la première apparition, `path-draw` 600ms (strokeDashOffset) — la courbe se dessine. Seulement la première fois dans la session.
- **Loading → Loaded sparkline** : morph des dots skeleton vers la courbe (cross-fade 300ms). Évite le hard-swap.
- **CTA tap** : scale 0.97 + haptic light.

## 10. Décisions principales (5-7)

1. **Contexte museum card plutôt que fintech dashboard.** Ce choix colore tout : Fraunces italic pour les noms, numérotation `01/02/…`, hairlines, grain, specimen tag, corner crosshairs.
2. **Une vue unique, 4 fragments optionnels.** `CoinDetailScreen(state)` avec `OwnershipStrip`, `PhotoCompareSection`, `CommonIssueSection`, `UserPolaroid` conditionnés par le contexte. Pas trois composables parallèles.
3. **Or = moment. Indigo = base.** L'or est sacralisé pour les moments-clés (nouvelle pièce, set débloqué, dernier point de courbe, médiane de distribution, variantes possédées). Le fond de travail reste indigo nuit + papier.
4. **Jamais d'invention de valeur.** Empty states explicites, dignes, jamais de « 0 € » ni de « — ». Le composant `PriceHistoryChart` est shippé dès la v1 avec tous les cas `Loading/Empty/Sparse/Loaded` gérés — il se remplira automatiquement quand les données eBay arriveront (Phase 2C.4+).
5. **Distribution bar + range dual-delta.** Au lieu d'une seule valeur centrale, on montre P25–P75 avec médiane or distincte, et deux deltas séparés (face value historique + 3m marché) dans des palettes différentes. Le collectionneur comprend immédiatement « combien ça vaut » et « où ça va ».
6. **Émission commune = section dédiée full-bleed.** Les 21 pays sont listés visuellement (pas juste un compteur), possédés entourés d'or, progress bar vers un badge Europa. Cas spécial first-class, pas une afterthought — parce que c'est exactement le genre de collection que l'app vise.
7. **Projection ≠ promesse.** Card indigo clairement séparée, texte Fraunces italic « Si la tendance se maintient », disclaimer en bas hairlined. Pas de graphique criard — juste une fourchette honnête + horizon + facteur rareté mentionné.

## 11. Questions ouvertes

- [ ] **Hero en light mode** : `ReferenceOnly` utilise le hero papier crème. Faut-il un toggle manuel dark/light aussi sur `ScanResult` et `OwnedCoin` ? Le dark donne du théâtre, mais certains users trouvent ça anxiogène pour leurs pièces courantes.
- [ ] **User polaroid — angle de rotation** : actuellement hard-codé (-3° / +5°). Faut-il un angle aléatoire par pièce (seeded sur eurio_id pour persistance) pour donner un effet de main ?
- [ ] **Tooltip sparkline 5 ans** : aujourd'hui positionnée en absolu à ~48% de la largeur. À l'implémentation Compose, il faudra un `DragGesture` pour déplacer le point actif. Quelle UX : tap-and-hold ou glissement libre ?
- [ ] **Couleur de la courbe 12m vs 5 ans** : 12m en indigo (mini), 5 ans en or (maxi). Cohérent ? Ou courbe toujours or avec bande indigo ? Il faut essayer les deux en vrai.
- [ ] **Plusieurs exemplaires possédés** : si l'user a 3 exemplaires d'une même pièce, la fiche actuelle n'expose pas cette réalité. Proposition : bandeau `Vous en possédez ×3` dans l'ownership strip, tap pour voir la liste détaillée (dates/états individuels). À designer.
- [ ] **Accessibilité** : la distinction « variante possédée » par outline gold seul peut passer inaperçue pour des collectionneurs atteints de daltonisme. Prévoir un checkmark glyph en plus de la couleur.
- [ ] **Fiabilité typo Fraunces** : variant `WONK` activée ? Donne du caractère mais peut distraire à certains gras. À trancher avec Raphaël en testant sur device réel.
- [ ] **Animation de « ajout au coffre »** (depuis ScanResult) : la pièce vole-t-elle vers le coffre avec un arc ? Ou juste la pastille change-t-elle avec un haptic ? Moment émotionnel, ne pas bâcler.

---

## Annexe A — Palette finale utilisée dans les mockups

```css
--indigo:      #1A1B4B;
--indigo-900:  #0E0E1F;
--indigo-800:  #15163A;
--indigo-700:  #22234F;
--gold:        #C8A864;
--gold-bright: #E0C688;
--gold-deep:   #8F7637;
--cream:       #FAFAF8;
--cream-2:     #F2F2EE;
--cream-3:     #E6E5DD;
--paper:       #F5F3EC;   /* hero light variant */
--ink:         #0E0E1F;
--ink-2:       #2B2B3A;
--ink-3:       #5A5A6B;
--ink-4:       #8A8A96;
--up:          #2FA971;
--down:        #D87878;
--destructive: #D14343;
```

## Annexe B — Fichiers de ce dossier

| Fichier | Rôle |
|---|---|
| `_system.css` | Variables + composants réutilisables (device frame, hero, sections, CTA) |
| `index.html` | Landing avec iframes miniatures des 6 écrans |
| `01-scan-result.html` | Contexte `ScanResult` — pièce FR-2012 Dix ans de l'euro |
| `02-owned.html` | Contexte `OwnedCoin` — pièce DE-2006 Schleswig-Holstein |
| `03-reference-only.html` | Contexte `ReferenceOnly` — pièce LU-2004 Henri |
| `04-price-history-expanded.html` | Modal plein écran 5 ans, courbe or sur fond indigo |
| `05-empty-states.html` | Toutes les absences : image, prix, historique, tirage |
| `06-commemorative-common.html` | Émission commune 2012 avec grille des 21 pays |
| `DESIGN-NOTES.md` | Ce fichier |
