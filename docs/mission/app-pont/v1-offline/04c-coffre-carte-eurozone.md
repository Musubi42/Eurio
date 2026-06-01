# Sous-vue — Coffre / Carte eurozone (v1-offline)

> Doc-pont. Sous-vue de [`04-coffre`](./04-coffre.md). Overview : [`../README.md`](../README.md).
> **Le différenciateur** du domaine. La carte actuelle est « moche » → à **refaire belle**.

## 1. Rôle

> **La complétion *spatiale*.** Une carte de la zone euro qu'on **remplit/gratte** pays par pays.
> Un 2ᵉ axe de progression que Pokémon n'a même pas — et l'**asset partageable n°1**.

**Drive primaire** : Complétion (spatiale) — secondaires : Sens (géo/voyage), Social (partage).

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Zeigarnik (2ᵉ axe)** | la carte incomplète = une 2ᵉ boucle ouverte, distincte du dex | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Endowed progress** | avance visible (pays déjà colorés) = motivation à finir | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Carte à gratter** | gratter le contour d'un pays complété → **reveal dans le contour** (tactile + découverte) | [`06`](../../psychologie-documentation/06-completion-double-axe.md) · [`05`](../../psychologie-documentation/05-juice-du-scan.md) |
| **Goal-gradient par pays** | « il te manque 1 pays » > « 8/21 » | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Partage / preuve sociale** | « il me manque 3 pays » est intrinsèquement partageable | mission Croissance · (ancrage psy : → à étayer, cf. `02-social-partage` post-v1-online) |

## 3. Actions × biais

| Action | Levier |
|---|---|
| Voir la **carte**, fill par % owned (21 pays) | Zeigarnik spatial + endowed progress |
| Drill-down **pays** → planche silhouette + filtre (circulation/commémo) | goal-gradient |
| **Gratter** un pays complété → infos révélées dans le contour | carte à gratter (micro-interaction + découverte) |
| Compléter un pays → **célébration catégorie 3** (= pays complété → carte à gratter, cf. consolidation §3) | peak-end |
| **Partager** la carte | partage (asset n°1) |
| Toggle Carte / Liste | autonomie/contrôle |

## 4. Contenu

- **Carte** : blobs/contours des 21 pays (rappel : **21**, Bulgarie incluse 2026), gold fill par %,
  peek-card au tap. Mode liste alternatif.
- **Drill-down pays** : drapeau hero + progress + planche owned/silhouette + ajout manuel long-press.
- **Carte à gratter** : cf. §2 (mécanique tactile + reveal, référent *scratch maps* de voyageurs).

## 5. Garde-fous

- **Zeigarnik ≠ harcèlement** : la carte incomplète ne génère aucune notif culpabilisante — elle invite, elle ne presse pas.
- **Gratter = récompense, pas gimmick** : réservé au **pays complété** (sinon le geste se dévalue).
- Pas de pression : la carte invite (« découvre »), ne culpabilise pas.

## 6. Drives servis

Complétion ⬤ · Sens ◑ (voyage/géo) · Social ◑ (partage).

## 7. À proto'er (R1)

`vault-catalog-map.html` / `vault-catalog-country.html` existent (Canvas map, fill, planche) → socle.
**Neuf et prioritaire** : la **carte à gratter** (interaction + reveal-dans-contour) + le **redesign
« belle carte »** → proto avant Compose.
