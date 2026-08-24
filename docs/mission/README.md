# Missions Eurio

> Couche **stratégique** du projet : le « quoi » et le « pourquoi », au-dessus des
> docs d'implémentation. Chaque mission est un lot cohérent qui livre de la valeur.
> Les docs détail (`roadmap.md`, `app-implem-phases/`, `features/`, `sources/`…)
> restent la couche d'exécution — les missions les **référencent**, ne les dupliquent pas.

**La stratégie produit (vision, North Star, paliers, monétisation, growth) vit dans
[`product-strategy.md`](./product-strategy.md).** Ce README n'est que l'index.

## Principe de travail

- **Dépendances souples.** Une mission peut en attendre une autre « idéalement »,
  mais rien n'est un mur : on avance sur l'envie et l'opportunité. Les seules vraies
  contraintes sont notées explicitement (ex. le bench scan a besoin des captures).
- **Chaque palier livre de la valeur seul.** Si on s'arrête avant la marketplace
  (North Star), une belle app de collection aboutie est déjà une réussite.
- **Pas de dette (R0), proto-first pour l'app (R1)** — cf. `CLAUDE.md`.

## Index des missions

| Mission | Objectif | Statut | Dépendances souples |
|---|---|---|---|
| [Scan](./scan.md) | Scan on-device fiable qui identifie une commémo 2€ | 🔄 bloqué sur les 340 captures | captures → ablation crop → train |
| [App](./app.md) | La boucle scan→coffre→sets→carte eurozone→profil | 🔄 en cours | avance en parallèle du scan |
| [Valorisation](./valorisation.md) | « ta collection vaut X », cote par qualité, « il te manque Y → acheter ici » | 🟢 données prêtes | un minimum d'app |
| [Croissance](./croissance.md) | Faire grossir l'audience + activer les paliers de revenu | 🔲 à lancer | contenu dès que l'app montre qqch |
| [Marketplace](./marketplace.md) | **North Star** : acheter/vendre/troquer in-app, à la commission | 🔭 étoile polaire | liquidité construite par les paliers d'avant |

## Fondation (acquise — socle de tout)

Le **référentiel** est solide et n'est pas une mission forward : catalogue quasi-complet
des commémo 2€, couverture officielle au bleeding-edge (JO/BCE + matrice nl.wikipedia),
multi-source avec provenance tracée, **prix par qualité** (LMDLP + eBay), i18n.
Détail : `docs/sources/`, `docs/referential-bce/`, `docs/data-harmonization/`,
memories `project_data_referential` / `project_trust_model_referential` / `project_eurlex_source`.

## Liens

- Trajectoire ML/scan : [`../work-in-progress/`](../work-in-progress/README.md) (chantiers vivants) et [`../architecture/parcours.md`](../architecture/parcours.md) (par geste). Le tracker J0→J7 a été supprimé le 2026-08-24.
- Phases app Android : [`../app-implem-phases/`](../app-implem-phases/) — détail de la mission App.
- Vision reconnaissance (scrape/augmentation/model) : [`../features/`](../archive/features/).
