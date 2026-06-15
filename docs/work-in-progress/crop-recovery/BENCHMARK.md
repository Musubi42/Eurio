# BENCHMARK — banc partagé crop-recovery (le contrat de comparabilité)

> **Linchpin du chantier.** Les deux stratégies (A, B) et tout hybride sont jugés **ici**,
> sur les **mêmes données**, avec les **mêmes métriques**, via la **même interface**. Si une
> session mesure autrement, les résultats ne sont pas comparables (= l'erreur qu'on veut
> éviter). **Chunk 0 = construire ce banc EN PREMIER.**

## 1. Composants gelés (oracle)

- **Probe fragment** (`vision.census.face_scores`) = **GELÉE**. C'est l'oracle « pièce
  entière ? ». Prouvée saine sur EMU/globe (crops validés-main → 0,87). On ne la touche pas.
- **Encodeur DINO** vits14, **τ = 0,55**. Figés pour tout le chantier.

## 2. Interface commune (le seul code que A/B écrivent)

```python
# ml/bench/crop_recovery_iface.py  (fourni par le banc)
@dataclass
class Candidate:
    cx: float; cy: float; r: float
    source: str          # "A:score_search" | "B:bimetal_rim" | "baseline" ...
    debug: dict | None = None

def recrop(raw_bgr: np.ndarray, hint: dict) -> list[Candidate]:
    """hint = {cx, cy, r_final, r_bbox} de la détection prod (detect_circles_multi).
    Retourne >=1 candidat(s) de cercle pièce-entière (coords natives).
    Le banc se charge de cropper, scorer (probe gelée), mesurer, logger."""
```

Retourner **plusieurs** candidats est encouragé (le banc les score tous → permet
l'évaluation hybride offline). Le **baseline** = `[Candidate(hint.cx,hint.cy,hint.r_final,
"baseline")]` (le crop prod actuel), toujours loggé pour le « lift ».

## 3. Les trois jeux de données (fixes, construits une fois → `ml/state/crop_recovery/`)

### D1 — Gold géométrie (vérité terrain du BON cercle)
- Source : `image_assets` `resolution_status='manual'` AND `face='obverse'` AND
  `detection_method LIKE 'manual%'` → **crops recroppés à la main** (~458, EMU/globe inclus).
- Pour chaque : le **raw** (via `source_images.storage_path`, bucket `enrichment-raws`) +
  le **cercle humain** reconstruit depuis `image_assets.bbox_json` (le rectangle main →
  cercle inscrit). C'est la vérité terrain du **bon crop**.
- **Métrique (indépendante de la probe)** : par cas, `IoU(cercle_strat, cercle_humain)`,
  `|Δr|/r_humain`, `Δcentre/r_humain`. Agrégat : **IoU médian**, % cas IoU ≥ 0,8.

### D2 — Récupération (l'impact réel)
- Source : les **341 zero_crops** du run `fa8a9af939ce43e6a3eee6842ecae170`
  (`crop_status='zero_crops'`). Sous-ensemble étiqueté **EMU/globe** (par `target_eurio_id`)
  = la cible principale ; garder aussi un slice « autres » pour la généralité.
- **Métrique** : % de cas dont le **meilleur candidat passe la probe gelée** (score ≥ τ) ;
  **score médian du meilleur candidat** ; **lift vs baseline** (baseline ≈ 0%).

### D3 — Non-régression (ne rien casser)
- **D3a `success`** : crops qui ont **passé le gate** (image_assets non rejetés des
  `success` du run). Le hint est **la géométrie réelle du crop accepté** (`bbox_json`), pas
  une re-détection → baseline ≈ 100%, donc « ne pas casser » est un test honnête. Après
  recrop, doivent **rester acceptés**. Métrique : **% rétention**.
- **D3b fragments** : vrais fragments (tags « fragment » de `/fragment-audit` +
  sous-crops synthétiques tranche/anneau). Doivent **rester rejetés**. Métrique : **%
  toujours coupés** (pas de nouveaux faux-accepts induits par un crop plus large).
- **D3c géométrie device** : crops gold du `crop-bench` / cohortes device — l'IoU ne doit
  pas régresser (garde la parité scan).

## 4. Schéma de sortie (UN JSON par run de stratégie) → alimente front + hybride

```json
{ "strategy": "A", "run": "fa8a9af9...", "tau": 0.55,
  "cases": [
    { "case_id": "...", "dataset": "D2", "raw_ref": "enrichment-raws/...",
      "target_eurio_id": "at-2012-...", "gold_circle": {"cx":..,"cy":..,"r":..} | null,
      "candidates": [ {"cx":..,"cy":..,"r":..,"source":"A:...","score":0.71,"iou_gold":0.86} ],
      "baseline_score": 0.04, "chosen_idx": 0, "passed": true } ] }
