# Harvest — acquérir des images réelles pour entraîner le scan

> **Réécrit 2026-06-07** (vérifié doc↔code). Ce track = **comment on nourrit le dataset
> d'entraînement du scan** au-delà de l'unique photo studio Numista.

## Le constat fondateur (toujours valide)

1 photo canonique Numista + augmentation synthétique **ne ferme pas** le gap studio→wild
(test-2, R@1 strict 57 % live sur `mix-zone-7-cls`). Il faut des **vraies photos variées**
par pièce — lumière changeante, angle approximatif, usure, doigts dans le cadre.

## Ce qui est DÉJÀ construit ✅ (la doc d'origine disait « aucun code livré » — c'était faux)

_Chemins re-vérifiés 2026-06-11 après la refacto ml/ (structure plate par domaine)._

| Brique / canal | État | Code |
|---|---|---|
| Foundation **DINOv2 ViT-S/14** | ✅ | `ml/training/foundation/encoder.py` |
| **Auto-validateur** (image + label proposé → auto-accept / review / reject) | ✅ | `ml/training/foundation/auto_validate.py` + `thresholds.py`, `ml/review/review_lanes.py` |
| **Scrap multi-source** (eBay massif + BCE + LMDLP + JO + pricing) | ✅ | `ml/sources/` (ebay ~80k) |
| Pilotage **par cohorte** (mix-zone-17) | ✅ | `ml/sources/cohort_scope.py` + cockpit lab |
| **Review humaine admin** (queue + lot-review + claude_review) | ✅ | `ml/review/review_queue_routes.py`, `ml/training/foundation/claude_review.py`, admin `features/review/` |

→ **Le scraping web (eBay en tête) est le canal principal et il tourne en prod.** Gros morceau livré.
Le bottleneck restant côté scrap = couverture wild des 510 classes encore peu dotées (cf. `roadmap.md`).

## Canaux d'acquisition à AJOUTER — le vrai reste-à-faire

### A. User self-identification in-app + opt-in collecte — **priorité produit**

Quand le modèle **ne reconnaît pas** la pièce scannée (ou hésite) :

- **UI d'identification manuelle sympa** : on a **toutes les pièces 2 € en base** → l'utilisateur
  choisit lui-même la bonne pièce via un affichage agréable et filtrable (par pays / année / thème,
  vignettes canoniques, recherche). Interaction soignée, pas une liste austère.
- **Donnée d'or produite** : le couple **(photo utilisateur, `eurio_id` confirmé par un humain)** =
  label sûr, en condition réelle. C'est exactement ce qui manque au dataset.
- **Opt-in explicite dans les Settings** : l'utilisateur **autorise** qu'on récupère ses photos de
  scan pour entraîner les modèles et améliorer la précision. **Sans opt-in coché, rien n'est collecté.**

Gated sur l'app Android shippée. **Proto-first** (R1 du CLAUDE.md) : la scène d'identification manuelle
+ l'écran settings opt-in doivent d'abord exister dans le proto `admin/packages/proto/`.
→ Détail UX + flux données : **[`user-harvest.md`](./user-harvest.md)**.

### B. Numista API — fallback image → pièce (à explorer)

Donner une **image** à l'API Numista et récupérer les **données de la pièce**. Double usage :
1. **Fallback in-app au début** : tant que notre modèle n'est pas assez bon, on délègue l'identification
   à Numista pour ne pas frustrer l'utilisateur.
2. **Source de label** : une pièce identifiée par Numista = un label exploitable pour le dataset.

À explorer : **que retourne exactement l'API** (matching visuel ? juste métadonnées par ID ? quotas ?
coût ?). → **[`numista-api-fallback.md`](./numista-api-fallback.md)**.

## Phases d'origine (référence historique)

`phase-1-dinov2-bring-up.md`, `auto-validator.md`, `sources.md`, `human-review.md` décrivent la vision
d'origine (2026-05-02). **L'essentiel est BÂTI** (cf. table « déjà construit »). `user-harvest.md` = le
canal A ci-dessus, mis à jour. Ces docs phase restent pour le « pourquoi » et les seuils détaillés.

## Pourquoi ce track existe (conservé)

L'app doit reconnaître des pièces à partir de scans utilisateur en conditions réelles. Le pipeline
entraîne un embedder (DINOv2 + ArcFace) ; la littérature et test-2 confirment que le gap studio→wild
ne se ferme pas par augmentation synthétique seule. Les apps qui marchent en prod s'appuient sur du
**corpus réel** — d'où ces canaux d'acquisition (scrap, user, Numista).
