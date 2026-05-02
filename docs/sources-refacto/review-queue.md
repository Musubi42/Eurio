# Review queue — vision complète

> Le module de review humaine est l'oxygène de la chaîne d'ingestion :
> sans lui, les rows non-résolues stagnent et la donnée ne sert à rien.
> Cette doc décrit la vision complète. La phase 1 livre une **version
> minimale** (cf. dernière section).

## Pourquoi la review queue est centrale

Le pipeline de résolution `auto_name → auto_dino → auto_phash` ne
résoudra jamais 100 % des cas. Les listings eBay aux titres
fantaisistes ("super piece rare !!! 2 euros"), les lots, les Catawiki
sans pays explicite, les images dont les métadonnées sont fausses —
tout ça atterrit en `needs_review`.

**Sans review queue, ces rows sont du déchet stocké.** Avec une UI
efficace, elles deviennent du training data labellisé à la main, plus
précieux que tout auto-match.

## Principes UX

1. **Vitesse > exhaustivité.** Mieux vaut 200 décisions/jour que
   200 décisions parfaites/semaine.
2. **L'humain ne tape pas, il sélectionne.** Top-5 candidats
   pré-calculés + filtres pays/dénomination → 95 % des cas se
   résolvent en 2 clics.
3. **L'image canonique Numista est toujours visible** côté droit
   pour comparaison.
4. **Raccourcis clavier partout** (1-5 pour candidats, R pour reject,
   N pour next, F pour focus filter…).
5. **Pas de retour arrière forcé** : une décision peut être révisée
   plus tard via la page coin admin standard, on ne bloque pas la
   review queue avec un undo.

## Layout de la page review

```
┌─ Review queue (1247 pending) ──────────────────────────────────────┐
│                                                                     │
│  ┌── Image à résoudre ────────┐   ┌── Candidats top-5 ──────────┐  │
│  │                            │   │ 1. BE-2EUR-2002 (0.87)      │  │
│  │   [crop 224×224]           │   │    [thumb canonique Numista] │  │
│  │                            │   │ 2. BE-2EUR-2008 (0.74)      │  │
│  │   bbox: x=120 y=80         │   │ 3. NL-2EUR-2002 (0.41)      │  │
│  │   source: ebay             │   │ 4. LU-2EUR-2002 (0.39)      │  │
│  │   listing: "2 euros        │   │ 5. FR-2EUR-2002 (0.32)      │  │
│  │     belgique 2002"         │   │                              │  │
│  └────────────────────────────┘   │ [Reject] [None / sélecteur] │  │
│                                   └──────────────────────────────┘  │
│                                                                     │
│  ┌── Sélecteur libre (si rien dans top-5) ────────────────────┐   │
│  │ Pays : [BE ▾]  Dénomination : [2 EUR ▾]  Année : [____]    │   │
│  │                                                              │   │
│  │ Résultats filtrés (12) :                                     │   │
│  │ [thumb] BE-2EUR-2002  [thumb] BE-2EUR-2008  [thumb] BE-…    │   │
│  │ [thumb] BE-2EUR-2010  …                                     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  Face détectée : ●obverse  ○reverse  ○unknown                      │
│  Notes (optionnel) : [____________________________________]         │
│                                                                     │
│  [Skip]  [Reject (R)]            [Validate (Enter)]                │
└─────────────────────────────────────────────────────────────────────┘
```

### Colonne candidats (top-5)

Pré-calculée au moment de l'enqueue par le name-match (voir
`schema.md` `candidate_eurio_ids jsonb`). Chaque candidat affiche :
- ID + score
- Thumb de la canonique Numista (depuis `coins.images.obverse`)
- Hover/click → modal avec image full + détails

### Sélecteur libre (fallback)

Quand le top-5 est complètement à côté (métadonnées listing trop
mauvaises) :
- 3 dropdowns cascade : pays → dénomination → année (optionnelle)
- Résultats = thumbs canoniques Numista filtrés
- Click sur un thumb = sélection comme `decided_eurio_id`

C'est le filet pour les ~10-20 % des cas où l'auto-match est
totalement perdu.

## Priorisation de la queue

`priority` int (plus bas = plus prioritaire). Calcul à l'enqueue :

```
priority =
    100                                    # base
  - 30 if eurio_id_target_known            # le fetch était ciblé, juste à confirmer
  - 20 if commemorative                    # les commémos sont notre cœur
  - 10 if rare_eurio_id                    # commémos rares (< N images en training)
  + 50 if multi_coin_lot                   # plus complexe, deprioriser
  + 20 if quality_score < 0.4              # mauvaise photo, deprio
```