```

## 5. Évaluation hybride (le « meilleur des deux », **sans re-run**)

Comme chaque cas logge **tous** les candidats de A **et** de B avec leur score, un
évaluateur post-hoc calcule n'importe quelle **politique** sur l'union des candidats :
- `A_only`, `B_only` ;
- `argmax_score` (garde le candidat — A ou B — au score max ≥ τ) ;
- `B_prior_then_A` (B propose la géométrie, A valide/raffine par score) ;
- `vote`, etc.
On choisit la politique qui **maximise D2** sous **contraintes D3** et **bon D1**.

## 6. Critères de succès — PRÉ-ENREGISTRÉS ✅ VALIDÉS PO (2026-06-15)

> Figés **avant** de coder les stratégies. Ne pas les bouger en cours de route.

- **Primaire** : récupération **D2 (EMU/globe) ≥ 70%** des zero_crops passent la probe gelée
  (τ=0,55) après recrop (baseline ≈ 0%).
- **Gardes (sinon disqualifié)** :
  - D3a **rétention `success` ≥ 98%** (ne pas casser ce qui marche) ;
  - D3b **faux-accept fragments ≤ 2%** (un crop plus large ne doit pas faire passer un
    fragment ; baseline mesurée comme référence) ;
  - D1 **IoU médian ≥ 0,80** vs cercle humain (le crop est géométriquement juste).
- **Départage A vs B** (à récupération comparable) : (1) **coût** (B cheap, A = K×DINO) ;
  (2) **applicabilité on-device** (B oui, A non) ; (3) robustesse hors EMU/globe (slice
  « autres » de D2).
- **Hybride** retenu s'il **domine** les deux sur D2 sans violer une garde.

## 6bis. Repères de référence (mesurés 2026-06-15, jeux réels)

Le plancher que A et B doivent battre. Jeux : D1=458 (9 EMU/globe), D2=305 (tous EMU/globe),
D3a=337 (crops gate-passés), D3b=80.

| stratégie | D1 IoU médian | D2 récup EMU/globe | D3a rétention | D3b faux-accept |
|---|---|---|---|---|
| **baseline** (crop prod) | 0,29 | **0%** | 100% | 0% |
| **ref:radius_sweep** (A naïf) | 0,55 | **43%** | 100% | 1% |
| **cible** | **≥0,80** | **≥70%** | ≥98% | ≤2% |

Lectures clés : (1) le crop prod est loin du gold (IoU 0,29) même hors EMU/globe → undercrop
large (D1 = cas que l'humain a dû recropper, donc enrichi en échecs auto) ; (2) un sweep
**naïf** récupère déjà 43% — A doit monter à 70% par le calage (recentrage, granularité) ;
(3) B vise surtout l'**IoU D1** (match géométrique), là où le sweep plafonne à 0,55.

## 7. Où vit le code

- Banc partagé : `ml/bench/crop_recovery/` (datasets builders + harness + iface + métriques).
- Front : page `/crop-recovery` (admin web) chargeant les JSON `ml/state/crop_recovery/*.json`.
- Stratégie A : un module `recrop()` importé par le harness (flag/registre).
- Stratégie B : idem. **Aucune des deux ne duplique la mesure.**
