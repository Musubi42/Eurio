# Plan — Refonte proto (enseignements CoinSnap) → Android prod

> Suite du [teardown CoinSnap](./README.md). Ce doc reformule le chantier décidé avec le PO
> le 2026-06-15 et découpe le travail. **Statut : plan validé sur les 4 décisions, en attente
> du « go » sur le 1er chunk.**

## 0. Vision en une phrase

On affûte le **proto web (PWA)** scène par scène en intégrant les bons patterns de CoinSnap,
on déploie à chaque chunk (`go-task proto:deploy` → Vercel → PWA installée au tel), le PO
audite sur son téléphone, on itère ; **une fois le proto verrouillé**, on porte le tout en
**Android prod** en garantissant que la prod ne contient *que* de la prod (le debug/QA part
dans les variantes dédiées).

## 1. Boucle d'itération (le workflow qu'on suit)

```
  édit scènes Vue (admin/packages/proto/src/scenes/*)
        │
        ▼
  go-task proto:deploy        ← régénère catalogue depuis eurio.db, build, deploy prebuilt Vercel
        │
        ▼
  PWA auto-update sur le tel   ← registerType:'autoUpdate' ; PO rouvre l'app
        │
        ▼
  audit PO : « ça oui / ça non »  ← chunk-by-chunk, on attend le retour avant d'enchaîner
        │
        └──► itère ou chunk suivant
```

Contraintes durables : **R1 proto-first STRICT** (tout design naît ici avant Compose),
**R2 tokens** (`shared/tokens.css` seul, jamais édités côté proto), **chunk-by-chunk avec
audit visuel** (livrer + attendre la rétro, ne pas enchaîner sans « go »).

> Pour le dev local rapide sans déployer : `go-task proto:dev` expose sur le réseau
> (`host:true`, port 5174) → accessible direct au tel sur le même wifi. À utiliser pendant
> qu'on bosse ; `proto:deploy` pour les audits « propres » hors-maison.

## 2. Décisions PO (2026-06-15) — figées

| # | Décision | Implication |
|---|---|---|
| D1 | Reveal : **toggle Yours↔canonique** + render **3D coté annoté en fiche détail** (pas dans le reveal) | Reveal garde sa charge émotionnelle ; le technique va dans CoinDetail |
| D2 | Coffre : **stat-bar patrimoine** (€·pièces·pays) **+ section best coins** badgée (Rarest/Most Valuable) | Double levier de pull éthique |
| D3 | Éditorial : **section in-app complète** (pièce du jour + articles, façon Expert Picks / Coin Talk) | Gros chantier neuf : surface + fixtures contenu |
| D4 | Narratifs : **data dure + 1 ligne factuelle** (pas de paragraphes IA invérifiables) | Réutilise `getRecit`/`getMarket` existants, ton factuel |

## 3. État du proto (point de départ réel)

- Shell nav : scan / vault / marketplace / profile + reveal — **déjà le pattern FAB-central** validé par CoinSnap.
- `RevealStratifie.vue` : héros 3D + bottom-sheet 2 crans + jalons/célébrations (déjà riche).
- `CoinDetail.vue` (346 l.) : hero **Ta capture + Référence**, sparkline cote, stats ownership, sets, variantes nationales, design-group.
- `VaultHome` + Coffre (tabs coins/sets/catalog, filtres, recherche, carte-à-gratter pays).
- Données dispo (`api/types.ts`) : `mintage`, `diameterMm`, `weightG`, `composition`, `edge*`, `Market{rarity, grades, history, projection}`, `getRecit`.

→ Conséquence : **E1/E2/E3 = enrichissement**, **E4/E5 = composition de données existantes**,
seul **E7 (éditorial) = surface neuve**.

## 4. Découpage en chunks (proto)

> Ordre proposé : impact visible + autonomie d'abord. Chaque chunk = livrable déployé + audit tel.

| Chunk | Scène(s) | Contenu | Pépites | Données | Taille |
|---|---|---|---|---|---|
| **C1 — Coffre patrimoine** | `VaultHome`, `CoffreHeader` | Stat-bar €·pièces·pays en hero + carrousel « tes meilleures pièces » badgé (rareté mintage / valeur) | E5, E4 | dispo (Market value+rarity) | M |
| **C2 — Reveal toggle** | `RevealStratifie`, `CoinDetail` | Toggle Yours↔canonique (superposition, switch au même endroit) ; harmoniser le dual-photo de CoinDetail en toggle | E1 | dispo | S |
| **C3 — Fiche technique** | `CoinDetail` | Section Physical Features : render **3D coté annoté** (Ø/épaisseur) + table composition/designer/edge ; 1 ligne narrative factuelle | E2, E3 | dispo (3D lib + types) | M |
| **C4 — Éditorial in-app** | nouvelle(s) scène(s) | Pièce du jour (Expert Picks) + articles (Coin Talk) : liste + détail + fixtures contenu | E7 | **à créer** (fixtures) | L |
| **C5 — Historique & sets** | `Profile`, sets | « Your History » (scans ≠ possédés) + exposer custom-set à l'ajout | E8, E9 | dispo | S |

