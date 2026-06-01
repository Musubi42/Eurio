# Vue — Coffre (parent) (v1-offline)

> Doc-pont psychologie → app. Périmètre **v1-offline**. Overview : [`../README.md`](../README.md).
> Vue à **3 sous-vues** — voir les docs dédiés :
> [`04a` Mes pièces](./04a-coffre-mes-pieces.md) · [`04b` Sets](./04b-coffre-sets.md) · [`04c` Carte eurozone](./04c-coffre-carte-eurozone.md).

## 1. Rôle

> **La collection** — le cœur du rituel renouvelable. Trois angles d'une même chose : ce que j'ai
> (Mes pièces), ce qu'il me reste à compléter (Sets), où dans l'Europe (Carte). C'est ici qu'on
> revient *même sans pièce neuve à scanner* (réponse au « bocal froid » : session sans pièce à scanner, l'user revient quand même).

**Drive primaire** : Complétion — secondaires : Sens (identité), Valeur, contrôle/structure.

## 2. Leviers psy transverses aux 3 sous-vues

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Zeigarnik (double axe)** | dex *et* carte = **deux boucles ouvertes** en parallèle | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Endowed progress + goal-gradient** | jamais « 0 vide » ; mettre en avant les « presque finis » | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Désir de contrôle / structure** | organiser/filtrer = mettre de l'ordre dans le chaos | [`01`](../../psychologie-documentation/01-motivations-baseline.md) |
| **Endowment effect** | les pièces que je possède sont à moi → attachement par propriété | [`01`](../../psychologie-documentation/01-motivations-baseline.md) |
| **IKEA effect** | cette pièce, je l'ai chassée/scannée → attachement par effort | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Sous-sets modulaires** | petites victoires, jamais une montagne « 0/340 » | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |

## 3. Structure

- **Segmented control** en tête (3 segments). Tri par défaut : **« en cours » d'abord** (goal-gradient).
- Les 3 sous-vues partagent la **rareté objective** (tirages) comme fil rouge (tiers visuels).

| Sous-vue | Angle | Drive dominant | Doc |
|---|---|---|---|
| **Mes pièces** | possession | endowment / sens (identité) | [`04a`](./04a-coffre-mes-pieces.md) |
| **Sets** | complétion structurée | goal-gradient | [`04b`](./04b-coffre-sets.md) |
| **Carte eurozone** | complétion spatiale | Zeigarnik 2ᵉ axe + partage | [`04c`](./04c-coffre-carte-eurozone.md) |

## 4. Garde-fous (transverses)

- **Jamais de montagne** : toujours des sous-sets atteignables (anti-démoralisation).
- **Zeigarnik ≠ harcèlement** : la boucle ouverte motive *dans* l'app ; pas de notif culpabilisante.
- **Valeur jamais anxiogène** (cf. `04a`).
- **Filtre SDT** : toute mécanique de complétion doit nourrir compétence (feedback de progression), autonomie (choix, pas de contrainte) et relatedness — cf. [`01`](../../psychologie-documentation/01-motivations-baseline.md) §5 / consolidation règle 7.

## 5. À proto'er (R1)

Détail par sous-vue. Le **segmented control** + planches silhouette existent en proto
(`vault-*.html`) → socle.

**Carte à gratter** ([`04c`](./04c-coffre-carte-eurozone.md)) → ❌ à proto'er avant tout code Android (nouveau composant, aucun équivalent dans `vault-*.html`).
