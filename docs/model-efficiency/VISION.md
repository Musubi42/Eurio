# Model Efficiency — VISION

> North star et règles du jeu pour faire évoluer le modèle de scan d'Eurio.
> Doc **vivante** : elle est mise à jour à chaque test réel, et nos croyances
> y sont remises en question dès qu'un benchmark les contredit.

## North star

**Reconnaître toutes les pièces 2€ de notre DB** (couverture catalogue
complète), avec un modèle assez **léger et rapide** pour tourner largement —
du haut de gamme jusque, à terme, l'entrée de gamme.

Aujourd'hui on couvre **27 classes fiables** (cf. état ci-dessous). La cible
est **l'intégralité des classes de la DB** (~546 designs 2€ et au-delà à mesure
que le référentiel grossit).

## Règles de travail (non négociables)

1. **Pas d'hypothèse cachée.** Toute supposition est écrite explicitement comme
   une **Hypothèse (à challenger)** dans le chantier concerné, et on **sème un
   benchmark** pour la stress-tester. Le registre global est plus bas.
2. **Benchmark-first.** Avant d'optimiser, on établit une **vérité terrain
   mesurée et persistée** (C0). Chaque session future repart de chiffres.
3. **Test réel dès que possible** → résultat consigné dans la doc → on
   réinterroge la croyance.
4. **Un chiffre non mesuré n'est pas un fait.** Les estimations sont taguées
   `⚠️ estimation` tant qu'un benchmark ne les a pas confirmées.

## Ce qui tourne vraiment — mesuré (2026-08-20)

> Ce bloc a été ajouté le 2026-08-20 parce que le tableau historique juste en
> dessous (2026-06-11) était devenu **trompeur** : il décrit un modèle qui n'est
> pas dans l'APK. Rien n'a été effacé ; le tableau de juin reste plus bas, encadré.

| Où ça tourne | Ce qui tourne | Chiffre, et sa source |
|---|---|---|
| **APK (scan)** | ArcFace **MobileNetV3-small**, 17 classes, embedding 256 | **4,43 Mo** — `shared/model-assets.json` (épinglé 2026-08-15) + `model_meta.json` : `{"mode":"arcface","backbone":"mobilenet_v3_small","num_classes":17,"embedding_dim":256}` ([ADR-008](../adr/008-deux-voies-backbone-gele-et-arcface.md) §Contexte) |
| **Serveur (review)** | Backbone **gelé** `dinov2-vitl14` + banque d'ancres `2eur_all` | **1495 ancres · 671 classes · 124 classes à exemplaires**, build `365dcab2a253` du `2026-08-20T14:27:56+00:00`, bâtie **avec** le plancher `min_exemplars=2` (68 classes ramenées au canonique seul) — ⚠️ *plancher depuis retiré du code, la banque servie le porte encore* — `SELECT COUNT(*), COUNT(DISTINCT class_id), COUNT(DISTINCT CASE WHEN method='fps' THEN class_id END) FROM dino_class_references WHERE anchors_kind='2eur_all'` sur `ml/state/eurio.replica.db` → `1495 \| 671 \| 124` (2026-08-20 17:13 UTC). *Build précédent, sans plancher : `23c637d93b43`, `1533 \| 671 \| 182`.* 12 454 prédictions recalculées contre cette banque, **0 périmée** |
| **Qualité de ce backbone gelé** | sur la tâche **review** | **91,6 % top-1 · 97,9 % top-5 · 97,4 % top-1 bande pays**, gold figé `0ecbb1d70e3c`, 1958 crops, 0 crop non encodé ([BENCH-ENCODEURS.md](../work-in-progress/scan-sans-retrain/BENCH-ENCODEURS.md)) |
| **Qualité sur la tâche scan** | — | **inconnue**. **0 capture versionnée** dans `ml/state/scan_corpus.db` (0 octet) — mais **2 264 images device existent et ne sont pas protégées** (114 `ml/datasets/eval_real_norm` + 2 150 `debug_pull`, aucune sur MinIO ni en sauvegarde), cf. P5, H10 et [`DURABILITE-CORPUS.md`](../work-in-progress/scan-quality/DURABILITE-CORPUS.md) |

⚠️ `arcface-vits14-v1` (le tableau ci-dessous) **n'a jamais atteint l'APK** : il
existe comme checkpoint sur MinIO et rien de plus. Les deux lignes de modèle ont
divergé sans qu'on le voie — c'est le constat qui a ouvert
[ADR-008](../adr/008-deux-voies-backbone-gele-et-arcface.md).

## État historique — mesuré (2026-06-11), ⚠️ PLUS EN SERVICE

> 🔴 **Ne pas lire ce tableau comme l'état de l'APK.** Conservé pour la
> traçabilité de C0/C1/C2 : c'est le modèle sur lequel H1, H2, H4 et H6 ont été
> mesurées. L'état réel est le bloc juste au-dessus.

Modèle de référence : **`arcface-vits14-v1`** (checkpoint sur MinIO
`eurio-db/transfers/arcface_vits14_v1_best_model.pth`).

| Dimension | Valeur | Source |
|---|---|---|
| Type | Embedder métrique (retrieval), pas classifieur | code |
| Backbone | DINOv2 ViT-S/14 + `Linear(384→384)`, 21,7M params | `train_embedder.py` |
| Loss | ArcFace, marge ≈ 28.6°, scale 30, `MPerClassSampler(m=4)` | log run |
| Entrée / sortie | 224×224 RGB (ImageNet norm) / embedding 384-dim | code |
| Données train | 546 classes, 1004 img train / 60 val @224px, ×3 aug | log run |
| Qualité | **Recall@1 = 66.67%, R@3 = 68.33%** sur le val (60 img / 27 classes) | `training_log.json` |
| Centroïdes déployés | **27 val-mean fiables** + 519 ArcFace-W (non re-vérifiés) | `compute_embeddings` |
| Poids fp32 / fp16 | 83.3 MB / **41.8 MB** | export réel |
| Coût calcul | 5.68 GMACs / inférence | export réel |
| Déployé | fp16 + 27 centroïdes fiables, testé sur Pixel 9a (concluant) | smoke test |

> ⚠️ **Le R@1 66.67% est sur 60 images val / 27 classes** — ce n'est PAS un test
> held-out représentatif sur tout le catalogue. La perf réelle « in the wild »
> sur les 546 classes est **inconnue** (→ C0).

## Carte des chantiers

Ordre = dépendances. Statut : 🔲 pas commencé · 🟡 en cours · ✅ fait.

| # | Chantier | Statut | Dépend de |
|---|---|---|---|
| **C0** | [Benchmark & vérité terrain](./C0-benchmark-ground-truth.md) | 🔲 | — |
| **C1** | [Centroïdes fiables](./C1-reliable-centroids.md) | 🔲 | C0 |
| **C2** | [Flywheel données — review eBay](./C2-data-flywheel-ebay-review.md) | 🟡 | C0, C1 |
| **C3** | [Couverture catalogue complète](./C3-full-catalog-coverage.md) | 🔲 | C1, C2 |
| **C4** | [Efficacité — quantization + distillation](./C4-efficiency-quant-distill.md) | 🔲 | C0 |
| **C5** | [Accélération on-device](./C5-on-device-acceleration.md) | 🔲 | C0 |
| **C6** | [Gate d'éval continue](./C6-eval-gate.md) | 🔲 | C0 |
| **C7** | [Scan robuste — cascade (face/authenticité/fusion)](./C7-robust-scan-classification.md) | 🟡 | C0, C1, C2 |

**Deux problèmes posés par écrit le 2026-08-20, sans chantier attitré.** Ils ne
sont dans aucune colonne ci-dessus et rien n'y est implémenté ; ces liens sont
leur seule porte d'entrée :

- [`review-autovalidation/PROBLEME.md`](../work-in-progress/review-autovalidation/PROBLEME.md)
  — **90 % des reviews demandent un geste humain sur le CROP**, pas sur la
  classe. Deux jours ont été investis dans l'attribution de classe (encodeurs,
  banque) ; le temps humain part probablement dans le **recadrage**. ⚠️ Lecture
  non mesurée, appuyée sur une phrase du PO — la mesurer est le geste zéro.
