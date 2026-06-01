# Vue — Page pièce (la profondeur) (v1-offline)

> Doc-pont psychologie → app. Périmètre **v1-offline**. Overview : [`../README.md`](../README.md).
> C'est la **profondeur** ouverte par le reveal ([`02-reveal`](./02-reveal.md)).

## 1. Rôle

> Là où l'histoire **complète** vit. La page transforme un jeton en **fenêtre sur un bout d'Europe**.
> Le reveal était le *pic resserré* ; ici, on **transporte**.

**Drive primaire** : Sens — secondaires : Valeur, Complétion, Statut.

## 2. Leviers psy mobilisés

| Levier | Ce qu'il fait | Source |
|---|---|---|
| **Transportation narrative** | immersion dans une histoire **vraie** → engagement émotionnel, attention focalisée | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Endowment effect** | « **ma** pièce » : la possession augmente la valeur perçue (actif sur cette vue) | [`07`](../../psychologie-documentation/07-sens-storytelling.md) · `01` |
| **IKEA effect (résiduel)** | geste de scan déjà accompli → attachement durable, rappel de l'acte mérité | [`07`](../../psychologie-documentation/07-sens-storytelling.md) |
| **Complétion** (goal-gradient + Zeigarnik) | la série entière visible → « il m'en manque… » + boucle mentale ouverte | [`06`](../../psychologie-documentation/06-completion-double-axe.md) |
| **Valeur** | cote par qualité = info numismate crédible | `01` (sécurité financière) · mission Valorisation |

> Moat de données : la qualité de la transportation repose sur nos données réelles (BCE i18n, Numista rich, LMDLP) — cf. `project_bce_i18n`, `project_coin_richness`.

## 3. Contenu (du général au détail)

1. **Héros 3D** (réutilisé du reveal) + état possédé/qualité.
2. **Le récit** : l'événement célébré, le contexte historique, designers, monument/lieu — la
   **transportation** complète. *(Idée différée : une scène 3D du monument/événement, stylée ou
   générée — à arbitrer, coûteuse, proto d'abord.)*
3. **Cote par qualité** (UNC/TTB/TB) + tendance — en info riche, pas anxiogène.
4. **La série / le set** : planche entière, ce qui manque pointé.
5. **« Où l'acheter »** (si manquante) → **lien affilié** externe (eBay/LMDLP/monnaies) — *première
   monétisation, zéro paiement à gérer* (mission Valorisation/Croissance, déjà OK en offline).
6. **Métadonnées** : tirage (→ rareté objective), diamètre, démonét, lettering…

## 4. Actions × biais

| Action | Levier |
|---|---|
| Lire le récit (déroulé progressif) | transportation |
| Faire tourner le 3D / zoomer | endowment (« mon » objet) |
| Naviguer la série → pièces manquantes | Complétion (goal-gradient + Zeigarnik) |
| Tap « où l'acheter » | valeur + affiliation (revenu) |
| Retirer du coffre (dialog) | contrôle (mais friction de confirmation) |

## 5. Garde-fous

- **Récit authentique only** : la transportation marche *parce que* c'est vrai (pas de lore inventé)
  → cohérent avec « pas de manipulation ».
- **Sens proposé, pas imposé** : un complétionniste peut ignorer le récit (lentille/autonomie).
- **Affiliation honnête** : transparente (« lien partenaire »), jamais déguisée en conseil neutre.
- Cote **non anxiogène** : pas de cours-bourse clignotant.

## 6. Drives servis

Sens ⬤ · Valeur ◑ · Complétion ◑ · Statut ◔ (rareté/tirage).

## 7. À proto'er (R1)

**❌ Bloquant avant Android** : enrichissement de `coin-detail.html` avec le bloc récit (layout déroulé progressif, hiérarchie visuelle transportation) — ce layout n'existe pas dans le socle actuel.

**Différé (arbitrage coût/valeur)** : scène 3D thématique du monument/événement — à proto'er si retenue, avant toute implémentation Android.
