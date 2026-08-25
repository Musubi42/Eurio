# Le corpus de scan doit survivre à la machine qui le produit

> Écrit le 2026-08-20. **Révisé le 2026-08-25** : le compte était faux d'un
> facteur ~4,6 (§1), et le corpus est désormais **répliqué sur MinIO** (§2). Ce
> doc pose un problème soulevé par le PO — « des photos sur device j'en ai déjà
> fait énormément, si tu me dis qu'il y en a 0 c'est qu'on les a perdues » — et
> le corrige sur un point : **elles ne sont pas perdues, elles sont non
> protégées.**
>
> 🟢 **Ce qui a changé le 2026-08-25** : le chemin de durabilité de §3 a été
> emprunté. Les arbres device sont dans `model-artifacts` (3 objets, 130,2 Mo),
> donc dans `MIRROR_BUCKETS`, donc dans la chaîne de sauvegarde. La règle de §4
> tient toujours pour les captures **futures**.
>
> Voisins : [`corpus-spec.md`](corpus-spec.md) (le store),
> [`../scan-sans-retrain/PROTOCOLE-CAPTURE.md`](../scan-sans-retrain/PROTOCOLE-CAPTURE.md)
> (le plan de prise de vue), [`../backup-pipeline/`](../backup-pipeline/) (la
> chaîne de sauvegarde existante).

## 1. Ce qui existe réellement — recompté le 2026-08-25

> 🔴 **Le chiffre de 2 264 images device de la version du 2026-08-20 était
> faux.** Il additionnait les originaux caméra, les crops qu'on en dérive, les
> frames annotées de debug et les diffs de portage, sur **deux arbres dont l'un
> duplique l'autre intégralement**. Le matériau irremplaçable — une frame que
> personne ne peut refabriquer — est **4,6 fois plus petit**.

### Le compte qui fait foi : 492 frames caméra originales uniques

```bash
find debug_pull app-android/debug_pull -name '*_raw.jpg' -type f | wc -l
# 860        ← fichiers sur les deux arbres

find debug_pull app-android/debug_pull -name '*_raw.jpg' -type f \
  -exec shasum -a 256 {} \; | awk '{print $1}' | sort -u | wc -l
# 492        ← hachés DISTINCTS : le vrai matériau
```

**860 fichiers → 492 originaux uniques.** 43 % de redondance, et elle a une
cause unique et mesurée : `app-android/debug_pull/` **n'a aucun contenu propre**.

```bash
ha=$(find debug_pull             -type f -exec shasum -a 256 {} \; | awk '{print $1}' | sort -u)
hb=$(find app-android/debug_pull -type f -exec shasum -a 256 {} \; | awk '{print $1}' | sort -u)
echo "racine=$(echo "$ha"|wc -l) android=$(echo "$hb"|wc -l) \
communs=$(comm -12 <(echo "$ha") <(echo "$hb")|wc -l) \
android_seul=$(comm -13 <(echo "$ha") <(echo "$hb")|wc -l)"
# racine=2184 android=857 communs=857 android_seul=0
```

**857 hachés côté `app-android/`, 857 déjà sous la racine, zéro contenu propre.**
26 Mo pour zéro information — c'est pourquoi cet arbre est **exclu** de la
publication MinIO (§2).

### Sur ces 492, 451 sont le corpus d'évaluation

Le `capture_id` de `scan_corpus` est `sha256(raw_bytes)[:16]` : le corpus est
donc **joignable au disque par le contenu**, sans faire confiance à un compte.

