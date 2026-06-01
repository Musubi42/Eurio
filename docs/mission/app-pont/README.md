# Doc-pont psychologie → app (blueprint « lab »)

> **Ce que c'est** : l'app Eurio **dérivée purement de la recherche psycho** (`../psychologie-*`
> + recherches `01-08`), **sans se contraindre à l'app/proto existants**. C'est volontaire : on a
> voulu pousser le raisonnement psychologie-first à fond, *puis* merger avec l'existant.
>
> ⚠️ **Le merge** avec [`../../app-implem-phases/`](../../app-implem-phases/) (14 décisions UX, proto
> HTML, portage Compose en cours) est une **étape séparée et ultérieure**. Ici, on ne regarde pas
> « ce que fait le proto » — on décrit **ce que la psycho nous dit de faire**.
>
> **R1 rappel** : tout rendu visuel nouveau ira au **proto HTML** avant Compose. Ces docs fixent
> *l'intention et les liens psy*, pas le pixel.

## Principe directeur

Tout découle de la **vision** ([`../psychologie-consolidation.md`](../psychologie-consolidation.md)) :

> **Parce qu'Eurio est *réel*, on offre le frisson du « pull » sans aucun des poisons.**

Et des **10 règles émergentes** (consolidation §5) — résumé opérationnel :
acte rare vs rituel renouvelable · asymétrie positive · pull éthique (zéro hasard) · défaut
excellent + lentille optionnelle · stratifier sans surcharger · économie des célébrations · filtre
SDT · local > global + N-effect · notif = cadeau · l'éthique EST le positionnement.

## La boucle produit (lab)

```
                          ┌─────────────────────────────────────────┐
                          │              RITUEL RENOUVELABLE          │
                          │   (toujours possible, jamais supply-gated)│
   Onboarding ─▶ SCAN ──▶ │  Coffre · Défis · pièce du jour · cote    │ ──▶ Profil (identité)
   (la 1ʳᵉ        │ (acte  │  ▲                                        │       grade/badges
    capture       │ rare)  └──┼────────────────────────────────────────┘
    magique)      │           │
                  ▼           │  notifs = ré-engagement (cadeau, fréquence adaptative)
        Transition 3D ─▶ Reveal ─▶ (tap) Page pièce (la profondeur)
        + juice              + lentilles
```

- **Acte rare** = scanner une pièce neuve (supply-gated). On le rend **inoubliable** (juice), pas
  obligatoire.
- **Rituel renouvelable** = ce qu'on peut faire **tous les jours sans pièce neuve** (consulter le
  coffre, avancer un défi, lire la pièce du jour, voir la cote). C'est là que vit la rétention.

## Inventaire des vues

### v1-offline (sans compte — le cœur)

| # | Vue | Rôle | Drive primaire | Doc |
|---|---|---|---|---|
| 0 | **Onboarding** | la 1ʳᵉ capture magique + question-lentille | Découverte | [`v1-offline/00-onboarding.md`](./v1-offline/00-onboarding.md) 🟢 |
| 1 | **Scan** (l'acte) | l'acte central + transition 3D | Découverte | [`v1-offline/01-scan.md`](./v1-offline/01-scan.md) 🟢 |
| 2 | **Reveal** | le pull éthique (lentilles, accent, célébrations) | Découverte/Statut | [`v1-offline/02-reveal.md`](./v1-offline/02-reveal.md) 🟢 |
| 3 | **Page pièce** | la profondeur (transportation narrative) | Sens | [`v1-offline/03-page-piece.md`](./v1-offline/03-page-piece.md) 🟢 |
| 4 | **Coffre** (parent) | la collection — 3 sous-vues | Complétion | [`v1-offline/04-coffre.md`](./v1-offline/04-coffre.md) 🟢 |
| 4a | **— Mes pièces** | « ce que j'ai chassé » (endowment/contrôle) | Endowment | [`v1-offline/04a-coffre-mes-pieces.md`](./v1-offline/04a-coffre-mes-pieces.md) 🟢 |
| 4b | **— Sets** | complétion structurée (goal-gradient) | Complétion | [`v1-offline/04b-coffre-sets.md`](./v1-offline/04b-coffre-sets.md) 🟢 |
| 4c | **— Carte eurozone** | complétion spatiale + carte à gratter | Complétion | [`v1-offline/04c-coffre-carte-eurozone.md`](./v1-offline/04c-coffre-carte-eurozone.md) 🟢 |
| 5 | **Défis adaptatifs** | le pilier rétention (≠ streak) | Complétion/Statut | [`v1-offline/05-defis.md`](./v1-offline/05-defis.md) 🟢 |
| 6 | **Profil** | l'identité long-terme (grade, badges, stats) | Statut/Sens | [`v1-offline/06-profil.md`](./v1-offline/06-profil.md) 🟢 |
| 7 | **Notifications** | ré-engagement (transverse) | dépend | [`v1-offline/07-notifications.md`](./v1-offline/07-notifications.md) 🟢 |

### post-v1-online (compte requis — futur)

| # | Vue | Rôle | Drive primaire | Doc |
|---|---|---|---|---|
| 1 | **Classement** | statut social multi-échelle (N-effect, local dominance) | Statut/Social | [`post-v1-online/01-classement.md`](./post-v1-online/01-classement.md) 🟢 |
| 2 | **Social / Partage / Amis** | la boucle virale (relatedness) | Social | [`post-v1-online/02-social-partage.md`](./post-v1-online/02-social-partage.md) 🟢 |
| 3 | **Marketplace** | acheter/vendre/troquer (+ surface affiliation) | Valeur | [`post-v1-online/03-marketplace.md`](./post-v1-online/03-marketplace.md) 🟢 |

## Gabarit d'une doc-pont par vue

Chaque doc suit la même trame (verbeux assumé) :

1. **Rôle** — à quoi sert la vue, en une phrase, + son drive primaire.
2. **Leviers psy mobilisés** — la liste des biais activés, chacun lié à sa recherche `0X`.
3. **Sous-vues / tables** — si la vue en contient plusieurs (ex. Coffre).
4. **Le flow / les actions × biais** — chaque interaction reliée au levier qu'elle déclenche.
5. **Contenu affiché** — quoi montrer, dans quel ordre (stratification Miller/Hick).
6. **Garde-fous** — anti-dark-pattern + filtre SDT.
7. **Drives servis** — matrice primaire/secondaire.
8. **À proto'er (R1)** — ce qui est neuf/visuel et devra passer par le proto avant code.

## Statut

Overview + **toutes les vues dépliées** (2026-06-01) : v1-offline `00`→`07` (Scan/Reveal séparés,
Coffre éclaté en `04a/b/c`) + post-v1-online `01`→`03`. **Passe de critique** (sous-agents adversariaux,
76 findings validés) + **correction** (74 appliqués, 3 écartés par jugement) faite. Liens vérifiés (0 cassé).
**Merge fait (2026-06-01)** : `app-implem-phases/README.md` révise les décisions streak #6/#8 (→ défis),
et `design/_shared/scene-parity.md` §Refonte psycho liste les écrans à proto'er (handoff session proto).
Questions produit **en suspens** (ne bloquent pas le proto) : critère du grade · emplacement des défis.