- [`scan-quality/DURABILITE-CORPUS.md`](../work-in-progress/scan-quality/DURABILITE-CORPUS.md)
  — les **2 264 images device** existantes n'ont **aucune réplique** : pas de
  MinIO, pas de sauvegarde, deux dossiers gitignorés. Les protéger doit précéder
  la campagne de capture de P5, pas la suivre.

## Passations de session

- [HANDOFF-C2.md](./HANDOFF-C2.md) — démarrage d'une session dédiée au flywheel
  eBay (C2) : mission bout-en-bout, infra existante cartographiée, décisions à
  prendre, premiers pas. Écrit fin session 1.

## Registre global des hypothèses (à challenger)

Chaque hypothèse vit en détail dans son chantier ; ici c'est l'index pour ne
jamais en perdre une de vue.

| H | Hypothèse | Croyance actuelle | Testée par | Statut |
|---|---|---|---|---|
| H1 | Plus d'images **réelles** par classe ↑ précision **et** ↑ fiabilité des centroïdes | **Confirmée et ISOLÉE le 2026-08-20** par la courbe « références par classe » ([`COURBE-REFERENCES.md`](../work-in-progress/scan-sans-retrain/COURBE-REFERENCES.md)) : à **jeu d'évaluation constant** (held-out, 1100 crops / 72 classes) et **encodeur constant**, seule la taille de la banque varie — `vits14` **53,1 % → 75,5 %** de N=0 à N=10, `vitl14` **76,1 % → 85,7 %**. Le terme « banque » est enfin séparé du terme « jeu d'éval » qui le confondait. **Deux nuances mesurées, à ne pas perdre** : (a) la relation n'est **pas monotone** — la PREMIÈRE référence fait BAISSER la précision (−3,0 pts `vits14`, −3,6 `vitl14`), et en encodeur de production il faut **N=5** pour repasser au-dessus du canonique seul ; (b) **aucun plateau n'a été observé** jusqu'à N=10, le « coude à 8 » de la première rédaction étant un artefact du maillage (8 → 10 gagne encore +1,55 pt, McNemar `z=2,38`, `p≈0,017`). Règle de conduite : **8 crops validés par classe** — 🔴 **mais le corollaire « jamais 1 », transformé en plancher `min_exemplars=2` et appliqué le 2026-08-20, a DÉGRADÉ le held-out de 1,4 pt (`vits14`) et 0,9 pt (`vitl14`), puis a été RETIRÉ le soir même** : le point N=1 de la courbe décrit *toutes* les classes plafonnées à 1, pas 68 classes sur 182, et la mesure restreinte dit qu'un exemplaire unique **aide** sa classe (p=0,048 `vitl14`, p=4,5e-10 `vits14`). Voir le journal des croyances, en tête | C2, scan-sans-retrain | ✅ **mesuré et isolé** sur la tâche **review** — 🔴 **son corollaire par classe est réfuté en régime mixte** — ⚠️ **non mesuré sur la tâche scan** (0 capture versionnée), ⚠️ non mesuré au-delà de N=10 |
| H2 | Les centroïdes ArcFace-W sont peu fiables (vs moyennes d'images) | **Réfutée** : le faible est val-mean, pas W | C1 | ⚠️ train-mean≈W > val-mean (set étroit) |
| H3 | fp16 ≈ sans perte ; int8 dégrade un ViT | Moyenne (typique, pas mesuré ici) | C4 | ❓ non mesuré |
| H4 | Les gains DINOv2 transfèrent à la **classification eBay scrape** | **Réfutée en juin en régime canonical-only** (zero-shot vitl14 62,8 % top-1 / 80,9 % hit@5 vs fine-tuné 28,7 % / 35,1 % ; auto-attribution = texte 75,8 % @ 94,9 %) — **et ce verdict ne survit pas au régime multi-exemplaires** : le même vitl14 gelé rend **91,6 %** top-1 / 97,9 % top-5 sur le gold `0ecbb1d70e3c`. ⚠️ **Ce 91,6 % n'est PAS le successeur du 62,8 %** : autre jeu (1958 crops / 194 classes vs gold BE 94 listings / 9 classes) et autre banque. Le seul couple comparable est le banc d'encodeurs à lui-même : **77,2 % (478 crops, banque canonical-only, juin) → 91,6 % (1958 crops, banque 1533 refs, août)** — même harnais, même métrique, **deux variables déplacées** | C2, scan-sans-retrain | ⚠️ réfutée dans son régime d'origine · **non retestée à régime constant** |
| H5 | La perf fp16 ViT-S est OK sur milieu/haut de gamme | Faible (aucune latence mesurée) | C5 | ❓ non mesuré |
| H6 | Le R@1 val reflète la perf réelle sur tout le catalogue | **Non** (val ≠ réel) | C0 | ⚠️ **réel > val** sur set étroit |
| H7 | DINO sépare avers national vs revers commun 2€ sans retrain | **Confirmée** : 0 % FP sur 562 avers, top-40 minés = 100 % revers | C7 | ✅ mesuré (précision ; rappel wild à élargir) |
| H8 | Un détecteur d'authenticité (vraie pièce vs dessin/3D/carton/réplique) manque | Forte (audit code = 0 détecteur image) | C7 | ❓ non mesuré (gold à construire) |
| H9 | Retourner la question Claude (confirmer top-1 DINO) ↑ rendement refs | Moyenne | C7 | ❓ non mesuré |
| H10 | Un backbone **gelé** + banque de vecteurs égale ou dépasse le fine-tuné **sur la tâche scan** (frames caméra), pas seulement sur la review | Moyenne — vraie sur la review (H1/H4), **jamais testée sur le scan** | corpus de scan ([ADR-008](../adr/008-deux-voies-backbone-gele-et-arcface.md)) | ❓ non mesuré — `scan_corpus.db` à 0 octet, plan de capture livré 19/08. ⚠️ **La matière existe** : 2 264 images device (dont 2 150 vraies frames caméra dans `debug_pull`), ni labellisées ni répliquées ([`DURABILITE-CORPUS.md`](../work-in-progress/scan-quality/DURABILITE-CORPUS.md)) |
| H11 | Les latences PyTorch/CPU **prédisent** le classement des encodeurs en TFLite/NNAPI sur Android | Faible — c'est l'hypothèse qui rendrait ConvNeXt-T rédhibitoire | bench TFLite sur device | ⚠️ mesuré côté Mac seulement : ConvNeXt-T 292,8 ms CPU bs1 vs ViT-S/16 24,5 ms (12×), alors qu'il est le plus rapide en MPS (9,5 ms) |
| H12 | Les gains publics de **DINOv3** en recherche d'instance (+24 % relatif de mAP sur Met, +10,8 pts, arXiv 2508.10104) transfèrent à notre tâche — reconnaître une face nationale de 2 € | **🔴 RÉFUTÉE sur la tâche review** : à taille égale (21,6 M vs 22,1 M), DINOv3 ViT-S/16 fait **78,7 %** top-1 contre **85,9 %** pour DINOv2 ViT-S/14, soit **−7,2 pts** ; ConvNeXt-T (27,8 M) 81,5 %, encore sous le petit DINOv2. McNemar apparié contre `dinov2_vitl14` : vits14 `b=163 c=50 p=3,6e-15`, dinov3 vits16 `b=286 c=32 p=3,8e-52`, dinov3 convnext-t `b=237 c=39 p=9,0e-36` | banc `bench_encoder_dino`, gold `0ecbb1d70e3c`, 1958 crops, 0 non encodé — [BENCH-ENCODEURS.md](../work-in-progress/scan-sans-retrain/BENCH-ENCODEURS.md) | ✅ **mesuré** (tâche **review** ; **backbone gelé sur la banque de la production**, DINOv3 n'a pas eu sa propre banque) |
| H13 | Un encodeur candidat mérite **sa propre banque** avant d'être jugé. Le banc ré-encode bien les images d'ancre avec chaque modèle, mais **le choix** de ces images (farthest-point sampling) a été fait dans l'espace de `dinov2-vitl14` | Moyenne — c'est le seul biais structurel connu du banc, et il joue **contre** les candidats | rebuild de banque par encodeur, bloqué par **Q6** (aucun lecteur de `dino_class_references` n'est scopé par encodeur) | ❓ non mesuré |
| H14 | Le **niveau absolu** rendu par le banc d'encodeurs est la performance qu'on aura sur des crops jamais vus | **🔴 RÉFUTÉ le 2026-08-20** : **858 des 1958 crops du gold SONT des lignes de la banque** — les noter contre elle mesure une similarité de 1,0 avec soi-même. En held-out, `vits14` tombe de 85,9 % à **75,5 %** (−10,4 pts) et `vitl14` de 91,6 % à **85,7 %** (−5,9 pts). Le **classement** n'est pas retourné et le McNemar publié reste valide sur sa propre population, mais **un seuil d'auto-acceptation calibré sur ce régime serait optimiste**. ⚠️ Symétriquement, la population held-out **n'est pas un plancher** : elle est plus facile de ~5,5 pts (mesuré à N=0, où aucune fuite n'est possible), parce que le FPS a retenu les crops les plus atypiques — donc les plus durs. Les deux biais jouent en sens contraire | banc `bench_encoder_dino` (fuité) vs `bench_refs_curve` (held-out), même gold `0ecbb1d70e3c` | ✅ **mesuré** — geste minimal proposé : tracer `n_leaked` dans `encoder_bench_runs`, ou ajouter une bande held-out au banc |

