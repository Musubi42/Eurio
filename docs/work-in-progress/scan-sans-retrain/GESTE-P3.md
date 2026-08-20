# Geste P3 — relancer les 12 454 prédictions DINO

> Une page pour lancer le backfill sans se poser de question. Écrit le
> 2026-08-20, après vérification du chemin de base et exécution réelle du point
> d'entrée sur une copie `/tmp` (jamais sur le canonique).
>
> Contexte : [`PREREQUIS.md`](PREREQUIS.md) §P3 · Dette :
> [`FINDINGS.md`](FINDINGS.md) §8 · Motif du défaut corrigé :
> [`FINDINGS.md`](FINDINGS.md) §8.7.
>
> **État au 2026-08-20 (clôture) : le geste a ABOUTI, et il a été refait une
> seconde fois.** Dernière exécution contre la banque à plancher (build
> `365dcab2a253`, **1495 ancres**) : **12 454 prédictions, 0 erreur, 0 périmée**,
> poussées au canonique de `14:28:14` à `15:09:34` UTC. Preuve retenue :
> `calibration_blockers(..., '2eur_all', 'dinov2-vitl14')` → `[]`.
>
> ⚠️ **Le témoin de banque a changé de valeur : c'est 1495, plus 1533.** Il vaut
> exactement le `count` du `.npz` servi — ne le fige pas de tête, relis-le
> (§« Ce que tu verras pendant », ligne 2).
>
> 🔴 **Et ne recopie pas la requête de complétude `computed_at < built_at`** de
> ce document : elle compare deux formats de date **en chaînes** et rend `12454`
> sur une base parfaitement saine. Le seul contrôle qui fait foi est
> `calibration_blockers`.

## Pourquoi maintenant

La banque a été rebâtie le 2026-08-19 à 16:36 (build `23c637d93b43`, 671
classes, **1533 ancres**), puis **de nouveau le 2026-08-20 à 14:27** avec le
plancher `min_exemplars=2` (build `365dcab2a253`, 671 classes, **1495 ancres**,
124 classes à exemplaires — ⚠️ *ce plancher a été retiré du code le soir même,
défaut revenu à 1 : la banque servie le porte, un rebuild ne le porterait
plus*). *Le raisonnement ci-dessous vaut pour tout rebuild ;
seuls les nombres changent.* Les 12 454 prédictions `2eur_all` sont donc toutes
antérieures au build courant : elles rattachent les crops à une banque qui
n'existe plus. Tant qu'elles ne sont pas recalculées, **toute mesure de
précision top-1 est fausse dans les deux sens**.

## La commande

```bash
cd ml
./.venv/bin/python -m scripts.backfill_dino_predictions --kind 2eur_all --force --verbose
```

- **Ne pas passer `--db`** : sous `--push` (actif par défaut dans le devShell)
  le fichier n'est jamais ouvert — le script pull une réplique scratch neuve du
  canonique. Il émet désormais un avertissement si on lui en passe un.
- **Ne pas passer `--no-push`** : ce serait le seul cas où le chemin local est
  ouvert, et rien ne remonterait au canonique.
- `--force` est indispensable : sans lui, les 12 454 prédictions existantes
  seraient toutes comptées « Skipped (existing) » et rien ne serait recalculé.

## Vérifier AVANT de lancer (30 secondes)

**1. La sync est active** — sinon le script ouvre la base locale et échoue :

```bash
echo "API=$EURIO_API_URL"
# attendu : API=https://eurio-api.musubi.dev
```

Si cette variable est vide (shell hors direnv), `push=False`, le script ouvre
`state/eurio.replica.db` et le premier `INSERT INTO source_runs` échoue en
`sqlite3.OperationalError: attempt to write a readonly database`, **avant tout
calcul**. Bruyant, pas de demi-corpus possible — mais autant ne pas y aller.

**2. Le chemin de base par défaut est le bon** :

```bash
./.venv/bin/python -c "import scripts.backfill_dino_predictions as m; print(m.DB_PATH)"
# attendu : .../ml/state/eurio.replica.db      (jamais .../state/eurio.db)
```

C'est le défaut qui a coûté la journée du 19 : la banque avait été bâtie
pendant des semaines sur `state/eurio.db`, **6205 assets au lieu de 12454**.

**3. La banque servie est bien la neuve** :

```bash
./.venv/bin/python -c "
import numpy as np; d=np.load('state/foundation_anchors_2eur_all.npz')
print(d['matrix'].shape)"
# attendu aujourd'hui : (1495, 1024)   — le build 365dcab2a253 du 2026-08-20 14:27.
#   1533 = la banque d'avant le plancher ; 1250 = celle du 19 au matin.
#   Le nombre juste est TOUJOURS le `count` du .npz servi — relis-le, ne le fige pas.
```

## Ce que tu verras pendant, dans l'ordre

