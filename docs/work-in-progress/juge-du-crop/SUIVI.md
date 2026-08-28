# Suivi — juge du crop

> Mets-le à jour à chaque étape franchie. **Un suivi qui ment est pire que pas
> de suivi.** Tout chiffre porte sa requête — recopie la requête, jamais le
> nombre.

## ⏱️ Où on en est — 2026-08-27, ouverture

**L1 est en production. La collecte a commencé.** Chaque recadrage — et chaque
NON-recadrage — du PO produit désormais une ligne de vérité terrain, sans qu'il
change quoi que ce soit à sa façon de travailler.

| en prod | |
|---|---|
| migration `0018` | appliquée au boot (`db_migrate: applying 0018_… (11 180 bytes)`) |
| `POST /review-queue/{id}/crop-edit-abandon` | servie, vérifiée à l'OpenAPI, 204 sur une vraie review |
| front hébergé | redéployé |
| lignes collectées | 0 au 27/08 au soir (la ligne de test a été supprimée) |
| migration `0019` | appliquée au boot le 2026-08-28 (`db_migrate: applying 0019_… (5 926 bytes)`) |
| `/crop-gold/{v}` · `…/annotations` · `…/geler` · `…/instantane` | servies, vérifiées à l'OpenAPI, testées avec un vrai PAT |
| annotations d'or collectées | 0 (la ligne de fumée a été supprimée) |

| lot | état |
|---|---|
| **L0** — `PROBLEME` + `JUGE` + `JEU-D-OR` + seuils signés | 🟡 docs écrits, `d = 0,08·a` **mesuré et confirmé** (28/08), **seuils toujours non signés** (D4) |
| **L1** — instrumentation du recadrage manuel | ✅ **livrée et déployée le 2026-08-27** — la collecte tourne |
| **L2** — outil d'annotation + séance PO | 🟡 **outil, tirage et persistance canonique DÉPLOYÉS** (28/08) — reste la séance du PO, ~40 min + 10 min de double passe à ≥ 24 h |
| **L3** — juge implémenté + **RE-4** | 🟡 **L3.1 + L3.2 écrits et testés** (juge, bornes, harness, RE-2/5/7 exécutables) — RE-4 attend l'or. ⛔ point d'arrêt |
| **L4** — bornes | 🔴 |
| **L5** — méthodes candidates | 🔴 |

## Ce qui est acquis, et qui ne se remesure pas

| fait | chiffre | source |
|---|---|---|
| `quality_score` est **inerte** | 0,9200 accepté / 0,9208 rejeté-crop | canonique, 2026-08-27 |
| `tilt_deg` est **tronqué** par le bas | min 14,07° = `acos(0,97)`, `_TILT_TRIVIAL` | `crop_detectors.py:328,462` |
| `IoU ≥ 0,80` tolère l'amputation | **10,6 % du rayon** (`1 − √0,80`) | calcul exact |
| rejet humain, chemin YOLO | **70,4 %** (et non 92 % — ce chiffre mélangeait les rejets automatiques) | canonique |
| rejet humain, `score_recover` | **93,1 %** | canonique |
| motifs de rejet | `face_reverse` 2 636 · `not_2eur` 2 033 · **crop 1 430** | canonique |
| l'éditeur ne trace que des cercles | **2 926 / 2 926** bbox manuelles carrées | canonique |
| recadrages reconstituables | **2 181 / 2 913** via `detections_json` | réplique |
| le disque intérieur suffit | 96,9–98,8 % contre 98,1 %, **aucun McNemar significatif** | banc du 27/08 |
| rapport de rayons réel | **0,735** (physique 0,699) | 40 crops, gradient b\* |
| largeur du listel nu | **≈ 0,080 a** en médiane (p25 0,060 · p75 0,097) | `bench.gold_crop.measure_listel`, 521/819 canoniques BCE, 2026-08-28 |

## Les pièges de ce chantier