## Journal des révisions de croyances

> On consigne ici, daté, chaque fois qu'un benchmark **renverse** une hypothèse.
> Ordre : le plus récent en tête.

- **2026-08-20 (soir, re-bench puis mesure par classe) — la règle « jamais UN
  seul exemplaire » a été implémentée, elle DÉGRADE, et elle est RETIRÉE. La
  croyance révisée n'est pas une mesure : c'est un mode de raisonnement.** L'entrée
  ci-dessous (courbe du même jour) tirait de la courbe une règle de conduite :
  plancher `min_exemplars = 2`. Le plancher a été codé, la banque rebâtie avec
  (build `365dcab2a253`, **1533 → 1495 ancres**, **182 → 124 classes à
  exemplaires**, 68 classes ramenées au canonique seul), P3 refait contre elle
  (12 454 prédictions, 0 périmée), et le re-bench held-out à N=10 rend :

  | held-out, N=10 | avant plancher | après | delta |
  |---|---:|---:|---:|
  | `dinov2_vits14` | 75,5 % | **74,1 %** | **−1,4** |
  | `dinov2_vitl14` | 85,7 % | **84,8 %** | **−0,9** |

  Contrôle qui autorise la comparaison : **à N=0 les deux banques sont
  identiques** (671 canoniques, aucun exemplaire) et rendent le même score à
  0,1 pt près — 53,1 → 53,2 % et 76,1 → 76,2 % — malgré le passage de 1100 à
  1179 crops held-out. Les populations sont donc comparables.

  **La faute, nommée : on a extrapolé d'un AGRÉGAT à une RÈGLE PAR CLASSE.** Le
  point N=1 de la courbe (50,1 % contre 53,1 % à N=0) décrit une banque où
  **toutes** les classes sont plafonnées à un exemplaire. La situation réelle
  était tout autre : 68 classes à un exemplaire, 114 plus riches. Rien dans la
  courbe ne mesurait *« que se passe-t-il si je ramène ces 68-là au canonique
  seul, les autres restant pleines »* — et c'est pourtant l'action qu'on en a
  déduite. La mesure était juste ; l'inférence ne l'était pas.

  **Ce qu'on en garde comme règle de travail** : *un point de courbe agrégée ne
  justifie jamais une règle appliquée classe par classe — il faut le mesurer
  dans le régime mixte où il sera appliqué.* C'est la version « données » de la
  leçon H12 sur les benchmarks publics : la ressemblance n'est pas le transfert.

  **Ce que ce delta seul ne permettait pas** : la banque n'a pas changé que par
  le plancher (le FPS a rejoué sur un pool qui avait bougé, 10 classes ont gagné
  des exemplaires, les crops fuités sont passés de 858 à 779), 1495 ancres
  offrent mécaniquement moins que 1533, et à **N=2 la nouvelle banque est
  meilleure** (55,9 % contre 54,6 %) avec moins de lignes — non expliqué. Le
  geste qui tranchait est une mesure **par classe**.

  **Ce geste a été fait le même soir, et il ANNULE la règle.** Sans rebuild, en
  restreignant la courbe (`--bank-classes`, `--gold-classes`, `--rank-order`,
  McNemar exact par palier) :

  1. La population visée est **inévaluable** — 77 crops dans le gold pour ces
     classes, dont 61 sont le crop qui deviendrait leur ancre : **16 crops
     held-out** pour ~70 classes.
  2. Donner à 57 classes riches **exactement un** exemplaire **améliore** leurs
     propres crops : `vitl14` 67,6 → **69,1 %** (p=0,048), `vits14` 41,6 →
     **45,5 %** (p=4,5e-10). *La prémisse était fausse dans le sens où elle
     était affirmée.*
  3. Le creux à N=1 vient de l'**ordre** du FPS, pas du nombre : non significatif
     en `vits14` (p=0,279) et, à nombre d'ancres identique, `--rank-order last`
     rend **77,8 %** au lieu de 73,8 % en `vitl14`.

  **Décision** : `min_exemplars` revient à **1** (plancher inactif), mécanisme
  conservé et testé. ⚠️ **Réserves** : la mesure décisive est un **proxy**
  (classes riches plafonnées à 1), et le vrai levier — amorcer le FPS au médoïde
  — n'est **pas** implémenté. ⚠️ **La banque servie porte encore le plancher, le
  code ne l'applique plus** : le prochain rebuild changera sa forme, et le garde
  P1 ne le signalera pas. Détail : [`COURBE-REFERENCES.md`](../work-in-progress/scan-sans-retrain/COURBE-REFERENCES.md)
  §Mise à jour, D5 de [`DECISION.md`](../work-in-progress/scan-sans-retrain/DECISION.md).

  ⛔ **Effet de bord à connaître** : `bench_refs_curve.py` ignore
  `min_exemplars` (défaut S6). Un palier N y signifie « **toutes** les classes
  plafonnées à N » — c'est exactement la confusion qui a produit cette entrée.