| # | Ligne attendue | Ce qu'elle prouve · quoi faire sinon |
|---|---|---|
| 1 | `[model-b] réplique scratch → /var/folders/.../dino-backfill-XXXX/dino_scratch.db` | Le pull API complet (~106 Mo, vérifié par SHA). Pas de ligne = échec bruyant, pas un silence |
| 2 | `auto_validate: anchor bank 2eur_all loaded (1495 anchors, dim=1024, encoder=dinov2-vitl14)` | **Le count du `.npz` servi** — **1495** depuis le rebuild à plancher du 20 août 14:27. Un nombre plus ancien (1533, 1250) = la banque servie n'est pas celle qu'on croit → **arrêter** |
| 3 | `auto_validate backfill: N candidate assets in scope 2eur_all` | **N ≈ 12 454.** Si N ≈ **6 205**, le correctif de chemin n'a pas pris → **arrêter avant les 18 minutes** |
| 4 | `Predicted: ~12454` · `Skipped (existing): 0` · `Errors: 0` | `Skipped=0` est l'effet de `--force`. **Lire `Errors:` à l'œil** — voir M8 ci-dessous |
| 5 | `[model-b] push dino-backfill-<horodatage> → <n> ligne(s) appliquée(s) au canonique` | **C'est cette ligne qui rend le geste complet.** `→ déjà appliqué (no-op)` sur un premier lancement signalerait une collision de `run_id`, à investiguer |

Le témoin qui compte le plus est le **3**. C'est le seul chiffre qui distingue
une base saine d'une base périmée, et il coûte zéro à lire.

## Durée

⚠️ **Estimation, non mesurée à l'échelle réelle.** Deux points mesurés sur une
copie `/tmp` : 4 assets → 5,0 s ; 60 assets → 9,7 s. Soit ~84 ms/asset après
~4,5 s de chargement du modèle (MPS), donc **≈ 18 min de calcul** pour 12 454,
**plus** le pull de la réplique scratch (~106 Mo).

L'estimation « plusieurs heures » qui traînait dans `PREREQUIS.md` supposait un
retéléchargement MinIO massif ; les 1958 crops du gold sont dans le cache local
(comptés fichier par fichier, 0 manquant), le reste ne l'est pas
nécessairement — c'est la principale source d'incertitude sur les 18 minutes.

## Vérifier APRÈS — le critère de complétude

Le geste est complet quand **zéro prédiction n'est antérieure au build
courant** :

```bash
sqlite3 "file:ml/state/eurio.replica.db?mode=ro" "
SELECT COUNT(*) FROM image_asset_dino_predictions p
  JOIN (SELECT MAX(built_at) m FROM dino_anchor_builds
         WHERE anchors_kind='2eur_all' AND encoder_version='dinov2-vitl14') b
 WHERE p.anchors_kind='2eur_all' AND p.encoder_version='dinov2-vitl14'
   AND p.computed_at < b.m;"
# attendu : 0        (aujourd'hui : 12454)
```

Et le volume total :

```bash
sqlite3 "file:ml/state/eurio.replica.db?mode=ro" \
  "SELECT COUNT(*) FROM image_asset_dino_predictions WHERE anchors_kind='2eur_all';"
# attendu : 12454
```

⚠️ **La réplique locale ne rattrape pas instantanément — et il faut la
rafraîchir soi-même avant de lire.** Direction A : le push écrit au canonique,
la réplique locale ne bouge pas toute seule. Si la requête rend encore `12454`
périmées juste après le push, ce n'est pas un échec — c'est le décalage de
réplication. **Le geste manquant** :

```bash
go-task ml:db:pull-replica          # sqlite3_rsync incrémental, ~3 s
# puis rejouer la requête de complétude ci-dessus  → attendu : 0
```

**Mesuré le 2026-08-20 au soir, et c'est la démonstration du piège** : la
requête rendait `12454 / 12454` sur une réplique dont le `mtime` était
`19 Aug 16:31` et dont le `MAX(built_at)` pour `2eur_all` valait
`2026-08-19T00:28:21+00:00` — alors que le build `23c637d93b43` porte
`2026-08-19T14:36:14+00:00`. **La réplique ne connaissait même pas le rebuild.**
Lire ce `12454` comme « le backfill a échoué » aurait relancé 18 minutes de
calcul pour rien. Contrôle systématique avant de conclure :

```bash
ls -l ml/state/eurio.replica.db
sqlite3 "file:ml/state/eurio.replica.db?mode=ro" \
  "SELECT MAX(built_at) FROM dino_anchor_builds WHERE anchors_kind='2eur_all';"
# si ce n'est pas 2026-08-19T14:36:14+00:00 ou plus récent, la réplique est
# en retard : rafraîchir AVANT de tirer une conclusion
```

Le juge de paix reste la ligne **5** de la sortie du script, et une
contre-lecture du canonique.