```bash
find debug_pull app-android/debug_pull -name '*_raw.jpg' -type f \
  -exec shasum -a 256 {} \; | awk '{print substr($1,1,16)}' | sort -u > /tmp/raw16.txt
sqlite3 "file:ml/state/scan_corpus.db?mode=ro" \
  "SELECT capture_id FROM scan_corpus;" | sort -u > /tmp/cap.txt
echo "raws uniques : $(wc -l < /tmp/raw16.txt)"        # 492
echo "captures     : $(wc -l < /tmp/cap.txt)"          # 451
comm -12 /tmp/raw16.txt /tmp/cap.txt | wc -l           # 451  ← toutes retrouvées
comm -23 /tmp/raw16.txt /tmp/cap.txt | wc -l           #  41  ← hors corpus
```

| | |
|---|---:|
| frames caméra originales uniques sur le Mac | **492** |
| dont **importées** dans `scan_corpus` (les deux protocoles, cf. `juge-et-banc/LOT1-IMPORT.md`) | **451** |
| dont **hors corpus** | **41** |

⚠️ `sqlite3 -readonly` **sans** `mode=ro` échoue sur cette base en `error 14`
(WAL sans `-shm`), et `immutable=1` sous-compterait si l'API `:8042` écrit —
cf. le catalogue de la skill `eurio-verify`.

Les 41 orphelins ne sont pas dispersés : ils vivent **tous** dans les deux pulls
du 2026-05-29, jamais importés.

```bash
comm -23 /tmp/raw16.txt /tmp/cap.txt > /tmp/orphans.txt
find debug_pull app-android/debug_pull -name '*_raw.jpg' -type f -exec shasum -a 256 {} \; \
  | awk '{h=substr($1,1,16); p=$0; sub(/^[0-9a-f]*  /,"",p); print h"\t"p}' > /tmp/raw_hp.tsv
grep -F -f /tmp/orphans.txt /tmp/raw_hp.tsv | cut -f2 | grep -c '20260529'
# 71 sur 71 lignes orphelines
```

### Ce qu'elles valent, et ce qui leur manque

| Jeu | Volume | Labellisé ? | Conditions tracées ? |
|---|---:|---|---|
| `scan_corpus.db` | **451 captures / 20 `eurio_id`** | oui (`eurio_id` remappé, manifeste committé) | **oui** (`condition` + `bundle_source`) |
| originaux hors corpus (pulls du 2026-05-29) | **41 frames** | par dossier de classe, non importées | non |
| `ml/datasets/eval_real_norm` | 114 img / 19 classes | oui (par dossier) | par nom de fichier |

⚠️ **Le paragraphe « les 2 150 frames de `debug_pull` sont le gisement
intéressant » est retiré : il portait sur dix fois plus de matière qu'il n'en
existe.** Le gisement non versionné réel est de **41 frames**, et l'arbitrage
« annoter ou archiver brut » ne vaut plus le débat qu'il ouvrait.

## 2. Le vrai problème — ✅ réglé le 2026-08-25 pour l'existant

### Ce qui était vrai le 2026-08-20, et qui l'était encore le matin du 25

```bash
git check-ignore -v ml/datasets/eval_real_norm debug_pull
# .gitignore:54   ml/datasets/*    ml/datasets/eval_real_norm
# .gitignore:221  debug_pull/      debug_pull
```

Les deux sont **gitignorés** — à raison, ce sont des données binaires. Mais ils
n'étaient sur aucun MinIO, donc hors de la chaîne de sauvegarde du VPS, donc
détruits par un `git clean -xdf`. **La seule copie était le disque de ce
portable.**

### 🟢 Ce qui a changé : trois arbres publiés dans `model-artifacts`

Le chemin de §3 a été emprunté tel quel — `ml/scripts/training_assets.py`
(ADR-004), arbre → archive déterministe → bucket, identité par `tree_digest` sur
le **contenu**, manifeste committé.

```bash
python3 -c "
import json; d=json.load(open('shared/training-assets.json'))
print('bucket:', d['bucket'], '| generated_at:', d['generated_at'])
for a in d['assets']: print(' ', a['name'], a['n_files'], a['content_size'])"
# bucket: model-artifacts | generated_at: 2026-08-25T13:27:42+00:00
#   detection_dataset      7580 47500604
#   coin_detector_weights     1  6221866
#   device_debug_pull      2968 76330291
#   eval_real_norm          114  2367074
#   scan_corpus_frames      902 53271495
```