- **2026-08-20 (courbe mesurée après le banc) — la courbe « références par
  classe » existe, et elle transforme H1 en règle de conduite chiffrée : viser
  8 crops validés par classe, jamais s'arrêter à 1.** C'est le chiffre qui
  dimensionne le budget de review, donc la trajectoire de l'année. Rapport
  complet : [`COURBE-REFERENCES.md`](../work-in-progress/scan-sans-retrain/COURBE-REFERENCES.md).
  - **Comment elle a été mesurée sans rebâtir la banque.** Les rangs
    *farthest-point sampling* de `dino_class_references` s'apparient exactement
    aux lignes du `.npz` servi (862/862 exemplaires, **0 écart dans chaque
    sens** ; 671 canoniques, différence symétrique 0 ; `selected_sim` monotone
    croissant avec le rang sur **680 paires consécutives, 0 violation**). Un
    préfixe par rang équivaut donc à un build `exemplars_per_class = N` : on
    encode **une fois** et on sous-échantillonne la matrice en mémoire — 67 s en
    `vits14`, 6 min 48 en `vitl14`, pour 7 paliers et 3 populations.
    Outil : `ml/scripts/bench_refs_curve.py`.
  - **Un piège trouvé en chemin, plus gros que celui qu'on cherchait : 858 des
    1958 crops du gold SONT des lignes de la banque.** Les noter contre elle,
    c'est mesurer une similarité de 1,0 avec soi-même. Toutes les courbes sont
    donc **held-out** (1100 crops / 72 classes). Le harnais reproduit le banc
    officiel **au dixième de point** en régime fuité (`vits14` 85,9 / 97,2 /
    96,0 ; `vitl14` 91,6 / 97,9 / 97,4), ce qui le valide **et** établit que les
    chiffres publiés de [`BENCH-ENCODEURS.md`](../work-in-progress/scan-sans-retrain/BENCH-ENCODEURS.md)
    sont optimistes de **+10,4 pts** (`vits14`) et **+5,9 pts** (`vitl14`) en
    niveau absolu. Le **classement** n'est pas retourné.

    | N réf./classe (held-out) | 0 | 1 | 2 | 3 | 5 | 8 | 10 |
    |---|---:|---:|---:|---:|---:|---:|---:|
    | `dinov2_vits14` global@1 | 53,1 % | **50,1 %** | 54,6 % | 57,3 % | 66,4 % | **73,9 %** | 75,5 % |
    | `dinov2_vitl14` global@1 | 76,1 % | **72,5 %** | 74,5 % | 76,1 % | 79,6 % | **84,4 %** | 85,7 % |

  - **Trois résultats.** (1) **La forme de la courbe ne dépend pas de
    l'encodeur** — creux, remontée, écrasement du rendement au même endroit,
    décalage de niveau constant : le budget de review se décide **avant** le
    choix d'encodeur. (2) **La première référence fait BAISSER la précision**
    (−3,0 pts en `vits14`, −3,6 en `vitl14`, sur les deux populations) ; en
    encodeur de production il faut **N=5** pour repasser au-dessus du canonique
    seul, N=3 rendant *exactement* le chiffre de N=0 (76,09 % dans les deux
    cas). (3) Le budget, mesuré : un crop validé donne une référence à
    **96-97 %**, et amener les 671 classes à N=8 demande **4 622 crops**, soit
    **2,4×** tout ce qui a été reviewé depuis le début du projet — dont
    **489 classes (73 %) aujourd'hui à zéro exemplaire**.
  - 🔴 **Le résultat que la vérification a cassé, et c'était le plus vendeur.**
    La première rédaction annonçait un **« coude à N=8 »**. C'est un artefact du
    maillage : les paliers par défaut sautent de 5 à 8 à 10. Relancé sur
    `--refs 4 5 6 7 8 9 10`, **le même détecteur ne trouve plus aucun coude** —
    les gains oscillent (3,72 · 4,82 · 1,00 · 1,73 · **0,18** · 1,36 pt/réf) et
    ne se stabilisent jamais. Le seuil du détecteur (1 pt/réf) est d'ailleurs
    **sous le plancher de bruit** : sur 1100 crops, 1 point = 11 crops.
    L'analyse appariée le chiffre : 8 → 9 est du bruit (net +2 crops, `z=0,50`)
    mais **8 → 10 reste significatif** (+1,55 pt, 34 gagnés / 17 perdus,
    `z=2,38`, `p≈0,017`). **« Viser 8 » reste l'arbitrage recommandé ; « ne pas
    dépasser 10 » n'est appuyé par aucune mesure.**
  - 🔴 **Deuxième correction : la population held-out n'est pas un plancher
    prudent.** À N=0 la banque est canonique seule, **aucune fuite n'est
    possible** — et l'écart subsiste : 53,1 % held-out contre 47,7 % sur les
    1958 crops (`vits14`), 76,1 % contre 70,5 % (`vitl14`). Les 858 crops
    écartés valent **40,8 %** à eux seuls. Cause : le FPS retient les crops les
    plus diversifiants, **donc les plus durs**, et ce sont eux qu'on exclut. La
    population held-out est plus facile de **~5,5 points**, indépendamment de
    toute fuite. Les deux biais jouent en sens contraire selon le palier : on ne
    peut corriger ni l'une ni l'autre par un décalage constant.
  - **La leçon de méthode, jumelle de celle du banc.** Ici ce n'est pas un
    benchmark public qui n'a pas transféré, c'est **un choix de présentation qui
    fabriquait un fait**. Sept paliers non régulièrement espacés suffisaient à
    faire apparaître un plateau qui n'existe pas, et le détecteur, lui, était
    juste. La garde qui manquait n'est pas un test — la suite était verte, 1843
    au vert — c'est **de rejouer la même mesure sur un maillage qu'on n'a pas
    choisi**.
  - ⚠️ **Ce que la courbe ne dit PAS.** (a) **C'est la tâche review** — photos
    de vendeurs eBay — **cadrées par un vendeur qui veut montrer la pièce**,
    souvent floues ou de loin mais statiques, entières et *choisies* — **pas la
    tâche scan**, dont le corpus compte toujours **0 capture versionnée** (pour
    2 264 images device non protégées) ; H10 reste entière. (b) La sélection FPS est
    celle de `dinov2-vitl14` : on fait varier le *nombre* à *sélection
    constante* (c'est ce qui isole la variable, et c'est aussi **H13**).
    (c) Rien n'est mesuré **au-delà de N=10**. (d) Le creux à N=1 est
    **expliqué, pas démontré**.
  - **Un défaut de plus, hors périmètre** : le gold est bâti sur
    `review_queue.decided_eurio_id`, la banque sur `image_assets.eurio_id` —
    ils **divergent sur 5 assets**, donc 5 ancres portent une classe que la
    review contredit. Impact négligeable sur la courbe (5 sur 862, tous hors
    held-out), consigné en **Q13** de
    [`FINDINGS.md`](../work-in-progress/scan-sans-retrain/FINDINGS.md) §8.10.

