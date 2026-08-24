# User harvest — identification manuelle in-app + opt-in collecte

> Canal d'acquisition A (cf. `README.md`). **Pas encore implémenté** — gated sur l'app Android.
> Réécrit 2026-06-07 avec la vision PO. Statut : spec, à proto'er d'abord (R1).

## Idée

L'utilisateur est la meilleure source de **labels sûrs en condition réelle**. Deux mécanismes
complémentaires, tous deux **opt-in** :

1. **Identification manuelle** quand le scan échoue → produit `(photo, eurio_id confirmé)`.
2. **Collecte opt-in** des photos de scan (même réussies) → enrichit le corpus avec l'accord explicite.

## A. Identification manuelle (scan échoué / incertain)

### Déclencheur
Le scan ne retourne pas de pièce avec assez de confiance (sous le seuil), ou l'utilisateur dit
« ce n'est pas la bonne pièce ».

### UX cible (à proto'er dans `admin/packages/proto/`)
On connaît **toutes les pièces 2 € de la zone euro** (référentiel `coins` en base, packagé dans l'APK
via le snapshot catalogue). Donc on peut offrir une **sélection manuelle agréable** :

- Entrée par **pays** (drapeaux) → **année** → vignettes des commémoratives, avec l'image canonique.
- Ou **recherche** texte (thème, personnage, « Erasmus », « Rome 2007 »…) via les alias i18n déjà en base.
- Interaction soignée (pas une liste austère) : grille de vignettes, filtre rapide, preview.
- Confirmation en 1-2 taps → la pièce est ajoutée au coffre **et** le couple est marqué pour le training.

### Donnée produite
`(photo utilisateur capturée, eurio_id choisi par l'humain, conditions=wild)` → **label d'or**.
Chemin de données : photo → (si opt-in) upload → table/queue de candidats training → review légère →
intègre le dataset (`image_assets` ou équivalent user-sourced, à trancher).

## B. Opt-in collecte des photos de scan (Settings)

### Principe
Une **option dans les Settings de l'app** : « Aider à améliorer le scan — autoriser Eurio à utiliser
mes photos de pièces pour entraîner les modèles ». **Désactivée par défaut.** RGPD-friendly.

### Comportement
- **OFF (défaut)** : aucune photo ne quitte l'appareil pour le training.
- **ON** : les photos de scan (réussi ou via identification manuelle) sont **éligibles** à la collecte
  (upload différé en Wi-Fi, anonymisé, sans métadonnée perso). L'utilisateur peut révoquer à tout moment.

### À trancher
- Granularité : opt-in global, ou par-scan (« partager cette photo ? ») ?
- Quoi upload : la photo brute, le crop normalisé, ou les deux ?
- Stockage : bucket dédié `user-harvest` (séparé de `enrichment-*`), provenance tracée (`source='user'`).
- Confiance : une photo user-confirmée vaut-elle autant qu'un canonical ? (trust model — provenance).

## Dépendances
- **App Android shippée** avec le flux scan + coffre (phases `app-implem-phases/`).
- **Proto-first** : scènes proto pour (1) l'écran d'identification manuelle, (2) le toggle settings opt-in.
- Backend : endpoint d'ingestion user-harvest + intégration au pipeline training (provenance `user`).

## Pourquoi c'est fort
Chaque photo user-confirmée est **gratuite, en condition réelle, et parfaitement labellisée** — exactement
ce qui ferme le gap studio→wild que le scrap eBay attaque déjà par le volume. Les deux canaux se cumulent.
