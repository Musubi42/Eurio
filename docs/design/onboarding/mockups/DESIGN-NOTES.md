# Onboarding — Design notes

> Mockups haute-fidélité du parcours d'entrée Eurio. HTML standalone, 390 × 844, device-framed.
> Base : `docs/design/onboarding/README.md`, `PRD.md` §6, `_shared/auth-strategy.md`.
> Date : 2026-04-13.

## Direction générale

- **Concept** : "Stripe meets museum". Fond indigo nuit (drapeau européen), or brossé numismatique, serif Fraunces italique en display pour un hint patrimoine, Inter Tight en body pour la précision.
- **Tempo** : mesuré, sobre, respirant. Pas de confettis, pas de gradient kitsch, pas de gamification criarde.
- **Pièce hero** : SVG radial gradient + anneaux concentriques + 12 étoiles (référence euro) + cœur serif italique "2€". Animation `breathe` (3,4 s ease-in-out) + halo or qui pulse. Pas de rotation — la pièce est posée, pas spectacle.
- **Atmosphère** : grain SVG subtil (opacity ~.08–.12, mix-blend overlay) + rings décoratifs dorés dashed pour rappeler un instrument de précision (boussole / loupe numismate).

## Fichiers

| Fichier | Rôle |
|---|---|
| `index.html` | Landing type "éditorial" avec mini-previews iframe de tous les écrans, palette, typo |
| `00-splash.html` | Splash au lancement de l'app |
| `01-welcome.html` | Écran 1/3 — pièce pulsante, CTA "Commencer", "Passer" visible |
| `02-vault.html` | Écran 2/3 — aperçu coffre 6 pièces, delta +12 % |
| `03-achievements.html` | Écran 3/3 — grille 8 pièces France, 2 manquantes en pointillé |
| `04-permission-camera.html` | Bottom sheet de demande de permission caméra, viewfinder dimmed en arrière-plan |

## Design system appliqué

- **Palette** : `#1A1B4B` indigo primary, `#0B0C2E` surface app, `#C8A864` or brossé, `#E3C98A` or clair (hover/italic), `#FAFAF8` paper pour sheets, `#0E0E1F` ink, `#6EB488/9BD3B2` accent vert delta positif.
- **Typo** : Fraunces (opsz variable) pour display/headings, Inter Tight pour UI, JetBrains Mono pour micro-typographie de l'index (édition/press).
- **Radius** : 54px device, 24px cards/sheets, 16px boutons, 14px cells, 999px pills.
- **Spacing** : rythme 4/8/12/16/18/22/28/48.
- **Boutons** :
  - Primary or : gradient `#D9BE7E → #C8A864 → #A7883F`, inner highlight + inner shadow + glow or, texte `#1A1205`, flèche circulaire.
  - Primary indigo (sheet permission) : gradient `#232466 → #1A1B4B → #0F103A`, texte or clair.
  - Ghost : 56×56, bordure subtle, pour back nav.
- **Status bar et home indicator** Android-like pour crédibilité device-framed.

---

## Écran par écran

### 00 — Splash

**Hiérarchie**
1. Anneaux concentriques dorés dashed (boussole)
2. Pièce dorée centrale avec halo pulsant
3. Wordmark `Eur*io*` (Fraunces, "io" italic or)
4. Tagline "Numismatique · Européenne" (micro, tracking 3px)
5. Barre de progression fine + ligne "Musubi · 2026"

**Interactions** : durée max 1,2 s en prod. Tap partout = skip vers l'écran 1 (mais en pratique auto-transition).

**Data bindings** : aucun. Tout statique (build-time).

**États** : n/a — écran transitoire.

### 01 — Welcome (scan)

**Hiérarchie**
1. Top bar : brand Eurio + `Passer` (pill ghost, tap target 44×44 min)
2. Zone pièce (height 360) avec rings décoratifs et pièce qui respire
3. Pager `● ○ ○` doré
4. Eyebrow "Étape 1 sur 3" + H1 serif "Scanne la pièce que tu as en main." + sub
5. CTA "Commencer →" pleine largeur, or gradient
6. Legal : "Fonctionne hors-ligne · Aucun compte requis"