| piège | ce qu'il fait |
|---|---|
| `tilt_trustworthy=1` ⟺ `tilt_deg ≥ 14,07°` | chercher « de face » dedans est une contradiction. Utiliser `axis_ratio ≥ 0,97` |
| **4 678 des 6 299 rejets ne parlent pas du crop** | les inclure dans le vivier apprend à détecter des revers |
| `image_assets.sha256` est **NULL** sur les 20 375 lignes | tirer dessus rend zéro ligne. La clé est `source_images.sha256 || ia.id` |
| le mot « capsule » n'existe pas dans les titres | 3 occurrences. La strate reflets se définit par le **conditionnement** |
| **aucune colonne d'uniformité de fond** n'existe | la strate « facile » est un proxy, confirmé à l'annotation |
| `crop_edit.py` écrit **en place** | la géométrie proposée est écrasée au moment même où elle devient une étiquette |
| **les non-modifications n'existent nulle part** | le jeu reconstitué n'a que des négatifs. Un modèle entraîné dessus apprend que tout cadrage est mauvais |
| geler un oracle ≠ le rendre non-optimisable | geler fixe la cible que l'optimiseur va viser |
| **monotone ≠ informatif** | `arc_coverage` ne peut pas monter sous rognage — et reste à 1,000 jusqu'à 25 % d'amputation. Une grandeur saturée est monotone au sens large et n'apprend rien |
| **le masque dur, pas le cadre, retire les pixels** | C1 sur le carré déclare sain un cas amputé dans les diagonales ; C1 sur le disque met le PLAFOND du banc à 100 % |
| **Cloudflare refuse l'UA par défaut d'urllib** | `Python-urllib/3.x` → **403 « error code: 1010 »**, une page HTML au lieu de JSON. `curl` passe, l'outil non : la panne ne se voit QUE dans l'outil. Tout client Python du canonique doit poser un `User-Agent` — `client/http.py` le fait déjà |
| **le listel n'est pas une zone lisse sur une photo** | c'est l'arête la plus contrastée de l'image. Toute statistique de texture le classe comme « du dessin » — trois mesures ont échoué là avant que la périodicité 12 des étoiles ne marche |

## Journal

