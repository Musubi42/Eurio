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

| lot | état |
|---|---|
| **L0** — `PROBLEME` + `JUGE` + `JEU-D-OR` + seuils signés | 🟡 docs écrits, `d = 0,08·a` **mesuré et confirmé** (28/08), **seuils toujours non signés** (D4) |
| **L1** — instrumentation du recadrage manuel | ✅ **livrée et déployée le 2026-08-27** — la collecte tourne |
| **L2** — outil d'annotation + séance PO | 🟡 **outil écrit, tirage fait (60 + 24 réserve, raws en cache)** — reste la séance du PO, ~40 min + 10 min de double passe |
| **L3** — juge implémenté + **RE-4** | 🔴 ⛔ point d'arrêt |
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