**Interactions**
- Tap `Commencer` → déclenche permission caméra système (écran 04 en overlay Android natif)
- Tap `Passer` (top right) → bypass tout l'onboarding, direct sur l'onglet Scan, flag `onboarding_completed=true` en DataStore
- Pas de swipe horizontal — navigation au bouton uniquement (confirmé PRD).
- Animation `breathe` (3,4 s) + `halo` (3,4 s) en phase. À couper si `prefers-reduced-motion`.

**Data bindings** : tous les textes statiques (resources strings FR). Le visuel pièce est un asset SVG embarqué dans l'APK (pas de fetch).

**États edge**
- `Passer` tappé → SharedPreferences `skipped=true`, pas d'auto-revive des écrans.
- Device sans caméra → CTA affiche "Continuer" et skip l'étape 04.

### 02 — Coffre (vault preview)

**Hiérarchie**
1. Top bar (idem 01)
2. Carte "Ton coffre · aperçu" glassmorphism subtle : label or + total `86,40 €` serif 40px + delta `+12 %` (pill vert) + stat row "Pièces / Pays / Séries" séparé par dashed
3. Strip "Ajoutées récemment" : grille 3×2 de mini pièces SVG avec drapeau emoji + millésime
4. Pager `○ ● ○`
5. Eyebrow "Étape 2 sur 3" + H1 "Ton coffre, bien ordonné."
6. CTA : back ghost + `Suivant →`

**Interactions** : back ghost → écran 1, primary → écran 3. Pas de tap sur les mini coins (onboarding = non-interactif sur la preview).

**Data bindings** : valeurs **dummy hardcodées** pendant l'onboarding (onboarding n'a pas accès à une vraie collection). En prod, les textes statiques restent les mêmes ; seule la visu est un asset préparé.

**États edge** : le delta `+12 %` est purement illustratif — éviter toute confusion. Option : tagger visuellement "exemple" si des testeurs le prennent pour leur vrai coffre. **Question ouverte.**

### 03 — Achievements (séries)

**Hiérarchie**
1. Top bar (idem)
2. Carte "France · circulation" : flag rond cocarde CSS + sous-titre "Série des 8 valeurs" + badge `6 / 8` or
3. Progress bar or brossé à 75% + label
4. Grille 4×2 de cells : 6 "done" (pièce SVG + tick or) et 2 "missing" (hachures diagonales + cercle pointillé `+`)
5. Pager `○ ○ ●`
6. Eyebrow "Étape 3 sur 3" + H1 "Complète des séries entières." + sub (explicitement anti-kitsch : "sans points kitsch, sans notifications agressives")
7. CTA : back ghost + `C'est parti →`

**Interactions** : `C'est parti` → finalise l'onboarding, va direct sur l'onglet Scan (caméra active).

**Data bindings** : exemple France dummy. Alternative en prod : choisir un pays statique neutre (Allemagne ?) pour ne pas donner l'impression que l'user a déjà scanné.

**États edge** : même remarque que 02 sur la clarification "exemple".

### 04 — Permission caméra

**Hiérarchie** (bottom sheet 100% au premier tap sur "Commencer")
1. Arrière-plan : viewfinder dimmed avec cercle pointillé or + texte "∅ Pointer une pièce" (aperçu de ce que l'user va obtenir)
2. Top : brand + `Annuler` (pill)
3. Sheet blanche radius 28 haut :
   - Handle bar
   - Icon box indigo avec icône caméra or + stroke lumineux
   - Titre "Autoriser l'appareil photo" + sous-titre
   - Body : "aucune image envoyée sur Internet", mise en avant du on-device
   - Liste 3 promesses avec ticks : aucune photo sauvegardée, 100 % hors-ligne, révocable
   - CTA primary indigo "Autoriser la caméra →"
   - CTA secondary ghost "Plus tard — continuer sans scanner"
   - Footer dashed : mention shield "Confidentialité by design · Android 13+ permission native"

**Interactions**
- `Autoriser` → déclenche le dialog système Android natif (ce mockup est le pré-prompt Eurio, pas le dialog OS). Pattern Duolingo : expliquer avant de demander pour maximiser le taux d'acceptation.
- `Plus tard` → bypass, va sur l'onglet Scan en mode "permission manquante" (affichera un prompt retry sur l'écran Scan).
- `Annuler` (top) → retour à l'écran 1.