| Date | Ce qui s'est passé |
|---|---|
| 2026-08-27 | **Chantier ouvert** après le rejet par le PO d'une n-ième tentative d'amélioration du crop. Sa phrase : « ce n'est pas la première fois qu'on fait un chantier crop et ça ne fonctionne toujours pas ». |
| 2026-08-27 | ❌ **Banc de recadrage guidé par `top1_sim` : 23,3 % de franchissement, et le chiffre ne vaut rien.** La planche visuelle montre le balayage gagnant du score en rognant la légende du bord. Et il ne fait pas que zoomer — `07a52426` est un dézoom franc, donc son mécanisme n'est pas caractérisé. **Mon affirmation « il ne fait que zoomer » était fausse**, le PO l'a trouvée en première ligne de sa planche. |
| 2026-08-27 | 🔴 **Archéologie : sept chantiers, un seul mode d'échec.** Chacun a atteint sa cible sur son propre oracle. `crop-recovery` avait des critères pré-enregistrés et validés PO — **et son seuil `IoU ≥ 0,80` tolérait 10,6 % d'amputation**. Le chantier n'a pas été bâclé, il a mesuré rigoureusement la mauvaise chose. |
| 2026-08-27 | 🔴 **« Ne pas livrer A seul. Viser l'hybride » — écrit dans `crop-recovery/strategy-a/RESULTS.md:105`, et A a été livré seul le jour même** (commit `c831bf27`). Aucune trace de décision, parce qu'il n'existait **aucune ADR sur le crop** en sept chantiers. |
| 2026-08-27 | ❌ **Correction d'un chiffre que j'avais mis partout** : « 1,4 % contre 92 % » était faux des deux côtés. Le 92 % mélangeait les rejets automatiques (rejets de **sujet** sur des crops corrects) avec les rejets humains — le vrai est **70,4 %**. Et le 1,4 % de `manual` est un taux de **survie** : `crop_edit.py:406` fait un UPDATE en place, donc 2 900 des 2 913 `manual` sont d'anciens crops auto réparés puis acceptés. |
| 2026-08-27 | 🔴 **Le premier motif de rejet n'est pas le cadrage** : `face_reverse` (2 636) + `not_2eur` (2 033) contre 1 430 rejets humains. `detect_circles_multi` ne lit **jamais** `source_images.target_eurio_id` — il crope tout ce qui est rond, puis on paie le tri en aval. |
| 2026-08-27 | ✅ **ADR-017 écrite** — la première sur le crop. Découplage eBay ↔ Android, le juge par contrainte, la sortie reste un cercle. |
| 2026-08-27 | ✅ **`tilt_deg` élucidé** : `_TILT_TRIVIAL = 0.97` et `acos(0,97) = 14,0699°`. Effet de sélection par construction, pas biais d'estimateur. La garde est juste ; la colonne est inutilisable pour chercher « de face ». |
| 2026-08-27 | ✅ **L'idée du PO mesurée** : le disque intérieur bimétallique porte toute l'information de dessin (aucun McNemar significatif contre la pièce entière). **Ma crainte était fausse** — le nom du pays est dans le disque, sur son bord, pas dans l'anneau aux étoiles. L'idée n'achète pas de justesse ; elle achète le **droit** de changer de cible de détection sans rien coûter. |
| 2026-08-27 | ⚠️ **Défaut connexe** : `_R_OUTER_FRAC = 0.47` sous-estime le rayon réel (mesuré 0,975 du demi-côté). Les anneaux du `bimetal_score` sont dessinés trop loin. À corriger ailleurs. |
| 2026-08-27 | ✅ **L1 livré et déployé.** Migration `0018` + `crop_edit_observations` + `store/crop_observations.py` + `POST /crop-edit-abandon` + instrumentation du front. Vérifié bout en bout en prod : `before_*` est **relu en base** (r=102,6) alors que le client envoyait `start_r=200` — le serveur ne croit pas le client sur parole. Tests 2542 → 2563 (Python), 14 → 19 (front). **12 mutations jouées, 12 rouges**, dont celle qui compte : faire repartir le delta de `before_*`. |
| 2026-08-27 | 🔴 **Le front est resté figé une heure sans qu'aucune alerte ne le dise.** `build` = `vue-tsc --noEmit && vite build`, et l'image du VPS n'installe que les deps de PRODUCTION : le premier fichier de test **committé** l'a cassé en `TS2307` sur `vitest`. Invisible jusque-là parce que les specs existantes n'étaient pas committées. Le conteneur garde alors son image précédente **et le site répond 200** — panne muette de plus. Corrigé : `tsconfig.json` exclut les specs, `tsconfig.vitest.json` les prend, `typecheck` lance les deux. |
| 2026-08-27 | 🔴 **Puis `--frozen-lockfile` a échoué** : j'avais commité un `package.json` portant des devDependencies **sans son lockfile**. Deuxième déploiement raté d'affilée, même geste — committer un sous-ensemble incohérent de l'arbre de travail. |
| 2026-08-28 | ✅ **`d = 0,08·a` mesuré, la prémisse tient.** Bande sans dessin du parc canonique : **≈ 0,080 a en médiane** après correction du biais (+0,023 a, calibré sur pièce de synthèse). `d` est donc littéralement la médiane du listel nu. `ml/bench/gold_crop/measure_listel.py` + 11 tests ; **8 mutations jouées, 8 rouges**. |
| 2026-08-28 | ❌ **Trois mesures du listel par le relief, trois échecs — et le même faux postulat** : « le listel est lisse ». Sur un rendu ou une photo, c'est l'arête la plus contrastée de l'image (reflet + ombre). Ce qui a marché : la **périodicité 12** des étoiles, que ni le bord ni l'éclairage ne partagent. |
| 2026-08-28 | ⚠️ **Mon commentaire de code disait le biais à l'envers** — j'avais écrit que la mesure sous-estimait la bande ; la pièce de synthèse a montré qu'elle la **sur**estime de 0,023 a. Le test l'a attrapé avant la doc. |
| 2026-08-28 | ✅ **L2.1 + L2.2 livrés.** `bench/gold_crop/sample.py` (tirage reproductible, 60 + 24 réserve) et `bench/gold_crop/annotate/` (outil + serveur, écriture atomique à chaque validation). Mesuré au premier lancement : **84/84 raws déjà en cache** (1,4 s, zéro réseau) et **84/84 pré-remplissages `measure_tilt` réussis**. 38 tests, **19 mutations jouées, 17 rouges** (les 2 survivantes sont documentées comme équivalentes en production). |
| 2026-08-28 | ⚠️ **La clé de tirage ne doit rien au `sha256` du raw.** `length(image_assets.id) = 32`, `length(sha256) = 64` : les 8 derniers caractères de `si.sha256 \|\| ia.id` tombent **entièrement** dans l'id. `JEU-D-OR.md` laissait croire que le hachage du raw pesait sur le tirage — il n'y pèse pas. Le tirage reste bon (uuid4), la phrase était fausse. Corrigée, et verrouillée par un test. |
| 2026-08-28 | ⚠️ **La réserve fait 6 images par strate, pas 8** — `JEU-D-OR.md` annonçait 8 et détaillait `rn` 9-11 / 8-10, soit 6. Le détail a été suivi ; la ligne est corrigée. |
| 2026-08-28 | 🔴 **Une planche de contrôle du tirage a montré des strates douteuses** : des capsules classées `S1_facile`, des raws à deux pièces classés `S4_oblique`. C'est attendu (les strates viennent de proxys textuels) et c'est précisément ce que la **confirmation de strate par le PO** doit redresser — l'outil la demande à chaque image. |
| 2026-08-28 | ✅ **L3.1 + L3.2 écrits.** `judge.py` (C1 dans ses trois lectures, C2, Boundary IoU ancrée sur l'or, IoU de masque, Hausdorff), `geometry.py`, `iface.py`, `datasets.py`, `bras.py`, `harness.py`. **RE-2 est une frontière de type** : un candidat reçoit un `ContexteCandidat` qui ne porte pas l'or, et un contrôle syntaxique refuse un bras qui importerait le juge. RE-5 et RE-7 sont exécutables. 67 tests, **14 mutations jouées, 14 rouges**. Suite 2 602 → 2 669. |
| 2026-08-28 | 🔴 **C2 est inerte : `arc_coverage` = 1,000 jusqu'à 25 % d'amputation.** L'anneau `[0,70 ; 1,15]` de `measure_tilt` englobe la jonction bimétallique (ρ ≈ 0,735), toujours présente dans les 12 secteurs. La monotonie de `JUGE.md` est vraie et **vide**. Resserrer l'anneau la rend discriminante mais elle ne mesure plus que la géométrie — que C1 tranche déjà. Journalisée, retirée du taux d'amputation en attendant l'amendement PO (D8). |
| 2026-08-28 | 🔴 **Le plafond du banc est à 100 % d'amputation sous la lettre de C1.** `gold_replay` prend `r = a`, donc le masque dur coupe pile sur le listel et la marge retenue est nulle : à `m = 0,02`, `gold_replay` échoue partout. C'est géométrique, vrai pour tout or, et c'est **exactement le rôle d'une borne** — sans elle on aurait imputé ça aux méthodes. Trois issues au PO (D9). |
| 2026-08-28 | ⚠️ **La table Boundary IoU de `JUGE.md` supposait une bande proportionnelle à chaque forme.** Le juge ancre `d` sur l'or (sinon une méthode qui rétrécit rétrécit sa propre bande) : 0,4545 et 0,1429 au lieu de 0,464 et 0,148. Écart < 0,01, sans effet sur un classement, mais dit (D10). |
| 2026-08-28 | ⚠️ **Défaut connexe : `measure_tilt` peut compter un 13ᵉ secteur.** `np.degrees(...) % 360.0` rend exactement `360.0` pour un angle négatif infinitésimal, et `int(360/30) = 12` sort de `range(12)` — `arc_coverage` vaut alors 13/12. Là-bas la garde `< 0,60` n'en devient que plus permissive ; ici ça cassait la borne supérieure de C2. Corrigé dans le juge (`% N_SECTEURS`), **pas** dans `crop_detectors.py` — défaut réel, à corriger là où il vit. |
| 2026-08-28 | ✅ **D8 et D9 tranchés par le PO.** C2 sort du critère et reste au journal. C1 posait **deux** questions sous un seul seuil : `ampute` (perd-on des pixels ? région retenue, seuil **0**) et `marge_promise_ok` (le `COIN_MARGIN` est-il tenu ? cadre, 0,02) sont désormais séparées. Un crop complet mais serré n'est plus compté comme cassé. |
| 2026-08-28 | ✅ **Le plafond redevient un plafond** : `gold_replay` passe de 100 % à 0 % d'amputation. Et la perte du format se déplace là où elle est réelle — **BIoU 0,257 à `b/a` = 0,90**. Aucune méthode ne peut faire mieux sur une pièce oblique tant que la sortie est un cercle (ADR-017). S4 doit se lire avec ce plafond sous les yeux. |
| 2026-08-28 | 🔴 **Trou de sauvegarde, hors chantier : le bucket `eval-corpus` n'est pas miroité.** `MIRROR_BUCKETS` (`infra/backup/eurio-backup.sh:74`) liste `enrichment-crops enrichment-raws numista-canonical model-artifacts eurio-db` — pas `eval-corpus`, créé le 2026-08-26 et qui porte le corpus d'éval de `juge-et-banc` (le jeu qui a tranché ArcFace ↔ DINO). `LOT0-REPLICATION.md` avait pourtant identifié le piège et choisi `model-artifacts` pour l'éviter. **À corriger là où il vit.** |
| 2026-08-28 | ✅ **L'or persiste dans le canonique.** Migration `0019` (`crop_gold_versions` + `crop_gold_annotations`), `store/crop_gold.py`, `POST/PUT /crop-gold/…`, et l'outil d'annotation pousse à chaque validation. **RE-5 devient exécutable** : une version gelée refuse l'écriture (409), et le `sha256` du gel est calculé par le serveur. 38 tests, **14 mutations jouées, 14 rouges**. Suite 2 670 → 2 701. |
| 2026-08-28 | ✅ **Bout en bout vérifié en local** (serveur d'annotation → route → relecture SQL) : envoyé `a = 394,6 / b = 401,4` (axes inversés exprès), relu en base `a = 401,4 / b = 394,6`, `theta` +90°. Le serveur ne croit pas le client sur parole — même leçon que L1, où `before_r` valait 102,6 alors que le client envoyait 200. |
| 2026-08-28 | ⚠️ **Sans `EURIO_API_URL`, l'outil le DIT** — au démarrage et à chaque écriture, et l'écran passe au rouge « disque seul ». Un dispositif qui a l'air de marcher sans sauvegarder est le défaut qu'on corrige : `denom-gold` écrit son verdict humain dans `ml/state/denom_bench/human_validation.jsonl`, invisible du front hébergé et hors sauvegarde. |
| 2026-08-28 | ✅ **Déployé.** Migration `0019` appliquée au boot, les 4 routes `/crop-gold/*` à l'OpenAPI, testées avec un vrai PAT contre la prod. **Le garde-fou des demi-axes a fonctionné EN PRODUCTION** : envoyé `a=394,6 b=401,4 θ=21,5`, relu en base `a=401,4 b=394,6 θ=111,5`. Le gel testé aussi : 409 avec le motif complet. *(La version de fumée a été supprimée — c'était une fausse annotation, elle aurait pollué le jeu, même leçon qu'à L1.)* |
| 2026-08-28 | ✅ **Le correctif `eval-corpus` vérifié EN PRODUCTION**, pas seulement en test : après miroir du bucket, `[3] image_assets ↔ eval-corpus : aucun dangling — 260 références résolues, 0 orphelin`. Et `enrichment-crops` passe de « 20 370 références dont 260 introuvables » à **20 110 résolues, 0 dangling** — c'est exactement ce que le résolveur sépare. ⚠️ Un rouge subsiste, `[2] migrations ≡ dépôt : 0019 non appliquée` : le staging date de 02:02, avant la migration. Il se résout au prochain passage nocturne. |
| 2026-08-28 | 🔴 **Première séance d'annotation cassée par Cloudflare.** L'outil poussait avec l'UA par défaut d'urllib → **403 « error code: 1010 »**, affiché « disque seul ». Mon essai en `curl` était passé — l'UA différait, donc la vérification ne couvrait pas le chemin réel. Corrigé (`User-Agent: eurio-gold-annotate/1.0`, même convention que `client/http.py`) et verrouillé par mutation. |
| 2026-08-28 | 🔴 **L'interface n'était pas compréhensible** — le PO : « j'avoue ne pas comprendre l'interface ». Ajouté : la consigne en tête (« fais coïncider l'ellipse avec le bord extérieur »), la légende des trois poignées, l'état de l'image (à faire / validée / indécidable), un message d'erreur qui explique au lieu d'afficher un code, et **4 loupes ×4 aux points cardinaux** — à l'échelle où la pièce tient à l'écran, 2 % du rayon font 4 pixels, la question « suis-je sur le bord ? » n'était pas répondable. |
| 2026-08-28 | 🔴 **La reprise sautait une image touchée mais non validée.** `findIndex(!annotations[id])` : confirmer une strate crée une entrée, donc la reprise ouvrait l'image SUIVANTE, sans un mot. Vécu sur l'image 1. La reprise cherche désormais la première image sans ellipse **et** sans « indécidable ». |
| 2026-08-28 | ✅ **Écriture prouvée de bout en bout, deux fois** : par l'API (`GET /crop-gold/SMOKE-UI`) et par lecture DIRECTE d'`eurio.db` sur le VPS. `a=167,7 b=164,6 θ=120,8 strate=S2_capsule 24,5 s`. *(Version de fumée supprimée ; `v1` reste vierge pour la vraie séance.)* |
