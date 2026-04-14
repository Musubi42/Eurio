# Prototype — Decisions log (Agent A / Foundation)

> Trancher les divergences entre les 5 DESIGN-NOTES des agents de l'archive et
> produire un socle unifié pour le prototype navigable. Chaque décision est
> documentée avec : **contexte**, **alternatives**, **choix**, **raison**.
>
> Date : 2026-04-13 · Auteur : Foundation Agent (Phase 1 du prototype)

---

## 1. Font stack — Fraunces + Inter Tight + JetBrains Mono

**Contexte.** Conflits cross-agent observés :
- onboarding, coin-detail, vault, profile → **Fraunces** (italic, opsz variable)
- scan → **Instrument Serif** (regular + italic)
- onboarding note "Inter Tight", scan & vault notent "Inter", profile note "Inter"

**Alternatives.**
- a) Fraunces + Inter Tight + JetBrains Mono (3 familles)
- b) Instrument Serif + Inter + JetBrains Mono
- c) System stack uniquement (perte d'identité musée)

**Choix — a.** Raphaël a figé Fraunces + Inter Tight + JetBrains Mono dans le
brief. On honore la décision produit. `tokens.css` expose
`--font-display | --font-ui | --font-mono`. Le mockup archivé "scan" qui utilise
Instrument Serif reste intouchable (archive), mais les scenes Phase 2 migrées
devront utiliser Fraunces.

**Raison.** Italic caractère éditorial, variable opsz/wght gère tous les usages
de la scan (titres discrets) au profile (titres de médaille 62 px). Une seule
serif à charger → bundle Google Fonts plus léger.

---

## 2. Indigo canonique — `#1A1B4B` en `--indigo-700`

**Contexte.** Chaque agent a défini son propre indigo :
- onboarding `#1A1B4B`, surface app `#0B0C2E`
- scan `#1A1B4B` + variants #2A2C63 / #4A4E8C
- coin-detail `#0E0E1F → #15163A` (hero), `#1A1B4B` = accent
- vault `#0E0E1F … #9394B3` (scale 3 → 900)
- profile `#1A1B4B` surface d'honneur

**Choix.** On construit une échelle 50 → 950 avec `#1A1B4B` comme **brand
primary** en `--indigo-700`. `#0E0E1F` devient `--indigo-900` et `--ink`,
`#0B0C22` devient `--indigo-950` (stage background hors device).

**Raison.** `#1A1B4B` est le seul shade présent chez 4 agents sur 5 → c'est
l'ancre la moins contestable. Reste de l'échelle dérivé en interpolant vault +
profile + coin-detail.

---

## 3. Gold palette — un seul `--gold: #C8A864`, variantes named

**Contexte.** Les 5 agents utilisent tous `#C8A864` au centre. Variations en
périphérie : `#E3C98A` (onboarding hover), `#E0C688 / #D9BF87 / F5EBD3` (coin-
detail), `#B8974E` (vault), `#A7883F` (onboarding gradient dark).

**Choix.** Échelle `--gold-100 / 300 / 400 / 500 / 600 / 700`, + alias
`--gold-soft`, `--gold`, `--gold-deep`. Jamais plus de 3 golds dans une scene.

**Raison.** Préserver le contrat "or = moment" documenté par coin-detail et
profile : l'or n'est pas un neutre chaud, c'est un accent sémantique.

---

## 4. Router — hash API pure (pas History API)

**Contexte.** Le prototype est servi par `python3 -m http.server`, aucun
serveur-side rewrite possible. Fallback 404 impossible.

**Alternatives.**
- a) `location.hash` + `hashchange`
- b) `history.pushState` + catch-all `index.html`
- c) file-based navigation (un HTML par page, liens classiques)

**Choix — a.** Hash router ES module (`_shared/router.js`, ~200 lignes).

**Raison.** (b) nécessite un serveur qui rewrite vers `index.html` ; impossible
avec Python http.server. (c) casse le shell persistant (status bar, bottom nav,
badge version 7-tap) parce qu'il se re-monte à chaque nav. Le hash router
préserve l'état DOM du shell et survit à ngrok sans config.

---

## 5. Scenes en **fragments HTML** fetched par `_shared/router.js`

**Contexte.** Comment injecter une scene dans le shell ?

**Alternatives.**
- a) Fragment HTML + `innerHTML` (scene sans `<html>/<head>/<body>`)
- b) Shadow DOM par scene
- c) iframe par scene

**Choix — a.** Scene = fragment HTML injecté dans `#view`. Optionnel : sidecar
`scenes/<name>.js` qui exporte `mount({ params, query, state, data, navigate })`.

**Raison.** (b) bloque l'héritage des CSS variables (on perdrait `tokens.css`).
(c) casse la navigation clavier + la transition entre scenes + double le
scroll. (a) marche immédiatement, debug facile via DevTools (pas de shadow
root).

---

## 6. localStorage namespace `eurio.proto.v1`

**Contexte.** Plusieurs prototypes pourraient cohabiter dans le même origin
(ex. si Raphaël sert aussi l'archive `docs/design/` sur `localhost:8000/docs/`).

**Choix.** Toute la persistence passe par une seule clé JSON
`eurio.proto.v1`. Le suffixe `.v1` est volontaire : toute évolution
incompatible passera à `.v2` avec une mini migration en `state.load()`.

**Raison.** Un seul point de reset (`#/debug/reset`), un seul `JSON.parse`, un
seul emplacement à lire quand on débogue en DevTools. Scope-propre.

---

## 7. Status bar — heure statique `9:41`

**Contexte.** Faut-il afficher l'heure réelle ?

**Alternatives.**
- a) `9:41` en dur (heure de référence Apple keynote)
- b) Heure réelle mise à jour chaque minute
- c) Cachée sur les captures

