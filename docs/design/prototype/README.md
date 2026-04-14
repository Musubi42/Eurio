# Eurio prototype navigable

Prototype HTML/CSS/JS vanilla du parcours Eurio — scan-first numismatique
européenne. Zéro framework, zéro build, servable par `python3 -m http.server`.

## Setup en 2 commandes

```bash
cd docs/design/prototype
./setup-data.sh     # copie ml/datasets/eurio_referential.json → data/ (gitignoré)
./serve.sh          # python3 -m http.server 8000
```

Puis dans le navigateur : <http://localhost:8000>.

### Test sur téléphone physique via ngrok

Dans un autre terminal :

```bash
ngrok http 8000
```

ngrok renvoie une URL publique `https://xxxx.ngrok-free.app` — ouvre-la sur
ton téléphone. Le shell passe automatiquement en plein écran en dessous de
500 px de largeur (voir `_shared/shell.css`).

## Architecture

```
prototype/
├── index.html                 # shell : device frame + status bar + #view + bottom nav
├── serve.sh                   # lance http.server:8000
├── setup-data.sh              # copie eurio_referential.json depuis ml/datasets/
├── .gitignore                 # exclut data/eurio_referential.json
├── data/                      # populated par setup-data.sh (gitignored)
├── _shared/
│   ├── fonts.css              # Google Fonts : Fraunces + Inter Tight + JetBrains Mono
│   ├── tokens.css             # toutes les variables CSS de design
│   ├── components.css         # classes réutilisables (btn / card / badge / …)
│   ├── shell.css              # device frame + responsive + bottom nav
│   ├── router.js              # hash router ES module + bootstrap
│   ├── state.js               # mock state + localStorage
│   ├── data.js                # fetch JSON + queries + coinSvg()
│   └── DECISIONS.md           # journal des arbitrages cross-agent
└── scenes/
    ├── scan-idle.html         # scène d'exemple (fragment HTML, pas de <html>)
    └── scan-idle.js           # sidecar optionnel : export mount({...})
```

### Le shell persistant

`index.html` monte une seule fois :
- `<div class="stage">` → `<div class="device">` → `<div class="screen">`
- Status bar (heure statique `9:41`)
- Version badge top-left (v0.1.0 + pastille rouge debug)
- `<main id="view">` — vidé / rempli par le router à chaque nav
- Bottom nav 4 tabs (Coffre, Scan central, Profil, Marché grisé)
- Home indicator

### Le router

`_shared/router.js` est un module ES qui :
1. Lit `location.hash` → `{ rawPath, query }`
2. Matche contre une table statique `ROUTES[]`
3. Fetch `scenes/<name>.html` et injecte dans `#view`
4. Importe dynamiquement `scenes/<name>.js` si présent et appelle son export
   `mount({ params, query, state, data, navigate })`
5. Met à jour l'onglet actif de la bottom nav
6. Redirige `#/` vers `#/onboarding/1` si `state.firstRun === true`, sinon
   vers `#/scan`

Routes reconnues (non exhaustif — voir `_shared/router.js`) :

| Route | Scène |
|---|---|
| `#/` | redirect (onboarding si firstRun, sinon scan) |
| `#/onboarding/1..3` + `/permission` | onboarding-1..3, onboarding-permission |
| `#/onboarding/replay` | reset firstRun et redirige |
| `#/scan` | scan-idle |
| `#/scan/matched` | scan-matched (query `?id=<eurioId>`) |
| `#/scan/failure` `#/scan/not-identified` `#/scan/debug` | idem |
| `#/coin/:eurioId?ctx=scan|owned|reference` | coin-detail |
| `#/vault` `#/vault/filters` `#/vault/search` | vault, vault-filters, vault-search |
| `#/profile` `#/profile/achievements` `#/profile/set/:setId` `#/profile/settings` | profile-* |
| `#/marketplace` | marketplace-soon (grisé) |
| `#/debug/reset` | vide localStorage → redirect onboarding |

Toute route qui pointe vers une scène non encore livrée affiche un placeholder
stylisé "Scène `xxx` — bientôt (Phase 2)".

## Ajouter une nouvelle scène

Les 5 agents Phase 2 vont migrer ~26 scenes. Pattern à suivre :

1. Créer `scenes/<nom>.html` comme **fragment HTML** (pas de `<html>`,
   `<head>`, ni `<body>` — juste le contenu injecté dans `#view`).
2. **Zéro inline CSS color ou font-family** ; toujours utiliser les variables
   de `_shared/tokens.css` et les classes de `_shared/components.css`.
3. Si un style est vraiment spécifique à la scène, ajouter un `<style>` en tête
   du fragment avec des sélecteurs scoped `.nom-scene-*`.
4. **Pas de `<script>` inline** ; si la scène a besoin de JS, créer
   `scenes/<nom>.js` qui exporte une fonction `mount(ctx)` — le router
   l'appellera après injection. `ctx` donne accès à `state`, `data`, `navigate`,
   `params`, `query`.
5. Ajouter la route correspondante dans `_shared/router.js` (tableau `ROUTES`).

Voir `scenes/scan-idle.html` + `scenes/scan-idle.js` pour le pattern de
référence (camera mock + L-corner guide + auto-advance 2 s).

## Où vivent les tokens et comment les modifier

Toute variable de design vit dans `_shared/tokens.css`. Cinq blocs :
couleurs (indigo, gold, surfaces, gray, semantic), typographie (font-family,
sizes, tracking), spacing, radius + shadows + inner highlights, easings +
durations. Jamais hardcoder un hex dans une scene — si une couleur manque,
ajoute la variable dans `tokens.css` puis référence-la.

Font loading : `_shared/fonts.css` importe Fraunces + Inter Tight + JetBrains
Mono depuis Google Fonts en `display=swap` (non-bloquant).

## Debug

- **Toggle debug mode** : 7 taps sur le badge `v0.1.0` top-left → pastille
  rouge allumée, `state.debugMode = true`, `CustomEvent('debug:toggle')`
  dispatché. Les scenes peuvent écouter pour révéler des contrôles cachés
  (ex : `scan-idle.html` affiche un bouton "FORCER UN MATCH").
- **Reset state** : naviguer vers `#/debug/reset` → vide localStorage, réinit,
  repart en `#/onboarding/1`.
- **Replay onboarding** : `#/onboarding/replay`.
- **Inspect state** : en console, `window.eurio.state.state`.

## Décisions

Tous les arbitrages cross-agent (merge des shades indigo, choix du hash
router, pattern sidecar, responsive breakpoint, etc.) sont documentés dans
[`_shared/DECISIONS.md`](./_shared/DECISIONS.md). À lire avant de contester un
choix.
