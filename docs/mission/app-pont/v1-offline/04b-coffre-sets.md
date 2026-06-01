# Sous-vue — Coffre / Sets (v1-offline)

> Doc-pont. Sous-vue de [`04-coffre`](./04-coffre.md). Overview : [`../README.md`](../README.md).

## 1. Rôle

> **La complétion structurée.** Des sets (par pays, année, thème, ou perso) avec une planche
> silhouette : ce qui manque est *visible* donc *désiré*. Le moteur le plus pur du collectionneur.

**Drive primaire** : Complétion — secondaires : Statut (rareté), contrôle/structure.

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Goal-gradient** | « 9/10, plus qu'**une** ! » accélère l'effort près du but | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Zeigarnik** | chaque set ouvert = boucle mentale qui rappelle « finis-moi » | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Endowed progress** | avance offerte à l'onboarding : premières pièces scannées placent d'emblée sur la barre (jamais « 0/340 ») | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Goal-gradient** (silhouettes) | la planche montre **le manque** → effet « presque », jamais page blanche | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Sous-sets modulaires** | toujours un « presque fini » à portée | [`06`](../../psychologie-documentation/06-completion-double-axe.md) · `01` (drive contrôle — Cao) |
| **Tiers de rareté objectifs** | médaillons légendaires (Monaco/Vatican) = désir + hiérarchie | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |

## 3. Actions × biais

| Action | Levier |
|---|---|
| Voir la **liste des sets**, « en cours » d'abord | goal-gradient (on attaque le presque-fini) |
| Drill-down → **planche silhouette** (cases pleines/vides) | endowed progress + Zeigarnik |
| Repérer la **case manquante** pointée | goal-gradient (cible nette) |
| Tap case manquante → page pièce → **« où l'acheter »** | pont **affiliation** (revenu) |
| Compléter un set → **célébration Set complété** (cat. 2 — banderole + habillage, cf. consolidation §3) | peak-end / économie des célébrations |
| Créer un **set perso** | autonomie + contrôle/structure |

## 4. Contenu

- **Cards sets** : mini-planche + `X/Y` + filtres catégorie/état. Tri **in-progress first**.
- **Planche** (signature « classeur ») : médaillons owned / silhouettes missing, date sous la case.
- **Reward teaser** (indicateur visuel sur la case manquante annonçant la célébration qui suivrait sa complétion) + ajout manuel (long-press) pour les cas hors-scan.

## 5. Garde-fous

- **Jamais une montagne** : un grand ensemble est **découpé** en sous-sets atteignables.
- **Silhouette = invitation, pas reproche** : on montre le manque sans culpabiliser.
- **Rareté honnête** : les tiers viennent des **tirages réels**, jamais inventés.

## 6. Drives servis

Complétion ⬤ · Statut/rareté ◑ · contrôle ◑ · Valeur ◔ (pont achat).

## 7. À proto'er (R1)

`vault-sets-list.html` / `vault-sets-detail.html` existent (planche, progress) → socle solide. Neuf :
- **Célébration Set complété** (cat. 2) → ❌ à proto'er dans `vault-sets-detail.html` (état post-complétion).
- **Lien affilié** sur case manquante → ❌ à proto'er comme état de la case dans `vault-sets-detail.html`.

Pas de nouveau fichier nécessaire — merge dans `vault-sets-detail.html` uniquement.
