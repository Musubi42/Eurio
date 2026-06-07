# Review humaine — UI admin pour arbitrer les cas ambigus

> L'auto-validateur classe les photos en trois buckets :
> auto-accept, review queue, reject. La **review queue** est l'endroit
> où un humain (toi) tranche en quelques secondes par photo.
>
> Pour que ça scale, l'UI doit être **rythmée au clavier**, pas à la
> souris.

## Pourquoi une UI dédiée

À court terme on pourrait reviewer dans le filesystem (deux dossiers
"accept/reject" et un mv). Mais dès qu'on dépasse 100 photos/semaine,
ça devient pénible et sans audit. Une UI minimale dans `admin/web`
résout ça pour un coût d'implémentation réduit.

L'objectif :

- 1 photo affichée à la fois, plein écran sur un côté
- La photo canonique Numista du label proposé sur l'autre côté
- Score image + score texte affichés
- Raccourcis clavier : `J` accept, `K` reject, `L` "needs more info"
- Compteur de progression dans la session
- Latence cible : 2-5 secondes par photo

## Sources d'entrée de la queue

Trois flux alimentent la même review queue :

1. **Scraping** — photos en bucket "review" depuis l'auto-validateur
   (cf. [`auto-validator.md`](./auto-validator.md)).
2. **User harvest** — scans avec `confidence = unknown` ou flagués
   par l'auto-validateur a posteriori (cf.
   [`user-harvest.md`](./user-harvest.md)).
3. **Spot-check** — échantillons aléatoires d'auto-accept pour
   mesurer la précision (cf. métriques validateur).

Chaque entrée a un `review_id`, une photo, un label proposé, des
scores, et la source d'origine.

## Modèle de données (proposition)

Table SQLite dans `ml/state/training.db` :

```sql
CREATE TABLE harvest_review (
  review_id        TEXT PRIMARY KEY,
  source           TEXT NOT NULL,        -- 'ebay' | 'user_scan' | 'spot_check' | ...
  source_url       TEXT,                  -- listing URL ou device_id
  photo_path       TEXT NOT NULL,         -- relatif à ml/datasets/_review/
  proposed_eurio_id TEXT NOT NULL,
  text_label       TEXT,                  -- output du parser texte
  image_top1       TEXT,                  -- label image top-1
  image_score      REAL,
  image_spread     REAL,
  candidate_topk   TEXT,                  -- JSON [{eurio_id, score}, ...]
  status           TEXT NOT NULL,         -- 'pending' | 'accepted' | 'rejected' | 'needs_info'
  decision_at      TEXT,
  decision_by      TEXT,                  -- email reviewer
  decision_reason  TEXT,                  -- enum ou texte libre
  created_at       TEXT NOT NULL
);
```

À la décision `accepted`, la photo migre vers
`ml/datasets/<source>/<eurio_id>/<photo>.jpg` et est référencée pour
la prochaine cohort.

## UI admin — wireframe

Dans `admin/packages/web/src/features/lab/`, nouveau module
`harvest-review/` :

```
┌──────────────────────────────────────────────────────────┐
│  Review queue · 247 pending · session: 12 reviewed (3 min)│
├────────────────────────────┬─────────────────────────────┤
│                            │                             │
│   [photo candidate]        │   [photo canonique Numista] │
│                            │                             │
│                            │                             │
│   eBay listing #42xxx      │   de-2020-2eur-kniefall     │
│   Title: "2 EURO ALL...    │   2€ Kniefall 50 ans        │
│   Image score: 0.78        │                             │
│   Text label: kniefall     │                             │
│   Spread: 0.04             │                             │
│                            │                             │
├────────────────────────────┴─────────────────────────────┤
│ [J] accept    [K] reject    [L] more info    [→] skip    │
│ [1-9] pick alt from top-k   [/] search catalog           │
└──────────────────────────────────────────────────────────┘
```

Raccourcis :

- `J` → accept (ajoute au training set, suivante)
- `K` → reject (jette, suivante)
- `L` → needs info (laisse en queue avec flag)
- `→` ou `Space` → skip (on revient plus tard)
- `1-9` → pick un candidat alternatif dans le top-k (la photo va
  vers cet eurio_id)
- `/` → ouvrir un mini-search catalog (si vraie classe pas dans le
  top-k)
- `?` → afficher l'aide

Pas de bouton submit, pas de modal de confirmation. Tout est instant
+ undo (`U` dernier choix) si erreur.

## Stratégies pour réduire le volume à reviewer

Le volume de la review queue est le **goulot d'étranglement** du
harvest. Plusieurs leviers :

1. **Calibration agressive de τ_high** (cf. auto-validator). Si on
   est trop conservateur, tout finit en review. Cible : 80%+
   auto-accept sur les commémoratives.
2. **Batch review par classe**. Au lieu d'enchaîner photos
   aléatoires, grouper "30 candidats Kniefall" en série — l'œil se
   cale sur la canonique, décisions plus rapides.
3. **Pré-tri par score**. Les `review` à score > 0.80 sont
   probablement des accept (review rapide). Les < 0.75 sont
   probablement des reject. Trier ascendant ou descendant selon
   l'humeur.
4. **Diff visuel**. Afficher la canonique et la candidate côte à
   côte avec un toggle "swap" pour comparer quickly. Avoir une
   grille des autres candidats du top-k en bas.
5. **Auto-skip si l'humain n'est pas sûr en 5s**. Bouton `L` (needs
   info), on revient quand on a + de contexte.

## Métriques humaines à tracker

- Photos reviewed / heure
- Taux accept / reject / needs-info
- Désaccord entre reviewers (si plusieurs personnes)
- Temps moyen par photo (alarme si > 10s = UI à améliorer)
- Taux de "alt picked from top-k" (si > 5%, suggère que le
  validateur propose mal le label)

Tableau de bord dans la même page admin.

## Hors-scope (v1)

- **Multi-reviewer avec consensus**. Tant que l'admin = 1 personne,
  inutile.
- **Active learning** (le système choisit quelles photos prioriser
  pour maximiser le gain modèle). Levier intéressant phase 6+, après
  qu'on ait un volume stable.
- **Annotation fine** (état de conservation, mint mark). Le harvest
  vise juste à confirmer le `eurio_id`.
- **Mobile-friendly review**. Le pattern clavier suppose desktop.

## Lien avec les autres tracks

- L'auto-validateur écrit dans cette table. Les seuils du validateur
  sont **réglés par observation des décisions humaines**.
- Le user-harvest écrit ici aussi pour les cas `confidence = unknown`
  ou détectés comme suspects après-coup.
- Une fois `accepted`, la photo entre dans le training set et sera
  utilisée par les prochaines cohorts via le mécanisme normal de
  `prepare_dataset.py` (qui devra savoir lire `ml/datasets/<source>/`
  comme source additionnelle aux datasets existants — câblage à
  faire en phase 2).