L'objectif : faire remonter en haut les cas faciles + à fort impact
training (commémos rares). Le reviewer voit en premier ce qui
rapporte le plus de signal pour le moins d'effort.

## Volume estimé

Hypothèses (révisable empiriquement) :
- 500 listings eBay/run × 3 images × 12 runs/an = ~18k images/an
- Auto-match name réussit à ~50-70 % → 5-9k pending review/an
- Catawiki (volume comparable) → x2

**Ordre de grandeur : 15-30k reviews/an, soit ~50-100/jour si on
review tous les jours.** Tenable si l'UI est rapide (objectif :
≤ 10s par décision médiane).

## Workflow d'enqueue

1. Fetch source → écrit `source_images` + `image_assets` (crops).
2. Pour chaque crop : tentative `auto_name`.
   - Si confiance ≥ 0.85 → `resolution_status='auto_name'`, pas en queue.
   - Si 0.55 ≤ confiance < 0.85 → `resolution_status='needs_review'`,
     enqueue avec top-5 = candidats du name-match.
   - Si confiance < 0.55 → `resolution_status='needs_review'`,
     enqueue, top-5 = best-effort (parfois vide).
3. *(Futur)* DinoV2 pré-calcule top-5 visuel pour les rows en queue
   sans top-5 ou pour upgrader le top-5 existant. **DinoV2
   n'auto-labellise jamais** — il aide juste l'humain en remplissant
   `candidate_eurio_ids` avec des suggestions visuellement
   pertinentes.
4. Reviewer pioche, décide, valide.
5. Décision écrite : `image_assets.eurio_id`, `resolution_status='manual'`,
   `review_queue.status='done'`.
6. Si `pending_quotes` existe pour ce `source_image_id` ET le listing
   était mono-pièce (`n_crops=1`) → promote vers `coin_market_quotes`.

## Endpoints API attendus

```
GET    /review-queue?status=open&limit=20&order=priority    # liste
GET    /review-queue/:id                                    # détail row + image
POST   /review-queue/:id/decide                             # body: eurio_id, face, variant_kind, notes
POST   /review-queue/:id/skip                               # repousser à plus tard (priority +50)
POST   /review-queue/:id/reject                             # image inutilisable

GET    /review-queue/stats                                  # n_pending, n_done_today, vélocité
GET    /coins/search?country=BE&denomination=2&year=        # sélecteur libre
```

## Évolutions futures (hors phase 1)

- **Batch labeling** : sélection multiple → tag commun (utile pour
  les listings d'un même vendeur ou les pHash-clusters).
- **Suggestions de pHash-cluster** : "vous avez résolu cette image
  vers BE-2EUR-2002 ; voici 12 autres images avec le même pHash,
  voulez-vous propager ?".
- **Active learning** : prioriser les rows dont la décision
  apporterait le plus d'info à DinoV2 (cf. uncertainty sampling).
- **Mobile-friendly** : review en swipe sur téléphone pendant les
  transports.
- **Multi-reviewer** : `assigned_to` pris en compte, reviewers
  multiples, conflits → re-queue avec `priority` ↓.
- **Audit & révision** : historique complet des décisions, possibilité
  de revisiter un cluster d'erreurs (ex: "j'ai mal labellisé toutes
  les Albert II 2008 en 2002 cette semaine").

## Version minimale livrée en phase 1

Périmètre minimum pour ne pas bloquer la chaîne :

- Table `review_queue` au schéma complet.
- Endpoints `GET /review-queue` (list + filtres status/priority),
  `GET /review-queue/:id`, `POST /review-queue/:id/decide`,
  `POST /review-queue/:id/reject`.
- Page Vue `/review` avec :
  - liste paginée triée par `priority`
  - vue détail : image crop + top-5 candidats (thumbs canoniques) +
    bouton Validate / Reject
  - sélecteur libre minimal (pays + dénomination dropdowns, sans
    cascade fancy)
  - raccourcis clavier 1-5 + Enter + R
- Pas de stats, pas de filtres avancés, pas de batch, pas de
  active learning, pas de skip retardé : c'est la **V0 utilisable**.

Tout le reste (UX évoluée, mobile, batch, active learning) est
développé dans une refacto suivante, indépendante.
