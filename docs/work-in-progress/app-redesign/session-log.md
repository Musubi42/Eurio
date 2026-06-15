# App-redesign — journal de session

> Un bloc par session. Méthode : preuve-first + how-to-verify (cf. [[feedback_handoff_quality]]).
> Lire un bloc = des faits vérifiés sur le proto, pas des intentions.

---

## Session 1 — Vue Scan + reveal (2026-06-15)

**Statut : ✅ livré en proto, audité (Chrome MCP) + à tester device.** Non committé.

### Ce qui a été fait

Fusion des 4 surfaces (`ScanIdle` + `ScanTransition3D` + `RevealStratifie` + `CoinDetail`)
en **une seule scène** `ScanReveal`, sur une seule stage Three (un objet 3D continu).

Le flux :

```
idle caméra ──(auto-match 2 s)──▶ identification (morph→spin→settle, halo+son 1×)
 ──▶ reveal : pièce posée + titre SOUS la pièce + sheet 2 crans
      • pull-up le sheet  → fiche complète (CoinDetailBody) ; le 3D migre dans le header du sheet
      • swipe-down le sheet → on repart en scan (NOUVELLE pièce)
```

### Fichiers (tous dans `admin/packages/proto/`)

| Type | Fichier | Rôle |
|---|---|---|
| **neuf** | `src/scenes/scan/ScanReveal.vue` | LA scène scan unifiée |
| **neuf** | `src/styles/scan-reveal.css` | phases idle/reveal, FX halo/flash (déplacés depuis scan-transition.css), titre-sous-pièce, variant **sombre** de la fiche |
| **neuf** | `src/components/CoinDetailBody.vue` | corps de fiche **partagé** (extrait de CoinDetail) — monté par `/coin/:id` ET par le sheet du scan. Prop `showHero` (false en scan : le 3D live remplace l'image), `@toast` |
| modif | `src/scenes/CoinDetail.vue` | devenu coquille (topbar + `<CoinDetailBody>` + CTA) |
| modif | `src/router/index.ts` | `/scan` → `ScanReveal` ; routes mortes supprimées |
| modif | `src/scenes/AppShell.vue` | onglet **Marché retiré** (nav 3 icônes, T1) |
| modif | `src/scenes/onboarding/OnboardingDemo.vue` | push `/scan?id=` (au lieu de `/scan/transition`) |
| modif | `src/styles/components.css` | variant snackbar `.toast--action` + `.toast__action` (toast nu = `pointer-events:none`) |
| **supprimé** | `ScanIdle.vue`, `scan/ScanTransition3D.vue`, `scan/RevealStratifie.vue`, `styles/scan-transition.css` | fusionnés dans ScanReveal |

> `reveal-stratifie.css` est **conservé** (réutilisé par ScanReveal pour le sheet/hero/célébration).

### Décisions prises (avec le PO)

1. Fusion via `CoinDetailBody` partagé (1 source de vérité).
2. 3D continu caméra → peek → header du sheet (re-parentage du canvas WebGL).
3. **Auto-add + undo** à l'identification (⚠️ contre-pied assumé de « scanner ≠ posséder » — [[feedback_scan_ux]]).
4. Toggle Avers/Revers gardé sur `/coin/:id` ; Yours/Réf différé Android (E1).
5. Retouches finales : **pas de label « Identifié »** (la pièce suffit) ; **swipe-down = re-scan** ;
   **rotation** = tourne libre, mais recentrée à plat + relâchée sans élan → se **fige** (lock), re-flick → repart.

### Comment vérifier (le proto tourne sur `:5174`)

- FAB Scan → `/scan` : attendre ~2 s → la pièce s'identifie (halo + son), titre sous la pièce, sheet en peek.
- **Pull-up** le handle → fiche complète scrollable (récit + sections), 3D dans le header. **Re-tirer vers le bas** → peek.
- **Swipe-down** depuis le peek → retour vue scan, nouvelle pièce après 2 s.
- **Rotation** : laisser tourner ; ramener la pièce ~face avant et lâcher doucement → elle se fige ; la reflicker → repart.
- **Coffre** : le scan auto-ajoute (snackbar « Annuler » + CTA « Retirer du coffre »).
- Nav = 3 icônes (Coffre · Scan · Profil).
- `pnpm typecheck` ✅, `pnpm build` ✅, console navigateur sans erreur.

État vérifié en pilotant Chrome (DOM/eval) : lock (snap exact au multiple de π, `locked=true`),
unlock au flick, dismiss (`phase=idle` puis nouvelle pièce), auto-add + undo, variant sombre lisible.

### Findings / pièges rencontrés (utiles pour les prochaines vues)

- **Audit visuel indispensable** : `vue-tsc` passait au vert alors que 2 fichiers `.vue` s'étaient
  terminés par des balises parasites (`</content></invoke>` injectées par l'outil Write) → Vite plantait.
  Le typecheck seul = faux positif. **Toujours ouvrir l'écran.**
- **Fiche claire dans un sheet sombre** : `CoinDetailBody` est stylé pour `/coin/:id` (fond clair,
  `var(--ink)`). Sur le sheet sombre, la moitié du texte était invisible. Fix = variant sombre **scopé**
  `.scan-reveal-root .coin-detail-body` (le clair reste intact). Pattern réutilisable si un autre composant
  clair atterrit sur fond sombre.
- **Re-parentage canvas WebGL** : déplacer `.reveal-hero__canvas` entre le bandeau et le sheet marche
  (le `ResizeObserver` de `createStage` recadre renderer+caméra). Pas de ré-instanciation 3D.
- **Réutilisation de composant Vue** : changer seulement la query (`/scan?milestone=…`) **ne remonte pas**
  le composant (même route) → un `const` figé au setup ne bouge pas. D'où la résolution de pièce **réactive**
  (refs) pour permettre le re-scan in-place.
- **Toast = `pointer-events:none`** : un bouton dans un toast n'est pas cliquable sans variant dédié.
- **Capture MCP vs timers** : les screenshots arrivent souvent après l'expiration d'un toast (4,5 s) à cause
  de la latence ; vérifier l'état par `eval` (DOM/attrs) plutôt que se fier au screenshot pour le transitoire.

### Reste à faire / différé

- **Tester sur device** (le PO) — surtout le feel du lock-rotation et du swipe-down.
- **Toggle CTA « Retirer » vs snackbar « Annuler »** : deux undo (transitoire + persistant). À confirmer/simplifier
  si le PO trouve ça redondant.
- **Parité** : le flux de capture parité référençait les anciennes scènes/routes — à re-vérifier quand la
  parité sera reprise (hors scope refonte).
- Vues suivantes : Coin Detail (la fiche existe déjà via `CoinDetailBody`), Coffre, Profil, Onboarding.

---

## Session 2 — Vue Coffre, restructurée sur le flow CoinSnap (2026-06-15)

**Statut : ✅ livré en proto, audité (Chrome MCP). Non committé.**

### Le problème (rappel `coffre.md`)
Le PO trouvait le Coffre « trop lourd » : 6 strates de façade (delta, sparkline 12 mois,
3-stats, barre recherche, rangée filtres/tris) **avant** d'arriver aux pièces. Le PO a fourni
des captures CoinSnap (`coinsnap-teardown/screens/s17–s19`) en disant « rapproche-toi de ce flow ».

### La bascule structurelle
Le dégraissage se fait **par répartition sur 3 onglets** (à la CoinSnap), pas par repli :

```
Header patrimoine SOBRE et persistant : « 22 € · Valeur du coffre » + « N Pièces | N Pays »
  ├─ Résumé  → vitrine curée : spotlight best coins + répartition géo + aperçu sets
  ├─ Pièces  → le navigateur brut (recherche, tri, toggle grille/liste, groupes)
  └─ Sets    → liste de sets existante
```

Décisions PO (via questions) : **3 onglets** (le Catalogue/carte-à-gratter n'est plus un onglet,
il devient le « Tout voir » de la *Répartition géographique* du Résumé) ; best coins en
**carte spotlight** (1 pièce, avers+revers, laurier superlatif, pagination par points).

### Fichiers (`admin/packages/proto/`)
| Type | Fichier | Rôle |
|---|---|---|
| réécrit | `scenes/vault/VaultHome.vue` | devient l'onglet **Résumé** (spotlight + géo + sets). Empty state conservé |
| **neuf** | `scenes/vault/VaultAll.vue` | onglet **Pièces** = navigateur brut extrait de l'ancien VaultHome |
| **neuf** | `styles/vault-summary.css` | spotlight, mini-carte géo, aperçu sets |
| réécrit | `scenes/vault/CoffreHeader.vue` | header patrimoine sobre (valeur + Pièces\|Pays), lit le store, **partagé par les 3 onglets** |
| réécrit | `scenes/vault/CoffreTabs.vue` | onglets `summary\|all\|sets` (`/vault`, `/vault/all`, `/vault/sets`) |
| modif | `scenes/vault/CarteAGratter.vue` | header onglets → **back-bar** « ← Catalogue eurozone » (atteint via Tout voir) |
| modif | `styles/components.css` | styles `.coffre-header__value` / `__stats` (sobre) + `__top` en flex-end |
| modif | `styles/vault-catalog.css` | `.cag-backbar` |
| modif | `router/index.ts` | route `/vault/all` ajoutée |

`VaultSetsList.vue` utilisait déjà `<CoffreHeader active="sets">` → 0 changement, hérite du nouveau header.

### Décisions de design
1. **Header sobre supprimé l'eyebrow « Ton coffre »** (la valeur fait le titre, comme CoinSnap ;
   en plus ça chevauchait le badge version dev en haut à gauche).
2. **Répartition géo dérivée du store** (pas de la fixture `getCountryProgress`, non jointe) →
   cohérente avec le compteur Pays du header. La fixture ne sert plus qu'à drapeau/nom ;
   drapeau **dérivé de l'ISO** (indicateurs régionaux) en repli → couvre MC/VA/SM absents de la fixture.
3. **Mini-carte = aperçu non interactif de la carte à gratter** (réutilise `GEO`/`CONTEXT` de
   `eurozone-geo`, pays possédés en or) ; tap → `/vault/catalog` (la vraie carte à gratter).

### Comment vérifier (`:5174`)
- `window.__eurio.seed('populated')` puis `#/vault` (un guard onboarding redirige `/vault` tant que
  `firstRun` ; `seed()` appelle `completeOnboarding`).
- **Résumé** : header 22 € · 11 Pièces · 11 Pays ; spotlight Monaco 2007 (avers+revers, laurier
  « 💎 La plus précieuse », 2162,50 €), 8 points de pagination (clic → change de pièce) ;
  Répartition « 11 pièces dans 11 pays » + mini-carte (France en or) + 3 pays (drapeaux 🇲🇨🇻🇦🇸🇲) +
  « Tout voir » → catalogue ; aperçu 3 sets avec barres.
- **Pièces** (`/vault/all`) : recherche + Filtres + toggle + tris + grille groupée par pays.
- **Sets** : header sobre + liste de sets existante intacte.
- **Catalogue** (`/vault/catalog`) : back-bar (pas d'onglets) + carte à gratter complète.
- `seed('empty')` → Résumé affiche l'empty state (titre + CTA « Scanner ma première pièce »).
- `pnpm typecheck` ✅, `pnpm build` ✅.

### Pièges rencontrés (utiles pour la suite)
- **Dev server Vite corrompu par les écritures rapides** : des 500 transitoires pendant la création
  des fichiers ont figé le module-graph (timestamp HMR `?t=` gelé) ; symptôme = un 2ᵉ `<style src>`
  résolu en `/styles/…` au lieu de `/src/styles/…` (`ENOENT`). Fix = `touch` des fichiers concernés
  pour forcer la ré-invalidation (le `pnpm dev` du PO tourne au premier plan, **on ne le tue pas**).
  Confirme à nouveau : **typecheck/build verts ≠ écran qui marche → toujours ouvrir l'écran.**
- **Réactivité Vue async en audit MCP** : lire le DOM juste après un `.click()` synthétique renvoie
  l'état d'avant ; attendre 2 `requestAnimationFrame` avant de relire.

### Reste à faire / différé
- **Tester sur device** (le PO) — feel du spotlight (swipe entre pièces ?) et de la nav onglets.
- **Swipe horizontal sur le spotlight** : aujourd'hui pagination par points seulement (clic). Le swipe
  tactile serait plus naturel — à ajouter si le PO valide le format.
- **Bande articles éditoriale (T5)** : non intégrée (hors scope, le Résumé CoinSnap n'en a pas).
- **Actions header** (export / ⋯) : encore des stubs.
- **Parité** : flux de capture à re-vérifier (routes vault changées) quand la parité sera reprise.

---

## Session 3 — Coffre, peaufinage best coins (2026-06-15)

**Statut : ✅ chunk A livré (proto, audité Chrome MCP). Non committé. Chunk B (carte géo) à suivre.**

### Décisions PO
- Best coins = **galerie de trophées** : 1 page de spotlight = 1 catégorie superlative.
  Catégories retenues (ordre) : 💎 **précieuse** · 👑 **rare** · 🏛️ **ancienne** · ⭐ **commémo phare** · 🏰 **micro-état**.
- Spotlight en **3D live** (réutilise le moteur de ScanReveal).
- Carte « Répartition géographique » = **scène séparée** (coexiste avec la carte à gratter),
  rendu **SVG stylisé + épingles drapeau**, feuille basse redimensionnable listant les **pièces** (pas les pays). → chunk B.

### Chunk A livré (best coins)
| Type | Fichier | Rôle |
|---|---|---|
| **neuf** | `components/Spotlight3D.vue` | pièce 3D live (createStage + buildCoinFromUrls), auto-rotation, swap du modèle au changement de catégorie (1 seule stage WebGL, garde anti-course par token) |
| modif | `scenes/vault/VaultHome.vue` | `trophies` (5 catégories, **dédoublonnées** → 5 pièces distinctes) ; pagination = catégories ; 3D au lieu d'avers+revers plats |
| modif | `styles/vault-summary.css` | `.summary-spot__stage` (canvas 3D h=200) remplace `__faces/__face` |

### Pièges
- **Canvas 3D débordant** : `createStage` appelle `setSize(w,h,false)` → ne pose PAS le style du canvas,
  donc il s'affiche à sa taille intrinsèque (buffer) et déborde. Fix = `.spotlight-3d :deep(canvas){width:100%;height:100%}`.
- **Dédoublonnage des trophées** : sur petite collection, une pièce iconique (Monaco Grace Kelly) cumule
  précieuse + commémo + micro-état → 3 pages identiques. Résolu : chaque catégorie prend le meilleur
  candidat *pas encore utilisé* (`used` set). Effet de bord assumé : « commémo phare » peut montrer la
  2ᵉ meilleure commémo si la 1ʳᵉ a déjà gagné « précieuse ». À confirmer PO.

### Comment vérifier
- `seed('populated')` → `#/vault`, onglet Résumé : la pièce du spotlight tourne en 3D ; les 5 points
  paginent les catégories (Monaco 💎 · Chypre 👑 · Vatican 🏛️ · Luxembourg ⭐ · Saint-Marin 🏰).
- `typecheck` ✅ `build` ✅.

### Chunk B livré (carte Répartition géo)
| Type | Fichier | Rôle |
|---|---|---|
| **neuf** | `scenes/vault/VaultGeoMap.vue` | scène `/vault/geo` : carte eurozone plein écran + épingles drapeau/compteur + feuille pièces redimensionnable |
| **neuf** | `styles/vault-geo.css` | carte atlas claire, épingles pilule, feuille drag |
| modif | `scenes/vault/VaultHome.vue` | Résumé « Répartition » (carte + lignes + Tout voir) → `/vault/geo` (au lieu de `/vault/catalog`) |
| modif | `router/index.ts` | route `/vault/geo` |

Détails :
- **Coexistence** carte géo ⟷ carte à gratter : la back-bar de `/vault/geo` a un lien « Catalogue → » vers `/vault/catalog`. Deux intentions : *répartition* (où sont mes pièces) vs *catalogue/complétion* (ce qu'il reste).
- **Feuille = pièces, pas pays** (divergence assumée vs CoinSnap) : liste les pièces possédées, triées par valeur. Tap d'une épingle → filtre la feuille au pays + surligne le pays ; bouton « Tout » réinitialise.
- **Feuille redimensionnable** : drag du handle (pointer events), hauteur clampée 18–85 %, défaut ≈ 32 %.
- **Épingles** : `GEO` ne contient QUE `d` (pas de cx/cy) → centroïde calculé en moyennant les sommets du path ; les **micro-états (MC/VA/SM/AD) sont absents de GEO** → ancrés sur le pays hôte (MC/AD→FR, SM/VA→IT) + offset viewBox. Positions micro-états = approximatives.
- **Rendu atlas clair** (mer bleu-gris, terres pâles, possédé en or) pour se distinguer de la carte à gratter (navy + or à gratter).

### Comment vérifier (chunk B)
- `#/vault` → Résumé → « Tout voir » de Répartition → `/vault/geo`.
- Carte plein écran, 11 épingles, feuille « 11 pièces · 11 pays » + lignes pièces.
- Tap épingle Italie → feuille « 🇮🇹 Italie · 1 pièce », pays surligné, bouton « Tout ».
- Drag du handle vers le haut → la feuille grandit (testé : 32 % → 59 %).
- `typecheck` ✅ `build` ✅, console sans erreur.

### Chunk B+ — carte full-bleed + pan/zoom (retours PO)
PO : (1) la feuille ne doit PAS redimensionner la carte (overlay) ; (2) pouvoir zoomer ; (3) SVG fragile ?
- **Carte full-bleed** : `.geo-map` en `position:absolute; inset:0` ; la feuille (`.geo-sheet`) est un **overlay** absolu → la redimensionner ne touche plus la carte. Vérifié : transform du calque inchangé pendant le drag.
- **Pan + zoom** : transform CSS sur `.geo-map__pannable` (svg + épingles ensemble), molette + pinch (2 pointeurs) + boutons +/−, zoom-vers-curseur, clamp 1–6×. Épingles **contre-zoomées** (`scale(1/zoom)`, origin bottom) → taille constante. `vector-effect:non-scaling-stroke` sur les paths.
- **SVG fragile ? NON.** Vérifié à 2,74× : frontières **nettes** (vectoriel) et géométrie déjà **détaillée** (fjords, îles danoises). Pas besoin de swap vers un GeoJSON ; SVG = bon choix (net + offline).
- **CSS via import JS** : `import '@/styles/vault-geo.css'` au lieu de `<style src>` (voir piège ci-dessous).

### ⚠️ Piège environnement majeur (cause de toute la flakiness de la session)
Les 500 / `ENOENT` / modules périmés intermittents n'étaient **pas** dus au code mais à **3 serveurs Vite en collision** sur les ports 5173/5174 (1× `packages/proto` + **2× `packages/web`**). Les requêtes étaient servies au hasard par l'un ou l'autre → modules manquants côté mauvais serveur. **Diagnostic** : `lsof -iTCP -sTCP:LISTEN -P | grep 517`. **Remède** : ne garder qu'UN dev server par package. **Audit fiable** = lancer une instance dédiée sur un port libre (`vite preview --port 5191 --strictPort`) et la couper après. `typecheck`/`build` restaient verts tout du long (le code était sain).

### Reste / à discuter
- **Swipe horizontal** sur le spotlight (aujourd'hui : points cliquables).
- **Dédoublonnage trophées** : valider le compromis (catégorie n prend le meilleur candidat non encore pris).
- **Épingles micro-états** : positions approximatives (offset depuis l'hôte) — affiner si besoin.
- **Zoom initial** : centré viewport (peut tomber sur la mer) ; on pourrait cadrer sur les pièces possédées.
- Tester sur device (3D spotlight + carte pan/zoom + feuille).

---

## Session 4 — Fixes ports/carte/3D + refonte vue Pièces (2026-06-15)

**Statut : ✅ livré (proto, audité Chrome MCP sur instance propre 5174). Non committé.**

### Fix 1 — Collision de ports (cause racine de la flakiness, RÉSOLUE durablement)
- `packages/web/vite.config.ts` n'avait **pas de port fixe** → défaut 5173 mais **sans `strictPort`** : si 5173 occupé (ou web lancé 2×), Vite **vole le 5174 du proto**. D'où le service aléatoire et les 500/ENOENT.
- Fix : `server`+`preview` avec **port explicite + `strictPort: true`** dans les DEUX configs (proto 5174, web 5173). Un doublon échoue désormais clairement au lieu de voler le voisin.
- Nettoyé les 3 serveurs en collision, relancé **un seul** proto sur 5174. Voir [[feedback_proto_dev_server_collision]].

### Fix 2 — Carte Répartition : fixe + recouverte (le PO : « la map reste full size, la modale la couvre »)
- `layout()` passe en **cover** (`s = max(rw/VBW, rh/VBH)`) : la carte remplit TOUT le viewport, taille **fixe**. La feuille (`.geo-sheet` absolute) glisse par-dessus sans jamais toucher la carte (transform du calque inchangé, vérifié à 18 % comme à 53 %). Plus de bandes vides (l'ancien centrage letterbox était « dégueulasse » au drag).

### Fix 3 — 3D best coins rétabli + fallback
- La carte spotlight vide chez le PO = conséquence de la collision de ports (module 3D chargé du mauvais serveur). Réglé par le fix 1.
- `Spotlight3D.vue` : **fallback `CoinImage`** si `getCoin3DAssets` renvoie null ou si le build 3D échoue → la section best-coins montre TOUJOURS une pièce.

### Chunk Pièces v2 — orientée valeur (décisions PO : toutes les pistes, grille par défaut, recherche inline)
`VaultAll.vue` refondu + `styles/vault-all.css` (importé en JS) :
- **Lignes valeur + identité** : titre = vrai nom (thème/commémo, ex « 25th Anniversary of the Death of Princess Grace »), sous-titre = grade + pays + année, à droite = **cote marché réelle** (`getMarket.p50`) teintée or si rareté. Fini la faciale + delta « — » mort.
- **Grille = vitrine** : tuile avec cote + bordure or (précieuse) / indigo (commémo).
- **Toolbar slim inline** : champ de recherche **inline** (filtre temps réel sur nom/pays/année) + chips de tri (Pays/Valeur/Faciale/Date) + toggle grille/liste, sur 2 rangées au lieu de 3.
- **Totaux par groupe** : en-tête = « N · valeur cumulée » (ex « Par valeur · 11 · 4 398 € »).
- **Filtres enfin appliqués** : `store.prefs.vaultFilters` (pays/faciale/type/grade/année) était édité par la scène `/vault/filters` mais **jamais appliqué** dans la liste → maintenant filtré + badge compteur sur le bouton Filtres.

### Comment vérifier (`:5174`, UN seul serveur)
- `seed('populated')` → onglet **Pièces** : grille avec cotes (Andorre 19 €, Chypre 1 699 €) + bordures or ; tri **Valeur** → liste « Par valeur » décroissante avec vrais noms ; recherche « monaco » → filtre à 1 ; bouton Filtres applique + badge.
- `typecheck` ✅ `build` ✅.

### Reste / à discuter (Pièces)
- **Panneau de filtres 100 % inline** (6 dimensions) : aujourd'hui les filtres *s'appliquent* mais le panneau d'édition reste la scène `/vault/filters` → prochaine étape = le rendre inline (feuille déroulante).
- **Noms en anglais** : `coin.theme`/`designDescription` sont en EN dans le catalogue → pour une app FR, préférer `coin.names.fr` si dispo. À trancher (chantier i18n).
- **Grade chip** : s'affiche quand `entry.condition` est renseigné (le seed démo ne l'a pas toujours).

---

## Session 5 — CoinDetail v2 (2026-06-15)

**Statut : 🟡 partiellement livré (proto, audité Chrome MCP sur 5174 propre). Non committé.**

Rappel : la fiche est le corps PARTAGÉ `CoinDetailBody` monté au scan ET sur `/coin/:id` (R0). Plus riche que CoinSnap (récit + percentiles + historique + projection + sets + émission commune). On comble des manques, on ne copie pas.

### Livré (décisions PO de cette session)
- **Hero 3D** sur `/coin/:id` : `CoinDetail.vue` monte `Spotlight3D` au-dessus du body (cohérent scan + best-coins). `CoinDetailBody` reçoit `:show-hero="false"` → ne rend plus de hero image (les deux hôtes fournissent leur 3D).
- **En-tête value-forward** (`CoinDetailBody`, nouveau `.cd-head`) : faciale + pays·année·commémo + nom réel (thème) + **fourchette de cote (P25–P75, valeur unique si plate) + grade + badge rareté** + (si owned) ligne Ajoutée/État/Valeur. Remplace l'ancien hero plat + la section « 01 Identité ».
- **Section Design** (`.cd-design`) : Avers (designDescription + lettering) / Revers (lettering, côté commun) / Tranche — **lettering réel via `coin.raw.{obverse,reverse,edge}_lettering`** (validé : Monaco « MONACO 2007 R.B.BARON » / « 2 EURO LL » / tranche).
- Variant **sombre** des nouvelles classes ajouté dans `scan-reveal.css` (sheet scan reste lisible — vérifié : titre `rgb(250,250,248)`).

Fichiers : `components/CoinDetailBody.vue` (refonte top + design), `scenes/CoinDetail.vue` (+hero 3D), `styles/coin-detail.css` (+cd-head/cd-design/hero3d), `styles/scan-reveal.css` (overrides sombres). `typecheck`/`build` ✅, scan + `/coin/:id` vérifiés sans erreur console.

### Reste (du cadrage `views/coin-detail.md`, non fait cette session)
- **Retirer les numéros lourds** 01/02/03… (hiérarchie condensée façon CoinSnap) — j'ai gardé les numéros par défaut, à enlever.
- **Toggle Yours / Référence** (Réf = 3D, Yours = photo utilisateur) — réservé Android (pas de vraie capture en proto).
- **Courbe de rareté** (distincte de la courbe de cote) pour les pièces rares — source à définir (mintage→percentile ?).
- **Bloc communauté Discord** en bas (« Reste connecté »).
- **CTA fond solide** (le fondu transparent bave sur la carte récit sombre).
- **Noms EN** (theme catalogue en anglais) → `coin.names.fr` (chantier i18n, commun avec la vue Pièces).

### Session 5b — Nettoyage CoinDetail (retours PO « clean tout »)
Le PO a relevé plusieurs scories sur la fiche. Corrigées :
- **CTA cassé** (flottait au milieu + dégradé qui bave) : était `position:absolute` dans un conteneur scrollable → se calait sur le bas du contenu. Passé en **`position:sticky; bottom:0` + fond solide** (border-top + ombre). Padding-bottom du root retiré.
- **Double barre en bas** : la nav principale (Coffre/Scan/Profil) s'affichait sur la fiche (sous-page) et le CTA se cachait derrière. → **nav masquée quand `meta.nav === null`** (`v-if="nav"` dans AppShell) : la fiche devient une vraie sous-page plein écran (back + CTA), cohérent CoinSnap. N'affecte que la fiche + le 404.
- **Numéros lourds 01/02…** : retirés (`perl` sur les `span.coin-detail-section__num`).
- **3D sur la tranche** : la rotation Y continue passait la moitié du temps de profil. Remplacée par un **balancement turntable face caméra** (`rotation.y = sin(t·0.5)·0.45`, ±~26°) + léger tilt → jamais une tranche fine. (Affecte aussi le spotlight best-coins, en mieux.)
- **Percentiles plats** (P25=P50=P75) : 3 cartes identiques → **une seule « Cote estimée »** quand `|p75−p25|<0,01`.
- **Données pourries affichées** : `designDescription` (souvent juste le titre EN) n'est montré comme description avers que si **≥ 40 car.** ; **metric « Tranche » verbeux retiré** des caractéristiques (le lettering de tranche est dans Design) ; **description redondante en bas retirée**.

Vérifié sur 5174 propre : fiche owned (Monaco) — 3D face caméra, CTA solide pinné bas (sans nav, sans chevauchement), Design = lettering réel only, percentiles compactés. Scan (body partagé) intact + lisible sombre. `typecheck`/`build` ✅, console propre.

Fichiers : `components/CoinDetailBody.vue`, `components/Spotlight3D.vue`, `scenes/AppShell.vue`, `styles/coin-detail.css`.
