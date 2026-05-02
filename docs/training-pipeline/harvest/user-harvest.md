# User harvest — capter des photos labelées depuis l'app

> Quand le modèle on-device n'identifie pas la pièce de l'user avec
> confiance, on transforme l'échec en opportunité d'apprentissage :
> on aide l'user à pointer la bonne pièce, et on capture
> photo + label pour le training futur.

## Le problème

Pl@ntNet a montré qu'un corpus de photos user-validées est ce qui
ferme vraiment le gap studio→wild à long terme. Mais **avant** que
les users existent en masse, on a un cold-start :

- L'app doit être suffisamment bonne dès le jour 1 pour ne pas
  frustrer.
- Pour devenir suffisamment bonne, il faudrait justement les
  données users.
- Cercle vicieux.

C'est pourquoi le **scraping** (cf. [`sources.md`](./sources.md))
attaque le cold-start. Le user-harvest prend ensuite le relais et
devient la source dominante quand l'app a une base.

## Trois cas à distinguer

Quand l'user scanne une pièce, le modèle on-device produit un top-k
avec scores. On classe le résultat en trois cas :

### Cas A — Modèle on-device confiant

`top1_score > seuil_high` ET `top1 - top2 > marge`.
L'app affiche directement "C'est X, ajouter au coffre ?". Pas de
harvest particulier — la photo et le label peuvent être stockés en
local pour audit, mais ne nécessitent pas de validation humaine
(l'user va corriger explicitement si on s'est trompés).

### Cas B — On-device hésite, fallback cloud résout

`top1_score < seuil_high` ou ambiguïté top1/top2.
L'app appelle le service cloud (notre infra ou tiers). Le cloud
renvoie un top-k plus fiable. **L'app demande confirmation à
l'user** : "On hésite entre X et Y. C'est laquelle ?" L'user tap.
Photo + label capturés avec **confiance haute** (user-validated).

### Cas C — Cloud aussi indécis ou totalement inconnu

L'app entre en **mode aide manuelle**. Plusieurs niveaux de
fallback successifs :

1. **Top-k visuel cloud** : "Voici 6 candidats, c'est laquelle ?"
   Si l'user pointe → photo + label haute confiance.
2. **Filtres rapides** : si l'user ne reconnaît pas dans le top-k,
   on propose des filtres : pays ? valeur (1c, 2€…) ? commémo ou
   standard ? L'user répond, on filtre le catalogue, on présente
   une grille visuelle. L'user pointe.
3. **Recherche libre** : l'user tape un mot-clé ("Kniefall",
   "Allemagne 2020") → recherche dans le catalogue → grille → pointe.
4. **Inconnu total** : l'user dit "je ne sais pas". Photo capturée
   avec label `unknown`, métadonnées (pays détecté ? texte OCR
   visible ?). File de **review admin** (cf.
   [`human-review.md`](./human-review.md)).

## Schéma de capture

Chaque scan donne lieu à un enregistrement local sur le device,
synchronisé vers `ml/state/user_harvest/` (ou table Supabase
dédiée — à arbitrer au moment du câblage) :

```json
{
  "scan_id": "uuid",
  "device_id": "anonymous_hash",
  "scanned_at": "2026-05-02T14:32:00Z",
  "photo_path": "user_harvest/<uuid>.jpg",
  "model_version": "lab/iterations/<iid>/...",
  "topk_on_device": [
    {"eurio_id": "de-2020-2eur-kniefall", "score": 0.42},
    {"eurio_id": "de-2007-2eur-schwerin", "score": 0.38}
  ],
  "fallback_used": "cloud",
  "topk_cloud": [...],
  "user_decision": {
    "kind": "confirmed" | "selected_from_topk" | "filtered" | "search" | "unknown",
    "eurio_id": "de-2020-2eur-kniefall",
    "confidence": "high" | "medium" | "unknown"
  },
  "needs_review": false
}
```

Tous les scans (même cas A succès) sont conservés. L'analytique sur
ce log permet de :

- Identifier les pièces qui font régulièrement échouer le on-device
  (cibler scraping ciblé sur ces pièces).
- Mesurer le taux d'usage du fallback cloud (coût opérationnel).
- Détecter les régressions (un scan auparavant cas A devient cas B
  sur une nouvelle version).

## UX — règles directrices

- **Ne jamais bloquer l'user**. Si on ne sait pas, on aide à
  trouver, on n'affiche pas un mur "désolé inconnu".
- **Toujours présenter quelque chose à choisir**. Une grille de 6
  candidats vaut mieux qu'un input texte vide.
- **Ne pas demander à l'user d'annoter**. On ne fait pas une app
  contributive façon Pl@ntNet. L'user veut identifier sa pièce, pas
  contribuer à un dataset. Le harvest est un effet de bord
  silencieux : "merci, c'est bien Kniefall, ajoutée à ton coffre".
- **Anonymat**. Les photos sont liées à un device_id hashé, pas à
  un compte. L'user peut purger son historique localement.
- **Opt-out clair** : un toggle "aider Eurio à s'améliorer en
  partageant tes scans anonymes" dans les settings. Default ON pour
  l'instant (à valider RGPD).

## Privacy & RGPD

- Les photos sont des photos de **pièces de monnaie**, pas de
  visages. Risque RGPD direct faible.
- Mais : un scan peut accidentellement capturer un environnement
  (table, main, document avec texte). Best practice :
  - Crop automatique sur la pièce (déjà fait pour le matcher) avant
    upload — on n'envoie que le cercle.
  - Pas de géolocalisation captée.
- Documenter clairement la politique dans la page settings.

## Boucle d'apprentissage

Photos collectées ⇒ ingestion lab périodique :

1. Filtrage : ne garder que les scans avec `confidence ∈ {high,
   medium}` ET `user_decision.kind ≠ unknown`.
2. Pré-traitement : crop pièce, redimensionnement, dédup pHash
   contre le training set existant.
3. Auto-validateur (si possible) : passe par DINOv2 vs ancre
   canonique, pour filtrer les cas où l'user a pointé la mauvaise
   pièce dans le top-k cloud.
4. Ingestion dans `ml/datasets/user_harvest/<eurio_id>/*.jpg`.
5. Disponible pour la prochaine itération de cohort.

Cadence : hebdo ou mensuelle selon volume. À industrialiser quand
les premiers users tournent.

## Hors-scope (rappel)

- **Récompense user pour avoir confirmé** (gamification "tu as
  ajouté 10 pièces, badge !"). Levier intéressant mais hors track
  data.
- **Modération communautaire** des photos contribuées. Pour
  l'instant tout passe par l'admin (humain unique = toi).
- **Sync multi-device** du harvest local. Pas pertinent au stade
  v1.
- **Réseau social autour des collectionneurs**. Hors mission de
  l'app.