**Points design à trancher en cours de route (à l'audit, pas bloquants) :**
- C4 : où vit l'éditorial ? On est scan-first (le scan = la home), donc pas de « home » à la
  CoinSnap. Options : nouvel onglet, ou section dans vault/profile, ou carte sur l'idle-scan.
  → on tranchera au moment du C4 avec un proto sous les yeux.
- C1 : axes de badge « best coins » — rareté (mintage) seule, ou mintage + valeur + complétude ?

## 5. Phase 2 (après verrouillage proto) — port Android prod + séparation dev

> Pas maintenant. Cadré ici pour mémoire.

1. **Port Compose** des scènes proto verrouillées (R3 : maj `scene-parity.md` / `components-parity.md`).
2. **Durcissement prod/dev** : aujourd'hui le debug est gaté `BuildConfig.DEBUG` dans le NavHost
   (`features/dev/*` absents du release). À décider : on renforce en **flavor `dev` dédié**
   (vs simple buildType) pour que prod = strictement prod, dev/QA = tout l'outillage. Le build
   est déjà sain ; ce sera un nettoyage, pas une reconstruction.

## 6. Livré — batch C1+C2+C3+C5 (2026-06-15, déployé sur eurio-proto.vercel.app)

| Chunk | Statut | Détail |
|---|---|---|
| C1 | ✅ | Carrousel « Tes meilleures pièces » dans `VaultHome` (badges 👑 plus rare / 💎 plus précieuse, valeur = cote marché `getMarket.p50`). Stat-bar patrimoine **existait déjà** (non touchée). |
| C2 | ⏸️ reporté Android | Toggle Ta photo↔Référence **retiré du proto** après audit tel : le proto n'a pas de vraie capture → SVG factice trompeur + double-toggle cluttered. E1 a sa place sur **Android** (capture réelle). Hero revenu propre : image + 1 toggle Avers/Revers. |
| C3 | ✅ | Section « Caractéristiques » enrichie dans `CoinDetail` : diagramme SVG annoté (Ø) + métriques (diamètre/poids/tranche) + 1 ligne factuelle (type · métal · tirage). Pas de Three.js (SVG = plus léger). |
| C5 | ✅ partiel | `scanHistory` au store + log au reveal + vue `/profile/history` (badge Au coffre/Scannée). **Custom sets (E9) déféré** : conflit archi sets-catalogue. |

### Bugs/dette repérés à l'audit tel (2026-06-15)
- **`coin.theme` pollué** : certaines pièces ont `theme = "2nd map"` (label de revers commun 2e série) au lieu d'un vrai thème → titre de récit moche. **Fix référentiel** (eurio.db), pas proto.
- **CTA sticky `coin-detail-cta`** : fondu transparent→surface qui bave sur la carte récit sombre. Polish à faire (fond solide ou récit qui s'arrête avant le CTA).
- Page fiche **très dense** (hero + toggle + ownership + récit long + 6 sections) : revoir la hiérarchie/longueur.

### Reste / déféré (à trancher au review)
- Toggle Yours↔canonique **dans le reveal 3D** (C2b).
- **Custom sets utilisateur** (E9) — design d'archi à part.
- **C4 éditorial** (E7) — pas dans ce batch (surface neuve + fixtures).
- Question ouverte C1 : la **« Valeur totale »** du coffre reste basée sur la faciale (`valueAtAddCents`), pas sur la cote marché. À décider si on l'aligne sur `getMarket.p50` comme le carrousel.

### Checklist audit tel
1. **Coffre** : carrousel « Tes meilleures pièces » sous les stats — badges lisibles, scroll horizontal fluide, valeurs cohérentes ?
2. **Fiche pièce** (tape une pièce) : toggle Ta capture/Référence (switch au même endroit) + section Caractéristiques (diagramme Ø + métriques + ligne factuelle).
3. **Profil → Activité → Historique des scans** : liste des scans, badge Au coffre/Scannée, tap → fiche.

> Pré-requis pour voir le coffre peuplé : seed démo via Profil → Paramètres (debug) si le coffre est vide.