**Data bindings** : statique.

**États edge**
- **Permission refusée** (user tape "Refuser" sur le dialog OS) → retour à l'écran Scan en état "permission manquante" avec banner + bouton deep-link vers les settings Android.
- **Permission refusée définitivement** (double refus) → banner persistant sur Scan avec CTA "Ouvrir les réglages".
- **Device sans caméra** : l'écran 04 est skippé entièrement.
- `prefers-reduced-motion` : désactiver `breathe` / `halo`.

---

## Décisions de design prises

1. **Serif Fraunces italic en display, pas sans-serif** — commit fort sur le feel musée/patrimoine. Inter Tight en UI garde la précision Stripe.
2. **Pièce hero SVG animée** — vraie pièce dessinée (gradient radial + 12 étoiles + reeded edge) plutôt qu'un emoji ou une image bitmap. Asset léger, nette à tout DPI, animable sans JS.
3. **Bouton primaire or à gradient + inner shadow** — évoque une pièce frappée, pas un bouton d'app. Utilisé sur 01/02/03. Sur 04 le primaire devient indigo (contexte = dialog de confiance, on veut du calme institutionnel).
4. **Pre-prompt avant la permission Android** — écran 04 est pédagogique, lists les promesses privacy avant même d'invoquer le dialog OS. Pattern qui augmente le taux d'accept.
5. **Pager en tirets dorés, pas en dots** — plus éditorial, rappelle les marques d'une barre de progression mécanique / vernier. Confirme l'aesthetic numismate.
6. **Skip visible dès l'écran 1** en pill ghost top right, conforme au PRD (pas caché).
7. **Grille 4×2 avec hachures diagonales pour les cells manquantes** — pas de points d'interrogation, pas de verrous. Juste l'absence, élégante.

## Questions ouvertes / blockers

- [ ] **Preview data** écrans 02/03 : l'user pourrait croire qu'il a déjà une collection. Faut-il tagger visuellement "exemple" ou utiliser un wording différent ("voilà à quoi ça ressemblera") ?
- [ ] **Asset pièce hero** : on a dessiné un "2€" générique sans face nationale. À confirmer avec Raphaël si on veut garder ce neutre, ou plutôt montrer la commémorative du moment (Bulgarie 2026 ?). Voir question ouverte du README onboarding.
- [ ] **Fonts** : Fraunces + Inter Tight = 2 familles Google Fonts. En prod Kotlin Compose, il faudra les embarquer en `.ttf` (taille APK ~400 Ko). Alternative : system-ui + un serif système (mais on perd l'italic de caractère).
- [ ] **Dark mode only** pour l'onboarding : décision implicite ici. Le reste de l'app pourrait être light + dark. À trancher dans le README de la vue Scan / Coffre.
- [ ] **Reduce motion** : prévoir `@media (prefers-reduced-motion)` pour désactiver breathe/halo dans l'impl Compose.
- [ ] **Badge "6 / 8"** et progress bar sur écran 03 : est-ce qu'on expose le pourcentage (75 %) ou juste la fraction ? Les deux sont affichés ici ; à simplifier en impl si redondant.
- [ ] **Test Pixel 9a** : le viewport 390 × 844 est iPhone-like. Pixel 9a c'est ~412 × 915 dp. Les layouts sont résilients (flex) mais à revérifier.

## À valider avec d'autres agents

- **Scan** : l'écran 04 prévisualise un viewfinder cercle pointillé or. Le vrai UI scan doit matcher ce cercle pour que la transition soit visuellement cohérente.
- **Coffre** : le total `86,40 €` et le delta `+12 %` doivent utiliser le même formatting (espace insécable + virgule, pill vert bordée). À documenter dans `_shared/data-contracts.md` si pas déjà fait.
- **Profil** : le pattern brand (bullet or + Fraunces) doit être repris en top bar partout.