Et côté bucket, les objets existent réellement (listés le 2026-08-25) :

| Objet | Taille |
|---|---:|
| `training/device_debug_pull/83f103e0074a/device_debug_pull.tar.gz` | 74 676 028 o |
| `training/eval_real_norm/697e80ca36c0/eval_real_norm.tar.gz` | 2 302 211 o |
| `training/scan_corpus_frames/287fc454e403/scan_corpus_frames.tar.gz` | 53 267 445 o |
| **total corpus device** | **130 245 684 o — 130,2 Mo** |

**Trois objets, ~130 Mo.** `app-android/debug_pull/` est délibérément **exclu**
(zéro contenu propre, §1).

### Pourquoi `model-artifacts` et pas un bucket neuf

```bash
sed -n 74p infra/backup/eurio-backup.sh
# MIRROR_BUCKETS=(${EURIO_BACKUP_BUCKETS-enrichment-crops enrichment-raws \
#                  numista-canonical model-artifacts eurio-db})
```

Cette liste est **en dur**. Un bucket neuf serait hors miroir, donc hors des
5 anneaux, et **cet oubli serait muet** : le corpus paraîtrait sauvegardé sans
l'être. Publier dans `model-artifacts` hérite de la chaîne sans toucher au
script.

### ⚠️ Ce qui n'est PAS établi

- **Que la sauvegarde ait effectivement repris ces 130 Mo.** `go-task
  backup:verify` ne tourne que sur le VPS ; la lecture de `MIRROR_BUCKETS` dans
  le source prouve l'**intention**, pas l'exécution. À vérifier au prochain
  passage sur le VPS — sinon on aura l'illusion de la sauvegarde sans sa preuve,
  exactement le silence que ce document combat.
