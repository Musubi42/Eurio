# Profile mockups — design notes

> Mockups haute-fidélité pour la vue Profil. Viewport 390×844. Tous les fichiers sont des HTML standalone (Fraunces + Inter + JetBrains Mono via Google Fonts, zéro JS sauf une arc-text SVG en 05).
>
> Révision : 2026-04-13 · `docs/design/profile/mockups/`

---

## Direction esthétique

**"Cabinet du collectionneur"** — ni free-to-play, ni austère. La référence visuelle est le cartel de musée, la planche de catalogue numismatique, le diplôme gravé. Progression calme, luxe retenu, aucune notification qui crie.

- **Palette** : indigo profond `#1A1B4B` en surface d'honneur (hero, médailles de fond, nav bar) ; or brossé `#C8A864` réservé aux médailles, aux rules fines et au niveau en cours ; paper `#F4F1E8` comme teinte warm pour les cards du body (évite le blanc clinique) ; surface `#FAFAF8` pour le fond principal.
- **Typographie** :
  - **Fraunces** (display serif, italic weights 300-500) — nom du niveau, titres d'écran, titres de médaille. Utilisé en *italic light* pour un ton honorifique, pas trophée.
  - **Inter** (400-600) — corps de texte, labels de progression, chips de pièces manquantes.
  - **JetBrains Mono** — eyebrows, counters, dates, legend, tout ce qui doit ressembler à une inscription gravée / un label de planche scientifique.
  - **Tabular nums** activé sur le conteneur device pour tous les compteurs (6/8, 11/21, 247€).
- **Radius** : 14px pour cards, 20-22px pour le hero & la bottom nav, 999px pour les pills, 50% pour les médailles.
- **Ornements** : rules en dégradé or `transparent → gold → transparent` sous le hero ; seal décoratif (cercles dashed) discret derrière le brand ; watermark vertical `MMXXVI` ; grain SVG en overlay sur les fonds indigo (feTurbulence, opacity ~.06-.08, blend overlay).
- **Motion** : très retenu. Anim pulse lente sur le badge "Plus que 2" (02), rotation rays 60s sur l'écran unlock (05), shimmer 4s sur le CTA or. Rien sur la home — le profil doit se lire immobile.

---

## Fichiers

| # | Fichier | Description |
|---|---|---|
| — | `index.html` | Landing dark avec previews iframe scalées de chaque plate |
| 01 | `01-profile-home.html` | Profil home : hero indigo, niveau "Passionné" en Fraunces italic gold-gradient, ladder 4 points, stats flottantes, 3 chasses en cours, bannière unlock récent, preview settings |
| 02 | `02-achievements-in-progress.html` | Liste achievements en cours, tabs actifs, section "Presque complètes" avec card highlightée + chips pièces manquantes |
| 03 | `03-achievements-unlocked.html` | Featured card dark pour la dernière médaille, puis grille 2-col "Panthéon" des débloqués avec dates |
| 04 | `04-set-detail.html` | Série complète France — hero indigo, grille 2-col de 8 coin-discs (radial gradients réalistes or/argent/bi-métal), 2 missing en dashed, CTA "Scanner une pièce manquante" |
| 05 | `05-achievement-unlock.html` | Plein écran dark, médaille 220px avec engraving, arc-text SVG `· Collection Eurio ·` / `MMXXVI`, halo pulsé, CTA or shimmer + ghost "Continuer" |
| 06 | `06-settings.html` | Liste groupée 7 sections : Général, Notifications (opt-in badge), Catalogue (segmented Wi-Fi/Cell/Manuel), Données, Vie privée, Compte (v2 disabled), À propos |

---

## Décisions de design (7 importantes)

1. **Le niveau comme titre d'honneur, pas comme score.** "Passionné" en Fraunces 62px italic 300, sur dégradé or, avec `II / IV` minuscule en mono à droite — inspiré des rangs chevaleresques/académiques. Aucun XP, aucun pourcentage crié. La barre sous le titre est fine (2px), avec 4 nodes circulaires (ladder discret), node courant glowy à 58% avec un hint textuel *"Encore 11 pièces pour devenir Expert"*. Le `58%` apparaît en mono discret à droite, pas en grand.

