# Sous-vue — Coffre / Mes pièces (v1-offline)

> Doc-pont. Sous-vue de [`04-coffre`](./04-coffre.md). Overview : [`../README.md`](../README.md).

## 1. Rôle

> **Ce que j'ai chassé.** Le vault perso : toutes mes pièces scannées, organisables. C'est la preuve
> tangible de la collection — le siège de l'**attachement**.

**Drive primaire** : endowment/contrôle — secondaires : Valeur, Sens.

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Endowment** (possession → survaluation) | « **mes** pièces » → attachement par propriété | [`07`](../../psychologie-documentation/07-sens-storytelling.md) · [`01`](../../psychologie-documentation/01-motivations-baseline.md) |
| **IKEA effect** (résiduel — hérité du scan) | « **moi** qui les ai trouvées » → attachement par effort, activé au scan | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Désir de contrôle / structure** | trier/filtrer = ordonner le chaos (réconfort, agentivité) | [`01`](../../psychologie-documentation/01-motivations-baseline.md) |
| **Valeur cumulée** | « ma collection vaut €X » — statut + sécurité financière | `01` · mission Valorisation |

## 3. Actions × biais

| Action | Levier |
|---|---|
| Voir la **grille** peuplée (ce que j'ai) | endowment (fierté de possession) |
| **Filtrer** (pays/type/valeur) · **trier** | contrôle/structure |
| **Rechercher** | contrôle |
| Voir la **valeur totale du coffre** (réelle ≠ faciale) | valeur/statut |
| Tap une pièce → [`03-page-piece`](./03-page-piece.md) | progressive disclosure / autonomie SDT (`01`) |

## 4. Contenu

- **Grille** (médaillons), filtres en chips, tri (pays/valeur/date), recherche en overlay.
- **Bandeau valeur** : valeur réelle agrégée + (optionnel) « top X% » — comparaison descendante, formulé positivement uniquement (ex. « top 15% », jamais « bottom 85% »), en *info*, pas en alarme.
- **État vide** : illustration + CTA « Scanner ma première pièce » (l'onboarding crédite 1 pièce au départ — voir [`00-onboarding`](./00-onboarding.md)).

## 5. Garde-fous

- **Valeur jamais anxiogène** : pas de variation rouge clignotante ; informatif, pas spéculatif.
- L'attachement vient du **vrai** (pièces réellement chassées) — ne pas gonfler artificiellement.
- **Asymétrie positive** : afficher ce qu'on *a*, pas ce qui manque — ne pas exposer les trous en rouge/gris dans la grille par défaut.
- **SDT / autonomie** : les filtres servent l'agentivité de l'utilisateur, pas la création de sous-objectifs imposés.
- **top X% : statique ou hebdomadaire** — jamais recalculé temps-réel pour toujours flatter (`01`).

## 6. Drives servis

Endowment/contrôle ⬤ · Valeur ◑ · Sens ◔.

## 7. À proto'er (R1)

`vault-home.html` / `vault-empty.html` / `vault-filters.html` / `vault-search.html` existent → socle.
Neuf : le **bandeau valeur cumulée** (en info) → à proto'er/confronter au merge.