**Choix — a.** `9:41` en dur, côté markup shell.

**Raison.** Le prototype est aussi un outil de review et de capture d'écran.
Une heure qui bouge pollue les screenshots et introduit un faux signal de
"hot reload". Convention standard de l'industrie (Apple, Figma Community).

---

## 8. Responsive breakpoint `≤ 500px` pour supprimer le device frame

**Contexte.** Pixel 9a = 412 × 915 px logical, iPhone 14 = 390 × 844, iPhone
SE = 375 × 667. En dessous de quelle largeur on masque le device bezel pour
laisser la scene prendre tout l'écran ?

**Alternatives.**
- a) ≤ 500 px
- b) ≤ 430 px (juste au-dessus de l'iPhone 14 Pro Max)
- c) Query media `hover: none` + `pointer: coarse`

**Choix — a.** Media query `max-width: 500px`.

**Raison.** 500 est au-dessus du plus large téléphone de test (Pixel 9a 412
px) et en-dessous du plus petit format desktop couramment utilisé (iPad
portrait 768, même mini 744). Si on voit ngrok depuis un navigateur resizé,
500 px est un seuil mental "ceci est un téléphone".

---

## 9. Seed collection — `firstRun: true`, aucune pièce préchargée

**Contexte.** Le brief propose deux options : seed vide (vraie expérience
onboarding) ou seed démo (coffre pré-rempli pour démos).

**Choix.** État initial **vide** (`firstRun: true`, `collection: []`).
`state.js` expose la surface pour un futur `seedDemoCollection()` mais la
fonction n'est **pas shippée en Phase 1** — à ajouter en Phase 2 si un agent en
a besoin pour démontrer le coffre rempli.

**Raison.** On veut que Raphaël et les testeurs physiques vivent vraiment le
parcours first-run au premier scan, sans "cheat mode" par défaut. Le reset
`#/debug/reset` permet de revenir à cet état à tout moment.

---

## 10. Scene sidecar pattern (`scenes/xxx.js` avec `mount()`)

**Contexte.** Les scenes ont parfois besoin de JS (timer auto-advance,
listeners debug…). Où vit ce code ?

**Alternatives.**
- a) `<script>` inline dans la scene HTML
- b) Fichier sidecar `scenes/xxx.js` avec export `mount({ ... })` importé
  dynamiquement par le router après injection
- c) Un gros event-delegator global qui dispatche par `data-scene`

**Choix — b.** Sidecar importé à la volée. Voir `scenes/scan-idle.js`.

**Raison.** (a) viole la règle "zero `<script>` inline" du brief. (c)
couple tout le JS du prototype dans un seul fichier qui grossit sans borne —
mauvais à 26 scenes. (b) garde la colocation scene + logique, permet aux
agents Phase 2 de ne pas modifier `_shared/router.js`, et autorise le cleanup
scoped (on listen `hashchange` une seule fois par mount).

---

## 11. Coin SVG — métal + label, pas d'images réelles

**Contexte.** Aucune image BCE/Numista n'est dispo localement. Comment
représenter une pièce dans le coffre ou dans un résultat scan ?

**Choix.** `data.coinSvg(coin, {size, showLabel})` génère un SVG inline :
radial-gradient par classe de métal (copper ≤ 5c, nordic gold 10-50c, bi-metal
≥ 1€), texte face value en Fraunces italic, sub-label année en JetBrains Mono.
Angle de tilt `seed(eurioId) → ±0.5°` pour éviter le look "série catalogue
cloné" mais rester discret.

**Raison.** 2938 pièces × téléchargement d'images = pas de POC navigable. Le
SVG paramétré marche offline, scale à tout DPI, reste aux couleurs des tokens,
et fait des captures esthétiques.

---

## 12. Debug mode — badge 7-tap runtime, pastille rouge persistée en LS

**Contexte.** `_shared/dev-debug-strategy.md` impose un badge version top-left
avec 7-tap detector + pastille rouge. À implémenter en JS vanilla.

**Choix.** Le badge vit dans `index.html` (partout), `router.js` installe le
listener 7-tap une seule fois au boot. `state.debugMode` est persisté en
localStorage et réhydraté au prochain chargement. Reset du compteur après 2 s
d'inactivité. Un `CustomEvent('debug:toggle')` est dispatché pour que les
scenes puissent réagir (ex : `scan-idle` montre un bouton "forcer un match").

**Raison.** Pattern fidèle au dev-debug-strategy.md (persistance + indicateur
visuel passif), implémentable en vanilla, portable tel quel en Compose Kotlin
plus tard (7-tap + DataStore).

---

## 13. Ne pas charger Google Fonts en self-hosted en v1

**Contexte.** Self-host donne un meilleur FCP offline, mais nécessite
télécharger les `.woff2`, versioner, gérer les variants.

**Choix.** Google Fonts via `@import` avec `display=swap`. À revoir quand le
prototype tournera offline (ngrok assume online).

**Raison.** POC sert à valider la navigation et les interactions, pas la perf
de chargement. Self-host = YAGNI tant que Raphaël n'en parle pas.