2. **Ladder multi-nodes plutôt que barre unique.** Les 4 paliers sont représentés visuellement par 4 points sur le rail, ce qui rend la non-régression évidente (les points passés restent or plein). Même si le user retire des pièces, les nodes done restent allumés — cohérent avec la règle "pas de régression" de `level-progression.md`.

3. **Stats flottantes qui chevauchent le hero.** Les 3 stats (Pièces / Pays / Valeur) sont dans des cards qui "remontent" de -32px dans le hero indigo. Crée une profondeur éditoriale type magazine, évite la monotonie d'un simple stack vertical, et limite le bruit : pas de "nombre de scans", pas de taux de succès — on garde uniquement ce qui raconte la collection. Voir Q1 ci-dessous.

4. **Médailles réalistes en CSS pur (radial gradients multiples).** Chaque médaille combine `radial-gradient` + `inset box-shadow` triples (highlight, depth, rim) + pseudo-élément dashed pour l'anneau intérieur. Variantes : gold, silver, bronze, dim (in-progress). L'écran unlock (05) pousse la technique plus loin avec un arc-text SVG en `textPath` qui grave *"· Collection Eurio · MMXXVI"* autour. Rendu "honnête" sans jamais avoir besoin d'un asset raster.

5. **Célébration mesurée, pas Duolingo.** L'écran 05 n'a ni confetti, ni explosion, ni son. À la place : une médaille 220px qui apparaît en `scale(0.4) → 1` cubic-bezier sur 1.2s, des rays coniques très low-opacity tournant à 60s, un halo radial qui pulse à 4s, et un texte "Première série." en Fraunces italic gradient or. CTA primaire or brossé (shimmer subtil), CTA secondaire "Continuer" en ghost mono. Le bouton close est toujours accessible en haut à droite dès le premier instant — le user n'est jamais prisonnier de l'écran.

6. **Set detail = planche de catalogue, pas inventaire.** La grille 2×4 utilise des coin-discs avec radial-gradient qui imitent vraiment le métal (cuivre pour 1-5c, nordic gold pour 10-50c, silver pour 1€, bi-metal pour 2€). Les manquantes gardent la forme mais passent en gris-beige mat avec card en border-dashed — le user voit encore ce qui manque comme des *emplacements vides dans un album*, pas comme des erreurs. Le header "Huit pièces, *une série.*" reprend le ton éditorial.

7. **Settings : notifications toutes off par défaut, "Opt-in" affiché comme badge or.** Je rends visible la promesse anti-spam en mettant un badge gold "OPT-IN" dans le label de la section Notifications. Ça rassure les users méfiants (persona Isabelle) et documente la posture PRD. La seule exception : "Complétion de set" est on — c'est l'unique notif qui célèbre un moment positif déjà accompli, jamais un rappel intrusif. Compte Google est *visible mais disabled* avec pill "v2" — le user sait que ça arrive, ne se demande pas où c'est.

---

## Hiérarchie des composants (réutilisables Compose)

| Composant HTML | Compose mapping suggéré | Notes |
|---|---|---|
| `.hero` (indigo + grain + gold rule) | `ProfileHero(level, progression, hint)` | Top-level container, gradient + noise overlay. Réutilisable en tête de set-detail avec des props. |
| `.ladder` (4 nodes + fill) | `LevelLadder(steps: List<Step>, currentIndex, fillPct)` | État `done / current / locked`. L'animation de progression est à l'extension du fill, pas sur le node. |
| `.stat` (flottant) | `FloatingStatCard(key, value, delta?)` | Row de 3 — l'offset negative margin reste côté parent (overlap) |
| `.ach` (card in-progress) | `AchievementCard(variant: InProgress/Hot/Done)` | Variant `hot` = "Plus que N", animation pulse côté badge |
| `.medal` (44/48/56/88/220px) | `Medal(variant, size, label?)` | Radial gradients. Variants : gold, silver, bronze, dim. 220 = hero unlock. |
| `.coin-disc` | `CoinDisc(variant: Copper/Nordic/Silver/BiMetal/Missing, denomination)` | Pareil mais pour la grille du set. Différent du Medal car représente une pièce réelle. |
| `.seg` (segmented) | `SegmentedPicker(options, selected)` | Pour Wi-Fi / Cell / Manuel |
| `.toggle` | `GoldToggle(checked)` | Variant gold pour la notif positive, variant indigo pour le reste |
| `.nav` (bottom) | `EurioBottomNav(activeTab)` | Dark floating pill, jamais en white flat |

