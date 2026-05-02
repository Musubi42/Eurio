# Harvest pipeline — élargir le corpus de photos réelles

> Statut : **planification, aucun code livré.** Document écrit
> 2026-05-02 après le constat tiré de la cohort `mix-zone-7-cls`
> (test-2, R@1 strict 57% live) : **une seule photo studio Numista
> + augmentation synthétique ne suffit pas** à entraîner un embedder
> qui tient face aux photos in-the-wild.

## Pourquoi ce track existe

L'app Eurio doit reconnaître des pièces euro à partir de scans
utilisateur (lumière variable, angle approximatif, usure, doigts dans
le cadre). Le pipeline actuel entraîne un ArcFace from-scratch sur :

- **1 photo canonique Numista** par pièce (qualité studio, propre)
- **N variantes augmentées** (perspective, relighting, overlays patine)

Test-2 a confirmé empiriquement ce que la littérature laisse entendre
(cf. brainstorm meta du 2026-05-02) : le gap studio→wild ne se ferme
pas par augmentation seule. Les apps qui marchent en prod
(Pl@ntNet, Numista search, Coinoscope) s'appuient sur un **corpus de
photos réelles** plus ou moins curé. On ne possède pas physiquement
les pièces, donc on doit aller chercher ces photos ailleurs.

## Trois sources de photos réelles à exploiter

| Source | Description | Confiance label | Volume potentiel |
|---|---|---|---|
| **Scraping web** | eBay, maisons de vente, Wikimedia, Colnect, Numista user-uploads… | Variable, à valider | Élevé (centaines/coin sur les communes) |
| **Fallback cloud** | Quand le modèle on-device hésite, l'app interroge un service cloud (notre infra ou tiers). Si l'user confirme, photo + label capturés. | Haute (user-validated) | Croissant avec les users |
| **User scans in-app** | Quand le scan échoue côté on-device et côté cloud, on aide l'user à pointer la bonne pièce dans le catalogue (cf. [`user-harvest.md`](./user-harvest.md)). | Haute (user-validated) | Croissant |

Les trois sont complémentaires. Le scraping débloque le cold-start
(pas d'users → pas de données users), le user-harvest prend le relais
quand l'app a une base d'utilisateurs.

## Le rôle pivot de DINOv2 (ou équivalent foundation)

Le track **DINOv2 backbone swap** (cf. brainstorm meta) et ce track
harvest partagent une dépendance : **un foundation embedder
généraliste capable de matcher photo wild ↔ photo canonique**.

- Côté **modèle on-device** : DINOv2 sert de backbone, fine-tuné avec
  une tête ArcFace sur nos données.
- Côté **harvest** : le même DINOv2 sert de **verifier** —
  étant donné une photo scrapée et la photo canonique Numista de la
  pièce visée, est-ce qu'on confirme que c'est bien la même pièce ?
  (cf. [`auto-validator.md`](./auto-validator.md))

Conséquence : le premier investissement code utile est de **câbler
DINOv2 en lab** (Python `ml/`, pas Android). Ça débloque les deux
tracks en parallèle.

## Lien avec les autres refactos

| Doc | Relation |
|---|---|
| [`lab-prod-refacto/`](../../lab-prod-refacto/) | Prérequis. Sans isolation par `iteration_id` (phase 2), un track DINOv2 / harvest expérimental polluerait la prod. |
| [`refacto/`](../refacto/) (UX lab) | Orthogonal. Les tiroirs cohort/iteration affichent les nouvelles itérations sans modification. |
| [`journal/`](../journal/) | Continue à tracker chaque itération, y compris les premières "DINOv2 + harvest" dès qu'elles tournent. |

## Phases

| # | Titre | Périmètre | Bloque la suite ? | Statut |
|---|---|---|---|---|
| 1 | [DINOv2 en lab](./phase-1-dinov2-bring-up.md) | Câbler DINOv2 (or alt) en Python, embedder utilitaire, premier bench sur cohort existante | Oui — verifier et backbone en dépendent | 🔲 |
| 2 | [Auto-validateur sur eBay (commémo only)](./auto-validator.md) | Pipeline texte+image, seuils calibrés, review queue minimale | Non, mais débloque le scraping massif | 🔲 |
| 3 | [Sources étendues](./sources.md) | Catawiki, Colnect, Wikimedia, Numista user-uploads | Non | 🔲 |
| 4 | [User harvest in-app](./user-harvest.md) | Flow cold-start côté Android, capture photo+label, ingestion lab | Non, dépend du nouvel on-device shippé | 🔲 |
| 5 | [Review humaine admin](./human-review.md) | UI batch dans `admin/web`, raccourcis clavier, exports | Non, support des phases 2+4 | 🔲 |

> Phase 1 est **bloquante** pour le track DINOv2 ET pour le
> verifier. C'est l'investissement le plus rentable à court terme.

## Hors-scope explicite

- **Choix définitif du foundation model** (DINOv2 vs SigLIP vs CLIP
  vs autres). À trancher en phase 1 selon perf mesurée sur notre
  cohort existante. Le doc parle de "DINOv2" par raccourci.
- **Achat de pièces physiques** pour shooter nos propres photos
  studio multi-angle. Levier valide mais hors de ce track.
- **Distillation du foundation model en mobile-friendly** pour
  embarquer DINOv2 directement sur Android. C'est un sous-projet du
  track on-device, pas du harvest.
- **Marketplace / API payante** (CoinArchives, Numista API search).
  Listées en référence dans [`sources.md`](./sources.md) mais pas
  attaquées en premier.

## Workflow agent

Un agent qui démarre une phase doit :

1. Lire ce README en entier.
2. Lire la phase qu'il implémente.
3. Lire le doc connexe (`auto-validator.md`, `sources.md`, etc.) si
   la phase y touche.
4. Valider avec l'utilisateur que la cohort/dataset cible est OK
   avant de toucher aux artefacts.
5. À la fin de la session, append une entrée datée dans
   `progress.md` (à créer si absent) ou dans le journal d'itération
   correspondant.