- **L'aller-retour depuis une autre machine.** `go-task
  ml:training-assets:fetch` n'a pas été rejoué depuis le PC : la publication est
  vérifiée, la restauration ne l'est pas.
- **Le corpus device du PC.** L'`eval_real_norm/` publié ici est celui du Mac
  (114 fichiers, pull du 2026-04-29). Celui qui a servi au run 317/16 est un
  **autre contenu**, sur la machine `desktop`, et il n'est **toujours pas
  répliqué**.

### Ce qui reste non protégé

Les **captures futures**. Rien dans le geste de capture ne pousse
automatiquement vers MinIO : la publication du 2026-08-25 est un geste manuel,
rejoué à la main. La règle de §4 reste donc entièrement à câbler.

## 3. Ce que le projet sait déjà faire, et qu'il suffit de brancher

Rien n'est à inventer. Trois mécanismes existent :

1. **MinIO** (`eurio-s3.musubi.dev`) est déjà le domicile des images du projet —
   raws, crops, canoniques, artefacts de modèle. Un bucket de plus n'est pas un
   chantier.
2. **Le patron `ml:assets:publish` / `ml:assets:fetch`** : publier au bucket,
   épingler les sha256 dans un manifeste committé (`shared/model-assets.json`),
   re-télécharger au besoin. C'est exactement la forme dont un corpus a besoin —
   **les octets dehors, l'inventaire vérifiable dans git.**
3. **La chaîne de sauvegarde du VPS** (chantier `backup-pipeline`, lots 0 à 5
   livrés) couvre déjà MinIO. Un corpus **dans** MinIO hérite de la sauvegarde ;
   un corpus sur le Mac n'héritera jamais de rien.

C'est le point qui rend ce chantier petit : **il n'y a pas de sauvegarde
Mac à construire. Il y a un chemin à emprunter — MinIO — et la sauvegarde suit.**

## 4. La règle à graver

> **Une capture qui n'est pas dans MinIO n'existe pas.**

Corollaire de conception : l'upload doit être **dans le geste de capture**, pas
une étape « à faire plus tard ». Une étape séparée sera oubliée un soir de
fatigue, précisément après la session la plus longue.

## 5. Les questions à trancher dans la session dédiée

- **Le point d'upload.** Au moment de l'import du bundle cohort-test dans
  `scan_corpus` (une seule porte, facile à verrouiller), ou directement depuis
  le téléphone (plus robuste à la perte du Mac, mais nouveau chemin réseau à
  écrire côté Android) ?
- **Le manifeste.** Committer un inventaire `capture_id → sha256 → clé MinIO`
  sur le patron de `model-assets.json` ? Ça donne une vérification d'intégrité
  et un moyen de reconstituer le corpus sur une autre machine. Le
  `capture_id` est déjà `sha256(raw_bytes)[:16]` — le contenu est donc **déjà
  adressable par son hash**, la moitié du travail est faite.
- **Le sort des 41 orphelins.** ⚠️ **Question redimensionnée le 2026-08-25** :
  elle portait sur « 2 150 frames non labellisées », il y en a **41** (§1), et
  elles sont **déjà rangées par dossier de classe** dans les deux pulls du
  2026-05-29. Les importer est un `go-task ml:scan-corpus:import-pull
  --bundle-source device_pull_20260529`, pas une campagne d'annotation. Reste à
  décider si un troisième protocole dans le même corpus se justifie — la
  collision de noms d'étape entre protocoles est réelle et mesurée
  (`juge-et-banc/LOT1-IMPORT.md` §3).
- **Le sort de `eval_real_norm`.** 114 images labellisées par classe : à verser
  au corpus avec `condition` inconnue, ou à re-capturer proprement ? Elles ont
  servi de jeu d'éval historique (les « 317 snaps » cités dans `VISION.md`
  désignent un comptage antérieur, non reproduit ici — écart non expliqué).
- **La rétention.** Un corpus est append-only et ne se purge pas. Vérifier que
  la politique de cycle de vie MinIO ne s'appliquera pas à ce bucket.

## 6. Ce que ça change pour le plan de capture

Le [`PROTOCOLE-CAPTURE.md`](../scan-sans-retrain/PROTOCOLE-CAPTURE.md) prévoit
**985 captures sur 80 classes en 11 sessions**. Deux conséquences :

- **Ne pas lancer la campagne avant que le chemin de durabilité existe.** Le
  contrôle bloquant du protocole (`sampled=False`, 400 tests, 80 classes) doit
  gagner une quatrième ligne : *les captures de la session précédente sont-elles
  dans MinIO ?*
- **La première session sert aussi à tester le chemin.** Trois sessions
  (~290 captures) donnent déjà un signal et attrapent une erreur de protocole
  tant qu'elle est réparable — c'est aussi le bon moment pour vérifier que
  l'aller-retour MinIO fonctionne, sur 96 images plutôt que sur 985.

## 7. Une correction à porter ailleurs

J'ai écrit et répété que le corpus de scan valait « 0 photo », puis « 2 264
images device ». **Les deux sont faux**, dans des directions opposées :

| Formulation | Statut |
|---|---|
| « 0 photo » | vrai du store versionné (à l'époque), faux de la matière |
| « 2 264 images device » | **faux** — additionne dérivés, doublons et deux arbres dont l'un duplique l'autre |
| **« 492 frames caméra originales uniques, dont 451 versionnées dans `scan_corpus` »** | ✅ la formulation juste, mesurée le 2026-08-25 (§1) |

À corriger dans [`../scan-sans-retrain/PREREQUIS.md`](../scan-sans-retrain/PREREQUIS.md)
§P5 et dans [`../juge-et-banc/PROBLEME.md`](../juge-et-banc/PROBLEME.md) §6 —
les deux citent encore le 2 264 — lors de la prochaine passe de doc.