---

## Interactions

| De → vers | Déclencheur |
|---|---|
| Home 01 → In Progress 02 | Tap "Tout voir" sur section Chasses en cours |
| Home 01 → Settings 06 | Tap "Ouvrir" settings preview, ou tap row settings |
| In Progress 02 → Set Detail 04 | Tap sur une card achievement en cours |
| In Progress 02 ↔ Unlocked 03 | Tap tab |
| Unlocked 03 → Featured medal | Tap la carte featured ouvre probablement un plein écran type 05 en mode "revisit" (pas d'anim d'arrivée) |
| Set Detail 04 → Scan | CTA "Scanner une pièce manquante" — deep-link vers la vue Scan pré-filtrée sur l'`eurio_id` manquant |
| Set Detail 04 → Coin Detail | Tap sur une coin-disc possédée (navigation hors scope de cet agent) |
| Unlock 05 → Set Detail 04 | CTA primaire "Voir dans le coffre" |
| Unlock 05 → Home 01 | Tap close (top-right) OU CTA ghost "Continuer". Écran jamais bloquant. |
| Settings toggles | State locaux, persistés en DataStore. Les toggles notifications déclenchent un prompt permission runtime Android 13+ au premier `on`. |
| Settings Catalogue segmented | Instant save, pas de bouton "Enregistrer" |

---

## Data bindings

| Element | Source | Calcul |
|---|---|---|
| Nom du niveau | `LevelRepository.currentLevel(userId)` | Max atteint, jamais régressif |
| Barre de progression | `LevelRepository.progressToNext()` | Pourcentage du critère le plus proche (voir `level-progression.md`) |
| Hint "Encore 11 pièces" | même | Critère qui a gagné la course + delta humanisé |
| `23 pièces` | `VaultRepository.countDistinct()` | `COUNT(DISTINCT eurio_id)` Room |
| `8 pays` | `VaultRepository.countryCoverage()` | `COUNT(DISTINCT country_iso2)` |
| `247 €` + `↑ 34%` | `VaultRepository.totalValueP50()` + delta 30 jours | Valorisation P50 via `coin_price_observation` |
| Achievements en cours | `AchievementEngine.inProgress()` | Tous les sets avec 0 < progress < 100 |
| "Plus que 2 pièces" + chips | `AchievementEngine.missingFor(setId)` | List<Coin> not in collection AMONG required |
| Dernière médaille (banner home + featured 03) | `AchievementEngine.mostRecentUnlock()` | Ordered by `unlocked_at DESC LIMIT 1` |
| Date unlock `13 AVR 2026` | `achievement_state.unlocked_at` | Format `DD MMM YYYY` localisé |
| Ladder nodes state | `LevelRepository.history()` | Liste des niveaux atteints |
| Version v0.3.1 | `BuildConfig.VERSION_NAME` + `BuildConfig.VERSION_CODE` | |

---

## États edge

### User débutant (Découvreur, 0-2 pièces)
- Hero : "Découvreur" en Fraunces, hint `"Scanne ta première pièce"`.
- Ladder : aucun node done, node current au début à 0%.
- Stats flottantes : `0 pièces / 0 pays / — €` (em-dash, pas 0€ pour ne pas renforcer le vide).
- Section "Chasses en cours" remplacée par une empty state : une médaille dim + "Les chasses apparaîtront dès ton premier scan" + CTA secondaire vers Scan.
- Bannière "dernière médaille" cachée tant qu'aucun unlock.
- Onglet Débloqués désactivé ou montré avec `0` en chip n-200. Onglet "Verrouillés" peut-être caché complètement en v1 (voir Q4).