- **2026-08-20 (banc à 01:11Z, réplique relue à 03:22) — un benchmark public de
  la BONNE famille de tâches n'a pas transféré. DINOv3 est réfuté sur nos
  données.** C'est le renversement le plus réutilisable du chantier, et ce n'est
  pas « DINOv3 perd » : c'est que **la seule chose qui a tranché est une mesure
  sur nos crops**, après qu'un argument public sérieux eut pointé dans l'autre
  sens pendant deux jours.
  - **Ce que disait l'argument public** (arXiv 2508.10104) : DINOv3 ViT-S/16 fait
    mAP **0,406** contre **0,327** pour DINOv2 ViT-S/14 en recherche d'instance,
    soit **+24 % relatif à taille égale**, +10,8 pts sur Met. Met — œuvres de
    musée, peu de références par classe, discrimination par détail fin — est
    **structurellement notre problème**. Ce n'était pas une extrapolation de
    tâche lointaine : c'était le meilleur transfert qu'on pouvait espérer.
  - **Ce que rend la mesure.** Banc `bench_encoder_dino`, gold figé
    `0ecbb1d70e3c`, **1958 crops, 0 crop non encodé**, banque `2eur_all` à 1533
    ancres, chaque modèle avec **sa** transform recommandée :

    | Modèle | M params | dim | global@1 | global@5 | pays@1 | ms/img |
    |---|---:|---:|---:|---:|---:|---:|
    | `dinov2_vitl14` *(sert la review)* | 304,4 | 1024 | **91,6 %** | 97,9 % | **97,4 %** | 122 |
    | `dinov2_vits14` | 22,1 | 384 | **85,9 %** | 97,2 % | 96,0 % | **16** |
    | `timm:convnext_tiny.dinov3_lvd1689m` | 27,8 | 768 | 81,5 % | 91,8 % | 90,4 % | 16 |
    | `timm:vit_small_patch16_dinov3.lvd1689m` | 21,6 | 384 | **78,7 %** | 91,7 % | 89,9 % | 22 |

    McNemar apparié contre `dinov2_vitl14` : vits14 `b=163 c=50 p=3,6e-15` ;
    dinov3 vits16 `b=286 c=32 p=3,8e-52` ; dinov3 convnext-t `b=237 c=39
    p=9,0e-36`. **À taille égale (21,6 M vs 22,1 M), DINOv3 fait 7,2 points de
    MOINS.** Le signe est inversé par rapport au public, pas seulement atténué.
  - **La leçon de méthode, écrite pour être réutilisée.** Un benchmark public
    n'est jamais une preuve, même quand sa tâche ressemble à la nôtre — et
    surtout quand elle lui ressemble, parce que c'est là qu'on cesse de se
    méfier. Ce qui a sauvé la décision n'est pas d'avoir douté : c'est d'avoir
    **écrit le doute comme une hypothèse falsifiable** (H12) et **semé la mesure
    qui la tue** avant de commencer. [`PROTOCOLE-BENCH.md`](../work-in-progress/banque-dino/PROTOCOLE-BENCH.md)
    §« Sur DINOv3 » l'avait posé mot pour mot : *« le benchmark public n'est pas
    notre tâche […] la seule mesure qui tranche est celle qu'on fera sur nos
    1 955 crops »*. Le coût du doute a été **un run de banc** ; le coût de la
    croyance aurait été un export TFLite, un rebuild de banque et un APK.
  - **Ce que la mesure ne dit PAS**, et il faut le dire aussi fort :
    (a) **c'est la tâche review** — photos de vendeurs eBay, cadrées par
    quelqu'un qui veut montrer la pièce —
    **pas la tâche scan** (frame caméra en main, reflets), dont le corpus est
    à **0 capture versionnée** ; le classement peut différer et H10 reste ouverte ;
    (b) la banque a été **sélectionnée par FPS dans l'espace de `dinov2-vitl14`** :
    le banc ré-encode bien les images avec chaque modèle, mais pas le **choix**
    des images — un DINOv3 avec sa propre banque n'a pas été mesuré (**H13**),
    et ce biais joue contre les candidats.
  - **Trois autres faits du même jour, mesurés.** Rebuild de la banque
    `2eur_all` : **671 classes, 1533 ancres, 182 classes à exemplaires** (contre
    125), build `23c637d93b43`. **P3 fait** : 12 454 prédictions recalculées, 0
    erreur, poussées au canonique (28 min). Réplique rafraîchie, et
    `calibration_blockers(anchors_kind='2eur_all', encoder_version='dinov2-vitl14')`
    rend désormais **`[]`** — zéro bloqueur (relevé ici même sur le pull du
    2026-08-20 03:22). Les candidats gardent leurs deux bloqueurs P1/P3, **par
    construction** : aucune banque n'a été bâtie sous eux. Cela n'entache pas le
    classement — le banc ré-encode tout à chaque run et ne lit aucune prédiction
    stockée ; cela bloque seulement la proposition de seuil.
  - ⚠️ **Un chiffre de fraîcheur qu'il ne faut plus recopier.** La requête de
    complétude P3 telle qu'écrite dans `PREREQUIS.md` / `GESTE-P3.md`
    (`computed_at < built_at`, comparaison de **chaînes**) rend **12454** sur la
    réplique fraîche, alors que la bonne rend **0** : les deux colonnes n'ont pas
    le même format (`'2026-08-19 23:48:36'` contre
    `'2026-08-19T14:36:14+00:00'` ; l'espace vaut 0x20, le `T` vaut 0x54).
    Vérifié : `SELECT SUM(computed_at < b), SUM(datetime(computed_at) <
    datetime(b))` → `(12454, 0)`. Le code de `_p3_blockers` est corrigé
    (`datetime()` des deux côtés) ; la **doc** ne l'était pas. Un rapport
    antérieur qui conclut « P3 non abouti » sur cette requête est faux.

- **2026-08-20 (soir) — deux jours de revue adversariale ont trouvé 45 défauts
  sur un lot dont la suite n'a jamais rougi ; sept sont la même maladie.** Fait
  de méthode, pas chiffre d'encodeur — et c'est une **mesure du rapport de force
  entre les tests et la revue dans ce dépôt**, pas une impression.
  - **Les deux séries, côte à côte.** Le registre de dette
    ([`../work-in-progress/scan-sans-retrain/FINDINGS.md`](../work-in-progress/scan-sans-retrain/FINDINGS.md) §8)
    est passé de **16 → 22 → 33 → 45 lignes** en deux jours et quatre passes.
    Pendant ce temps la suite `ml/` est passée de **1690 → 1797 → 1820 passed,
    0 failed**, toujours dans les deux ordres d'exécution. **Aucun** des 45
    défauts n'a été trouvé par un test ; **tous** l'ont été par lecture
    adversariale suivie d'une exécution. Le compte au soir : 17 ✅ · 3 ⚠️ ·
    3 ⏭ · 1 🔍 · **21 🔴**.
  - **Corriger crée sa dette, et c'est maintenant une régularité mesurée sur
    trois passes.** Passe 1 : 16 fermés, 6 neufs. Passe 2 : 7 fermés, 11 neufs.
    Passe 3 : 2 fermés (M1, M2), **12 neufs** — dont l'un des deux « fermés »
    (M2) requalifié en partiel par sa propre vérification. Une passe de
    correction non vérifiée doit être lue comme une **hypothèse**, jamais comme
    un état.
  - **Sept instances d'un seul motif, et il se déplace à chaque correctif.**
    « Le garde branché sur le chemin qu'on avait en tête » : on ferme le
    **câblage** (M2 : l'invariant descend dans la seule fonction qui écrit) et
    le **prédicat** reste faux — quatre payloads forgés franchissent la porte et
    laissent en base la ligne exacte que la page admin lit « promouvable ». On
    pose un **détecteur** du chemin suivant (un test qui énumère les écrivains
    par AST) et il ne voit pas un nom de table interpolé — vérifié par mutation :
    13 passed avec le contournement en place, 2 failed avec le même
    contournement en SQL littéral. On met l'encodeur dans la **clé primaire**
    (migration 0010) pour que deux banques coexistent, et **tous les lecteurs
    deviennent faux le jour même** sans avoir été touchés : la route admin rend
    deux canoniques pour une classe, et le plan de capture P5 — un livrable
    humain, on photographie d'après lui — déplace 9 classes de strate parce
    qu'un encodeur candidat a été benché.
  - **La question qui manquait, et qu'on ajoute à la discipline** : *ce
    correctif rend-il possible un état que le reste du code croit impossible ?*
    Avant 0010, deux lignes du même crop ne pouvaient pas coexister ; tous les
    lecteurs écrits sous ce régime étaient **accidentellement justes**. Aucun
    diff ne les montre, aucune mutation ne les atteint, et la suite reste verte.
    Se la poser coûte un `grep`.
  - **Ce que ça change concrètement.** Après le câblage d'un garde, une
    demi-heure de payloads forgés contre le **vrai point d'entrée** (route
    montée sur `TestClient`, base jetable) est le meilleur rendement observé du
    chantier : quatre défauts en une sonde, sur un garde que tout le monde
    croyait fermé. Motif complet, mécanismes nommés et parades :
    [`../work-in-progress/scan-sans-retrain/FINDINGS.md`](../work-in-progress/scan-sans-retrain/FINDINGS.md)
    §8.9 (la note) et §8.10 (les douze constats).

- **2026-08-20 (matin) — le même défaut, trois fois le même jour : le chemin de
  base codé en dur est un motif, pas un accident.** Seconde passe de correction
  (trois lots + intégration), puis deux vérifications. Fait de méthode, pas
  chiffre d'encodeur.
  - **Trois occurrences, un motif.** `build_dino_anchors` (la cause racine),
    `bench_encoder_dino` (repli divergent) et `backfill_dino_predictions` (le
    geste P3) portaient la même forme, plus neuf scripts frères audités. Ce qui
    le rend invisible tient en une phrase : **une base périmée répond
    normalement — elle ne lève pas, elle rend simplement moins de lignes**. Et
    `Store()` sur un chemin inexistant **crée le fichier et bootstrappe le
    schéma** (reproduit), donc sur le VPS le script annonçait « 0 candidats, 0
    erreurs » sur une base vide qu'il venait de créer. Convention tranchée,
    motif et parade écrits :
    [`../work-in-progress/scan-sans-retrain/FINDINGS.md`](../work-in-progress/scan-sans-retrain/FINDINGS.md) §8.7.
  - **Corriger crée sa dette, confirmé une seconde fois.** Sept défauts fermés
    et vérifiés (D1 volet P1, D5, D8, D16, N1, N2, N6), **onze neufs** trouvés
    par la vérification. La proportion de la première passe se reproduit.
  - **La maladie a une forme plus stable qu'on ne croyait.** On avait diagnostiqué
    D1 comme *un garde qui ne se déclenche pas dans le cas qu'il devait couvrir*.
    M1 et M2 disent mieux : **le garde est juste, et il est branché ailleurs que
    là où la chose arrive.** P1 compte maintenant le bon encodeur dans une table
    dont la PK ne peut pas en distinguer deux ; D8 et D16 mesurent le bon chiffre
    sur le seul chemin que l'attaquant qu'ils **nomment** n'emprunte pas.
  - **Ce que ça change dans la discipline de test.** Une campagne de mutation
    prouve qu'un test *couvre* le code écrit ; elle ne dit **rien** sur le fait
    que ce code soit *appelé* là où le monde réel passe. Les trois findings
    graves du jour sont invisibles à la mutation et visibles en **une commande
    d'exécution**. C'est la distinction prédicat / câblage de la skill
    `eurio-verify`, et il faut en faire une passe systématique, pas un réflexe
    occasionnel. Corollaire mesuré : **`1797 passed` n'est pas une propriété** —
    un des 1797 (`test_environnement_du_devshell_est_bien_celui_quon_croit`) a
    son corps neutralisé par un fixture autouse, `assert False` le laisse vert.

- **2026-08-19 (nuit) — 1690 tests verts n'ont pas empêché 16 défauts ; trois
  revues de code les ont tous trouvés en une session.** Passe de correction du
  lot P4/P6 (banc multi-encodeurs). Ce qui est consigné ici n'est pas un chiffre
  de qualité d'encodeur mais un **fait de méthode**, et il renverse une habitude.
  - **Le rapport de force est mesuré.** La suite `ml/` passait **1690 passed, 0
    failed** (deux exécutions, avec et sans `-p no:randomly`) sur un lot qui
    portait **16 défauts** — dont cinq pannes muettes, un garde qui s'auto-désarme
    sur les runs qu'il devait couvrir (D1), un label de vérité pris à la mauvaise
    colonne (D6 : **242 lignes fausses ou nulles sur 1958**, 12,4 %), et deux
    définitions concurrentes du même jeu d'évaluation (D5). **Aucun** n'a été
    trouvé par un test ; **tous** l'ont été par lecture adversariale. Registre
    daté, défaut par défaut :
    [`../work-in-progress/scan-sans-retrain/FINDINGS.md`](../work-in-progress/scan-sans-retrain/FINDINGS.md) §8.
  - **La revue de la correction vaut la revue du code.** Après quatre lots de
    correction (+64 tests, suite à **1754 passed**), deux vérifications
    adversariales de la *passe* ont trouvé **6 défauts neufs** (N1..N6) et
    rabaissé **5 corrections sur 16** au rang de partielles. Trois des six neufs
    ont été **introduits par les correctifs eux-mêmes**. Corriger n'est pas un
    acte sûr : il crée sa propre dette, dans la même proportion.
  - **Le test qui compte est celui qu'on a vu rougir.** 18 mutations posées puis
    revertées sur les gardes neufs : **17 rougissent le test attendu**. La 18e a
    révélé que l'unique garde de non-silence de D6 — une `ValueError` — n'est
    couvert par rien : le remplacer par `return ""` laisse `23 passed`. Un garde
    qu'aucune mutation ne fait tomber n'est pas gardé.
  - **⚠️ Et un compte de tests verts n'est pas une propriété.**
    `test_calibration_blockers_gold_entier_nest_pas_un_echantillon` — précisément
    le test qui tient D8 — a échoué **1 fois sur 6** exécutions complètes en ordre
    fixe, sur un arbre inchangé ; non reproduit isolé (`1 passed`), ni sur 40
    graines intra-fichier. Interaction inter-fichiers, cause non trouvée. C'est R6
    qui s'entame : une suite qui rougit sans raison retrouvée rend le prochain
    échec réel indistinguable du bruit.
  - **Ce que ça change dans la règle de travail** : un lot vert n'est pas un lot
    vérifié. Le geste qui a payé, ici, c'est *une revue adversariale par lot, puis
    une revue de la correction* — et la discipline de mutation sur chaque garde
    neuf, pas seulement sur le code corrigé. ⚠️ Ce constat porte sur **une**
    session et **un** lot ; ce n'est pas une statistique.
  - Rien n'est commité ; P3 n'a pas été lancé ; la banque servie n'a pas été
    rebâtie (mtime + md5 des 4 `.npz` identiques du début à la fin).

- **2026-08-19 (16:36) — la banque rebâtie sur la bonne base rend exactement les
  182 classes prédites : la cause était suffisante, et le SQL la prédisait.**
  Rebuild `2eur_all` après correction du `--db` codé en dur de
  `build_dino_anchors.py`. Build `23c637d93b43` poussé au canonique, **237 s**.
  - **Le delta, mesuré sur le `.npz` servi** (pas sur un rapport ; commande dans
    [`../work-in-progress/scan-sans-retrain/PREREQUIS.md`](../work-in-progress/scan-sans-retrain/PREREQUIS.md) §P1) :

    | | avant | après |
    |---|---:|---:|
    | classes | 664 | **671** |
    | lignes d'ancres | 1250 | **1533** |
    | exemplaires réels | 586 | **862** |
    | **classes avec exemplaires** | **125** | **182** |
    | canonique seul | 539 | **489** |

  - **Ce qui est renversé, c'est la méthode de diagnostic, pas un chiffre
    d'encodeur.** Rejouer la sélection du builder en **pur SQL, sans encoder**,
    avait annoncé « 182 classes ». Le rebuild réel en rend **182**, exactement.
    Une cause racine se confirme donc **avant** de payer le calcul, à condition
    de savoir rejouer la sélection seule. L'estimation de volume, elle, était
    généreuse de 18 % (`~1050` exemplaires annoncés, **862** réels) : l'écart
    vient du seul terme non simulable, le plancher `floor_sim = 0.45` appliqué
    **après** encodage.
  - **Le régime canonical-only reste dominant** : 489 classes sur 671, soit
    **73 %** (contre 81 % avant). Le rebuild lève un défaut, il ne remplit pas
    le catalogue — et H4 mesure ce régime à **62,8 %** top-1 contre **72,7 %**
    en wild-rich. C'est P5 (la campagne de capture) qui porte ce sujet, pas le
    choix d'encodeur.
  - **Direction A, piège à ne pas « corriger »** : la réplique locale affiche
    encore `1250 / 125`. La trace part au canonique par HTTP ; la base locale
    n'est pas écrite. Corollaire attendu : `calibration_blockers` lu sur la
    réplique continue de rendre `P1: … 125 classes (attendu >= 180)`.
  - ⚠️ **Le geste suivant était piégé, il ne l'est plus** : bâtir la banque
    d'un encodeur **candidat** effaçait ces 182 classes. La PK de
    `dino_class_references` était `(anchors_kind, class_id, eurio_id,
    asset_id)` — **sans `encoder_version`** ; l'index unique qui le porte est
    *partiel* (`WHERE asset_id IS NULL`), donc canoniques seulement. Reproduit
    sur le DDL réel via le vrai writer : `prod=200 cand=0` → `prod=0 cand=200`.
    Défaut **M1**, **fermé le 2026-08-20** : la clé primaire est désormais
    `(anchors_kind, encoder_version, class_id, eurio_id, asset_id)` avec
    `encoder_version NOT NULL DEFAULT ''` (migration `0010` + miroir
    `state/schema.sql`), et le writer refuse une table à l'ancienne clé.
    ⚠️ **Reste un geste humain** : 0010 n'est appliquée au canonique qu'au
    redémarrage de `eurio-api` — à faire **avant** ce premier build candidat.
    ⚠️ **Et le piège s'est déplacé, il n'a pas disparu** (constat du 2026-08-20
    au soir, défaut **Q6**) : plus rien n'est détruit, mais **aucun lecteur** de
    `dino_class_references` ne nomme `encoder_version` — ils n'avaient jamais eu
    à le faire, la coexistence étant impossible. Mesuré sur données réelles :
    `get_class_references` rend **22 lignes au lieu de 11** avec deux canoniques
    pour une classe, et le vrai CLI du plan de capture P5 déplace **9 classes de
    strate**. Le premier build candidat reste donc interdit tant que Q6 est
    ouvert.

- **2026-08-19 — La banque DINO servie avait été bâtie sur la mauvaise base ;
  ConvNeXt-Tiny s'effondre en CPU batch 1 ; DINOv3 est redistribuable.** Session
  « scan sans réentraînement ». Cinq renversements, tous mesurés — détail et
  requêtes : [`../work-in-progress/scan-sans-retrain/FINDINGS.md`](../work-in-progress/scan-sans-retrain/FINDINGS.md).
  - **La cause des 57 classes manquantes est trouvée** — six hypothèses avaient
    été éliminées sans conclusion. `ml/scripts/build_dino_anchors.py` codait son
    `--db` par défaut en dur sur `ml/state/eurio.db` au lieu d'honorer
    `EURIO_DB_PATH` : **6205 `image_assets` contre 12454** dans la réplique.
    Rejouer la sélection sur `eurio.db` reproduit **exactement** les 125 classes
    et les 586 exemplaires de la banque servie (ensembles de diff vides des deux
    côtés). La sixième piste — « le build aurait tourné sur une autre base » —
    avait été écartée sur un raisonnement faux : la réplique porte les
    références parce qu'elles y sont **poussées par HTTP**, ce qui ne dit rien de
    la base *lue*. Correctif écrit + test, rebuild non lancé.
  - **`dino_class_references` n'est plus vide** (CONSTAT.md disait « vide dans
    les 8 bases locales et au canonique ») : **1250 lignes** (664 `canonical` +
    586 `fps`), 1 `dino_anchor_builds`. Et **« 130 pièces sans ancre » est
    périmé** : 664 classes ont leur canonique, les 7 restantes ont été
    rapatriées le jour même (7 appels Numista, `n_no_canonical` 7 → 0).
  - **⚠️ ConvNeXt-Tiny est catastrophique en CPU batch 1** — le régime du scan
    Android. Mac, torch 2.9.1, 8 threads : dinov3 ConvNeXt-T **292,8 ms** bs1
    (reproduit : 292,6 ms machine libre, 286,0 en `channels_last`) contre
    **24,5 ms** pour dinov3 ViT-S/16, à taille comparable (27,8 vs 21,6 M). Le
    même ConvNeXt est pourtant **le plus rapide des quatre en MPS (9,5 ms)**.
    Cela **inverse** l'ordre d'export proposé (« ConvNeXt d'abord ») : le
    ViT-S/16 devient le candidat APK par défaut. Caveat H11 : mesures
    PyTorch/Mac, pas TFLite/Android — signal fort, pas verdict. Référence :
    dinov2 ViT-L/14 (celui qui sert la review) = 217,9 ms CPU bs1, 304 M params.
  - **DINOv3 est redistribuable dans un APK commercial**, sous trois conditions
    (§1.b.i) : distribuer sous le même accord, joindre une copie de l'accord,
    et afficher « Built with DINOv3 ». ⚠️ Cette dernière clause figure sur
    `ai.meta.com` et **pas** dans le `LICENSE.md` de GitHub (`grep -c 'Built
    with'` → 0) — on se conforme à la plus stricte. La quantification TFLite ne
    lave pas la licence (le §1.b.i vise « any derivative works thereof »).
    **Correction d'une erreur de la doc** : les variantes « EUPE » ne sont pas
    des variantes de DINOv3 mais une famille séparée sous licence non
    commerciale ; les vraies variantes sont `lvd1689m` et `sat493m`, toutes deux
    sous la même licence DINOv3.
  - **Le gold du banc d'encodeurs est figé** : 1958 crops / 194 classes,
    `gold_version=0ecbb1d70e3c`. Piège attrapé : 8 classes / **105 crops
    (5,4 %)** ont un `class_id` de banque différent de leur `eurio_id` (repli sur
    le représentant du groupe de dessin) — un gold naïf aurait **plafonné le
    recall à 94,6 %** sur tous les encodeurs, sans rien signaler.
  - **Ouverture d'[ADR-008](../adr/008-deux-voies-backbone-gele-et-arcface.md)** —
    deux voies (backbone gelé + banque, à côté d'ArcFace), départagées par le
    corpus de scan et par lui seul. H10 est l'hypothèse que ce chantier teste.
  - ⚠️ **Rien de tout ça n'est un chiffre de qualité d'encodeur** : le bench
    comparatif n'a pas été lancé, la banque n'a pas été rebâtie, et les 12454
    prédictions restent périmées (P3, hors périmètre sans go du PO).

- **2026-06-11 — Premier test réel (C0) renverse H2 et H6.** Éval de
  `arcface-vits14-v1` sur **317 vraies photos device** (`eval_real_norm`, ~17
  classes) via `vision/eval_real_snaps.py` :
  - Centroïdes **déployés** (val-mean + ArcFace-W) : **top-1 = 77.60%** (246/317).
  - Centroïdes **ArcFace-W purs** : **top-1 = 82.65%** (262/317).
  - Rappel R@1 **val** = 66.67%.
  - **H2 (ArcFace-W est mauvais) → contredit** sur ce modèle : W bat val-mean de
    **+5 pts**. On allait construire C1 sur la croyance inverse (héritée du run
    F2). À confirmer sur un set plus large avant d'en faire une règle.
  - **H6 → le val sous-estime** ici le réel (66.67% val vs 77-82% réel).
  - ⚠️ Caveat : set étroit (~17 classes, recouvrant nos classes fiables), 5 pts
    ≈ 16 snaps. Signal, pas preuve. → élargir le set (C0) avant conclusion.

- **2026-06-12 — Session 2 (C2) : le « maillon manquant » training_eligible
  n'existe pas — le lien review → entraînement est COMPLET.** Le handoff C2
  (§3, gap n°1) supposait qu'aucun code ne reliait une décision de review au
  flag `image_assets.training_eligible`. Audit code exhaustif : le lien existe
  sur **tous** les chemins de décision, atomiquement avec `resolution_status` —
  accept humain (`decide_review`, `bulk_assign_lot_review`), accept 1-click
  DINO (`accept_dino_review`), ack verdict Claude (`ack_claude_verdict`),
  arbitrage pair (`peer_arbitration_routes.approve`) → `=1` ; rejets (humain,
  consensus `enqueue.py`, gate vision, pair) → `=0`. Conso côté training :
  `iteration_augmentations.py:136` (`training_eligible=1` + `storage_status=
  'present'`). Le flywheel n'a PAS de maillon code manquant — ce qui manque,
  c'est du **volume validé** (au 25/05 : 0 asset `training_eligible=1` sur
  1961).

- **2026-06-12 — Baseline H4 texte mesurée (C2).** Replay du theme-matcher
  HEAD sur le gold figé (196 listings) : recall **100 %**, auto-attribution
  **75,8 %** (75/99) à précision **94,9 %** (75/79), junk false-keep **36,5 %**
  (31/85). ⚠️ Mesuré sur la DB scratch du 25/05 (aliases/coins de cette date —
  cf. note DB ci-dessous). Le matcher texte est donc déjà fort en
  auto-attribution ; le rôle réel de la vision est le **résiduel** (21,2 % des
  valides routés review) + le **junk filtering** (le vrai point faible).

- **2026-06-12 — C7 pilier face LIVRÉ (back + données + funnel).** Détecteur
  câblé dans `auto_validate` (réutilise le vec vitl14, τ=0,05, écrit
  `image_assets.face` si NULL), banque `reverse_2eur`, rejet `face_reverse`
  (pattern consensus factorisé), bucket cliquable dans le funnel bench.
  Backfill : **2277 crops 2€ → 231 reverse / 2046 obverse**, 119 rejetés, 48
  listings re-routés ; idempotent ; 566 avers humains intacts. Funnel vérifié
  (7 groupes montrent « Rejeté · revers commun 2€ », drill OK). Reste : rappel
  wild à élargir, UX Android « retourne la pièce » (proto-first, ❌ à proto'er).

- **2026-06-12 — Pivot stratégie (C7) + H7 confirmée.** Constat utilisateur :
  ccproxy/Claude vision « pourri », mais le DINO de la review manuelle classe
  bien. Diagnostic : ccproxy posait la mauvaise question (vérifier la cible eBay
  sur la lane où DINO diverge déjà → 86 % no_match inexploitables). Décision :
  vision = **proposeur d'identité** (DINO top-K), pas vérificateur de cible ;
  lane ccproxy parquée. Ouverture du chantier **C7** (cascade : face →
  authenticité → fusion). **H7 confirmée** du premier coup : détecteur de face
  zéro-training (ancres = 2 designs revers communs packagés) → **0 % FP** sur
  562 avers, top-40 revers minés **100 % corrects**. ~15 % de la queue sont des
  revers non détectés. Détail : C7 §Pilier 1.

- **2026-06-12 (soir) — Clôture itération 1 : v1 reste le modèle de
  référence ; double incident GPU.** Le re-run v2 complet a collapsé (best
  epoch 1 à 52,5 %, puis 45,8 % — pas de seed fixée, variance forte) et le
  GPU (GTX 1080 Ti) est **tombé du bus PCIe (Xid 79)** pendant l'epoch 12
  après ~7 h à 250 W (idem, très probablement, pour l'« extinction » de la
  nuit). Décisions : (1) **v1 reste le fine-tuné de référence** — pas de
  réentraînement avant un vrai delta de données (backlog review) ; (2) longs
  runs sur ce PC : capper la puissance (`nvidia-smi -pl 180`) + raccourcir
  (`--epoch-multiplier 3`) ; (3) à corriger côté trainer : seed fixée +
  `training_log.json` écrit à chaque epoch (pas seulement en fin de run).

- **2026-06-12 (boucle C2, 1re itération) — H1 confirmée ; « best epoch
  précoce » réfutée.** Dataset v2 (544 classes, 455 wild train, 77 test
  held-out par listing). Sur le test held-out : **v1 fine-tuné 71,4 % g@1 ≈
  vitl14 zero-shot 72,7 %**, +17 pts vs vits14 zero-shot (54,5 %) — alors que
  le même v1 fait 28,7 % sur le gold (classes sans wild). **Ce sont les refs
  wild par classe qui font le modèle** → le flywheel est la bonne stratégie.
  Réfuté au passage : « le best val-R@1 à l'epoch 3 ≈ plateau » — v2 interrompu
  à l'epoch 3 fait 59,7 % vs v1 epoch 10 à 71,4 % sur le held-out (le val 59
  img ne voit pas la progression tardive, écho de H6). Run v2 complet relancé
  (~7 h, 35 min/epoch ; batch >32 OOM au défreeze sans xFormers sur 11 Go).
  Détails : C2 §Résultats.

- **2026-06-12 (suite) — DB canonique récupérée (lease Mac→PC) ; les chiffres
  tiennent ; un artefact de slugs débusqué.** Le cycle lease a été fait
  (`ml:db:release` Mac → `ml:db:acquire` PC, 82 Mo). Le 1er replay texte
  canonique donnait 17,2 % @ 23,3 % — c'était un **artefact** : 52 des 53
  « erreurs » étaient la bonne pièce sous un slug renommé (le canonique est
  revenu aux slugs anciens, le gold portait ceux du 01/06). Gold **réaligné**
  (76 verdicts). Chiffres canoniques réels : texte **69,7 % @ 94,5 %** (la
  purge des aliases 563→69 coûte ~6 pts d'auto-attrib, la précision tient) ;
  vision inchangée (zs_country 62,8 % / 79,8 % hit@5 ; arc 28,7 %). La DB
  canonique révèle aussi : **574 crops training_eligible=1 sur 89 classes**
  (le flywheel produit déjà), backlog review 1722 ccproxy / 560 manual / 123
  auto_accept. ⚠️ Les 9 classes gold BE n'ont **aucun** crop wild → le bench
  gold ne mesurera l'effet boucle qu'après review du backlog BE.

- **2026-06-12 — Bench vision pré-classement (C2) réfute H4.** Nouveau bench
  `ml/scripts/bench_vision_preclass.py` (94 listings gold BE, 551 crops
  multi-Hough, ancres canonical-only) : **zero-shot vitl14 `2eur_all` 62,8 %
  top-1 / 80,9 % hit@5** (re-rank pays) vs **arcface-vits14-v1 28,7 % / 35,1 %**.
  Vision seule ≈ 0 % d'auto-attribution à p≥95 %. Décision : la review garde le
  zero-shot vitl14 en suggestions ; l'auto-attribution reste portée par le
  texte ; le fine-tuné ne revient en review que quand ses centroïdes auront des
  refs wild (H1). Détail + caveats : C2 §Résultats.

- **2026-06-12 — ⚠️ Infra : la eurio.db canonique n'est PAS sur ce PC.** Le
  lease MinIO (`ml:db:status`) montre `sha distant ∅` (jamais poussée — bucket
  `eurio-db` créé le 08/06), et la DB locale était un stub vide auto-créé. La
  canonique vit sur le Mac. **Workaround session 2** : copie du backup
  `/nix/store/...-source/ml/state/eurio.db.fix-attempt-20260525` (29 Mo, état
  réel du 25/05) installée en `ml/state/eurio.db` — DB **scratch**, ne jamais
  `ml:db:release` depuis ce PC tant que la vraie DB n'a pas été poussée depuis
  le Mac (`ml:db:release` là-bas, puis `ml:db:acquire` ici).

- **2026-06-11 — 3-way centroïdes (C1) précise H2.** Même set (317 snaps),
  `--centroid-source` : **train-mean 82.97%** · **ArcFace-W 82.65%** ·
  **val-mean 77.60%**. Le maillon faible est **val-mean** (peu d'images val),
  pas ArcFace-W. train-mean ≈ W (égalité). Implication : l'app déployée priorise
  val-mean (le pire) → gain immédiat possible en train-mean. Et train-mean tient
  déjà avec `n=1`/classe → devrait progresser avec plus d'images (H1). Toujours
  set étroit → à confirmer large.

## Sources de vérité (code)

- Entraînement : `ml/training/train_embedder.py`
- Export TFLite : `ml/training/export_tflite.py` (`--fp16`)
- Centroïdes : `ml/training/compute_embeddings.py`
- Spike quantization : `ml/scripts/spike_vits14_litert.py`
- Inférence Android : `app-android/.../ml/CoinEmbedder.kt`, `EmbeddingMatcher.kt`
- Résolution match→pièce : `CoinRepository.resolveByClassifierName` (`findByEurioId`)
- Pipeline scrape/review eBay : `ml:scrape-ebay`, `ml:src:ebay`, `ml:review:*`, `ml:dino-predictions:*`
- Infra bench existante (à auditer en C0) : `ml/bench/`, tâches `ml:bench:*`, `android:bench:*`