Corollaire attendu : `calibration_blockers` cesse d'émettre
`P3: 12454 predictions … anterieures au build courant` pour
`2eur_all/dinov2-vitl14`.

## Si ça s'arrête en route

**Le script n'est pas reprenable, et il n'a pas de point de sauvegarde
intermédiaire.** C'est mesuré par lecture du code, pas supposé :

- il pull une réplique **scratch** dans un `tempfile.mkdtemp(prefix="dino-backfill-")`
  et y écrit toutes les prédictions ;
- le `push_run(conn, run_id)` est la **toute dernière instruction**, après les
  12 454 prédictions ;
- donc **une interruption avant la ligne 5 ne pousse rien au canonique**, et le
  scratch est perdu avec le process.

**Que faire** : relancer **la même commande, à l'identique**. Elle est sûre à
relancer :

- un `run_id` neuf est fabriqué à chaque lancement
  (`dino-backfill-<ISO-timestamp>`), donc pas de collision ;
- côté canonique, `push_run` porte un `batch_sha` et répond `already_applied`
  si le même lot repasse — un double push est un no-op, pas un doublon ;
- côté données, `--force` réécrit les prédictions par `asset_id` ; il n'y a pas
  d'état partiel à nettoyer puisque rien n'a été poussé.

Le coût d'une reprise est donc **le run entier depuis zéro** (~18 min + le
pull), pas une corruption. Lancer machine libre.

**Si l'échec est un `readonly database`** : tu es hors devShell ou
`EURIO_API_URL` est vide. Lire la skill `eurio-data-writes` avant de contourner
— ne jamais « débloquer » en passant `--no-push` ou en posant un `--db`.

## Deux défauts connus sur ce chemin — aucun ne bloque

Ni l'un ni l'autre n'empêche de lancer. Les deux méritent d'être connus avant,
parce qu'ils changent ce qu'on doit regarder. Détail :
[`FINDINGS.md`](FINDINGS.md) §8.8.

- **M8 — le script sort en code 0 même avec des milliers d'erreurs.**
  `main()` se termine par un `return 0` inconditionnel ; `result.n_errors` est
  imprimé et jamais lu. Un backfill avec 3 000 erreurs sort en code 0 et
  `go-task` dit « réussi ». **Conséquence pratique : lire `Errors:` à l'œil, ne
  pas se fier au code de sortie.** Le correctif est une ligne
  (`return 1 if result.n_errors else 0`) ; il est recommandé mais non appliqué.
- **M7 — le travail `face` / `denom` est recalculé puis jeté.** Le backfill
  écrit `face` (2 997 valeurs nulles sur les 12 454 candidats) et `denom`
  (6 185) sur sa réplique scratch, mais `export_run` ne récolte pas
  `image_assets` pour un run de backfill : le batch poussé au canonique porte
  **0 ligne `image_assets`** (mesuré : `{'source_runs': 1,
  'image_asset_dino_predictions': 1}`). Sous `--push`, le scratch est un
  `mkdtemp` — ce travail disparaît avec le process. **Préexistant, pas une
  régression** ; les prédictions, elles, voyagent bien.
  ⚠️ Corollaire : le journal `auto_validate: face écrit sur N crops` annonce la
  taille du lot **soumis**, pas le nombre de lignes changées (**M9**) — ne pas
  le lire comme une preuve que quelque chose a été écrit.

## Ce que ce geste ne débloque PAS

P3 fait tomber un bloqueur de calibration, pas tous. Après P3, le banc
d'encodeurs reste bloqué par **P1 lu sur la réplique** (125 classes tant que la
réplique n'a pas rattrapé le canonique), et le premier build de banque d'un
encodeur **candidat** reste interdit — pour une raison qui a changé le
2026-08-20 :

- **M1 est fermé** : l'encodeur est entré dans la clé primaire de
  `dino_class_references` (migration **0010**), et le writer **refuse
  bruyamment** une table à l'ancienne clé au lieu d'écraser. Plus rien n'est
  détruit. ⚠️ 0010 n'est appliquée au canonique qu'au **redémarrage de
  `eurio-api`** ; d'ici là, ce build s'arrête sur un refus nommé — et par HTTP
  ce refus sort en **500 générique**, message perdu
  ([`FINDINGS.md`](FINDINGS.md) §8.10, **Q10**).
- **Mais Q6 est ouvert** : aucun **lecteur** de la table n'est scopé par
  encodeur. Une fois deux banques en base, la route admin rend 22 lignes au lieu
  de 11 avec deux canoniques pour une classe, le badge de review affiche la
  banque du candidat, et le plan de capture P5 déplace 9 classes de strate.
  Rien ne casse, tout ment.

Ordre proposé : [`PREREQUIS.md`](PREREQUIS.md) §« Où on en est sur ce graphe ».