### User Maître (niveau max atteint)
- Hero : "Maître" en Fraunces, **pas de hint vers le prochain niveau**.
- Ladder : les 4 nodes all gold, pas de glow courant.
- À la place de la barre de progression : une ligne *"Tu as atteint le rang le plus élevé."* en italic, sans pourcentage.
- `level-progression.md` interdit explicitement un niveau 5 — le hint de progression laisse place à une section "Pantheon" (ou rien).
- Le hero pourrait recevoir un ornement supplémentaire type laurier serif léger (option à explorer).

### User qui vient de débloquer Maître pour la première fois
- Même écran 05 (unlock-screen) mais titre "Maître." et description sur-mesure.
- Pas de CTA "Voir dans le coffre" puisque Maître n'est pas un set — remplacer par "Voir mon cabinet" qui ramène au Profil home dans son nouvel état.

### User avec 100+ achievements débloqués
- Grille 03 reste 2-col. Pas de virtualisation dans le mockup mais Compose `LazyVerticalGrid` en prod.
- La featured card reste le plus récent. Ajouter une option de tri (par date / par difficulté) en secondary header — hors scope mockup v1.

---

## Questions ouvertes

1. **Les 3 stats flottantes suffisent-elles ?** J'ai choisi Pièces / Pays / Valeur. Le README mentionne aussi "membre depuis 12 jours" et "scans total 34". Je les ai volontairement omis de la home pour ne pas voyeuriser — à rebasculer dans une sous-vue "Statistiques détaillées" si le user en veut plus. À valider.
2. **Ladder à 4 nodes vs barre simple.** Le ladder est plus riche mais prend plus de place verticalement. Arbitré en faveur du ladder parce que c'est THE moment de lecture du profil — mais si on doit densifier, on peut dropper les labels mono sous les nodes.
3. **Unlock screen plein écran à chaque fois vs bannière discrète.** Le mockup 05 est conçu pour la **première fois** uniquement (question ouverte dans le README). Pour les unlocks suivants ou le "revisit" depuis la liste 03, il faudrait une variante sans les anims d'entrée et sans CTA "Continuer" — juste un état de consultation. À trancher avant impl.
4. **Onglet "Verrouillés".** Il existe dans les tabs 02/03 mais je n'ai pas fait un écran dédié : d'une part pour rester dans le scope 6 plates, d'autre part parce que la question 4 du README ("les afficher ou les cacher") est ouverte. Ma reco : afficher uniquement ceux qui ont au moins 1 pièce compatible dans la collection (sinon ils deviennent une to-do list infinie). À valider avec Raphaël.
5. **"Membre depuis"**. Pas affiché dans le mockup — cohérent avec Q1 du README ("premier lancement ou premier scan ?"). Ma reco : premier scan, affiché uniquement dans le bottom sub-header de Settings "À propos" (pas sur la home).
6. **Animation unlock : durée totale.** Actuellement ~1.5s entry (eyebrow .1s + medal .3s/1.2s + texts .8s + actions 1.1s). C'est généreux. Si on veut plus snappy on peut couper à ~900ms total. À calibrer sur device réel.
7. **Thème sombre global.** Tous les mockups sont en light mode "paper". Les écrans 01 (hero) et 05 (unlock) sont déjà dark-chrome. Une version sombre du profil entier serait probablement une inversion : surface = indigo-3, paper = indigo-2, ink = paper. À prototyper si le reste de l'app tourne en dark.
8. **Grille set detail pour sets à N pièces > 8.** Grande chasse = 21 tiles, Commémoratives FR = 25+. Le mockup 04 assume 8 (circulation). Il faudra une variante avec plus de colonnes (3-col) ou un scroll plus long — et les manquantes risquent d'écraser visuellement (une mer de gris). Option : grouper les manquantes dans une section "À trouver" en bas plutôt qu'en ligne dans la grille.
