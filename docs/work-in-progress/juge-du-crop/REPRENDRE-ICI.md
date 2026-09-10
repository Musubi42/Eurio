# Reprendre ici — chantier `juge-du-crop`

> **À lire en premier dans une nouvelle session.** Ce fichier dit où on en est,
> ce qui est fait, et le geste exact qui reste. Les décisions sont dans
> [`DECISIONS.md`](./DECISIONS.md), l'historique dans [`SUIVI.md`](./SUIVI.md),
> le plan d'ensemble dans [`PLAN.md`](./PLAN.md).

## En une phrase

Sept chantiers « crop » ont chacun atteint leur cible sur leur **propre** oracle
et produit des crops que la review humaine jette. Celui-ci construit d'abord la
**vérité terrain** (60 ellipses tracées à la main), *puis* le juge — et il
s'arrête si le juge ne prédit pas le verdict humain (RE-4).

## ⚠️ La séance se tient sur **v2** depuis le 2026-09-10

> **https://eurio-admin.musubi.dev/gold-crop/annoter?version=v2** — le
> `?version=v2` n'est **pas** optionnel : la page vaut `v1` par défaut.

v1 tirait 9 rejets sur 28 qui étaient des **mauvaises faces** au cadrage
impeccable — un verdict qu'aucun juge du crop ne peut prédire, donc RE-4 faussé
(la réserve était contaminée pareil). Détail, mesures et coût :
[D13](./DECISIONS.md#d13). v1 n'était pas gelée et ne portait que 2 annotations,
sur deux images que v2 reprend à l'identique : **les 2 ellipses sont à
retracer**, rien d'autre n'est perdu (51 des 60 images sont les mêmes).

## ⏱️ État au 2026-09-11 — la passe 1 est jouée, RE-4 préliminaire dit « à l'envers »

Les 60 annotations de v2 sont dans le canonique (2026-09-10). **16 indécidables, tous des rejets** (D14) ; 44 utilisables, 32 accept / 12 reject. RE-4 préliminaire, sans gel : le juge `amputation_rate` **sépare à l'envers** (90 % des acceptés « amputés ») ; la géométrie (BIoU, IoU masque) sépare fort. Proposition D15 : juge amendé en IoU de masque ≥ τ, τ validé sur la réserve. **Trois gestes PO** : les trois clics D14 (44, 45, 59 → indécidable), la passe 2, la réserve (dès que `?role=reserve` est déployé). Le gel attend ces trois gestes.

## ⏱️ État au 2026-09-08 (historique)

| lot | état |
|---|---|
| **L1** — le recadrage manuel devient une mesure | ✅ déployé (27/08) — mais **0 ligne collectée** : aucune review humaine n'a eu lieu depuis le 27/08 01:42 UTC, *avant* le déploiement. L'instrument n'a jamais rien vu passer |
| **L2** — jeu d'or : tirage, outil, persistance | ✅ livré et déployé (28/08) |
| **L2.3** — **la séance d'annotation du PO** | 🔴 **À L'ARRÊT — 2 images sur 60**, inchangé depuis le 29/08 08:54 UTC |
| **L3.1/L3.2** — juge + harness | ✅ écrits, testés, **re-vérifiés le 08/09** sur les 2 annotations réelles (le banc tourne, RE-4 répond « impossible : un groupe vide » — c'est le bon verdict) |
| **L3.2bis** — le banc lit le canonique (`fetch`, `geler`) | ✅ écrit et testé le 08/09 (25 tests, 7 mutations rouges), smoke lecture seule contre la prod |
| **L3.3 — RE-4, le point d'arrêt** | 🔴 attend l'or |
| **L4/L5** — bornes, méthodes candidates | 🔴 |

**Le chemin critique passe par une seule chose : les 58 images restantes.**
Tout le code est prêt et vérifié ; rien de ce qui reste n'est du code. Deux
gestes humains, et eux seuls, font avancer le chantier : **la séance
d'annotation** (L2.3) et **une séance de review** (sans elle, L1 reste une
table vide et la question de D6 — la prod sur-crope-t-elle ou sous-crope-t-elle ?
— reste sans réponse ; la file porte 9 715 items `open`).

## Ce que le PO doit faire, exactement

**Depuis n'importe quel navigateur, sans terminal** (D12, déployé le 2026-09-08) :

> **https://eurio-admin.musubi.dev/gold-crop/annoter?version=v2**

La page reprend à la première image sans ellipse. Le geste, par image : traîner
l'ellipse jaune sur le **bord extérieur de la pièce** (le listel, pas l'anneau
aux étoiles), confirmer la famille avec <kbd>1</kbd>…<kbd>4</kbd>, puis
<kbd>Entrée</kbd>. Les 4 vignettes du bas montrent ce bord de près : si le trait
y colle au métal, c'est bon. Pendant la séance, la ligne **écrit** du panneau
doit rester **verte** (`canonique · N`) — si elle passe au rouge, la phrase dit
pourquoi ; rien n'est perdu tant qu'on ne quitte pas l'image.

L'avancement se lit sur **`/gold-crop`** (n / 60, dernière écriture), qui porte
aussi le bouton d'entrée.

<details>
<summary>Le repli : l'outil local (même route, même table, <code>editor_version</code> distinct)</summary>

```bash
cd ~/Documents/Musubi42/bizz/EurioProject/Eurio/ml
python -m bench.gold_crop.annotate.serve --out state/gold_crop/v1
# puis http://127.0.0.1:8765
```

Au démarrage, la console doit dire
`canonique : https://eurio-api.musubi.dev/crop-gold/v1/annotations`. Si elle
dit `🔴 EURIO_API_URL / EURIO_API_TOKEN absents`, **s'arrêter** : le devShell
n'est pas chargé, et l'or n'irait que sur disque.

</details>

**Puis, à ≥ 24 h d'écart**, la seconde passe :
**https://eurio-admin.musubi.dev/gold-crop/annoter?version=v2&passe=2** (le lien apparaît
sur `/gold-crop` dès que la passe 1 est complète). En repli :
`python -m bench.gold_crop.annotate.serve --out state/gold_crop/v1 --passe 2 --n-double 10`.

10 images seulement, re-annotées. Elle fixe le **plafond du banc** : aucune
méthode ne peut être créditée au-dessus du bruit de la main qui a fait l'or.

## Les quatre familles (« strates »), et pourquoi on les confirme

Les 60 images ont été tirées **15 par famille**, pour qu'une méthode qui marche
sur les photos faciles et rate les pièces de biais ne puisse pas se cacher
derrière une moyenne.

| | ce que c'est |
|---|---|
| **S1 facile** | une seule pièce, nette, quasi de face, fond simple |
| **S2 capsule** | sous plastique — blister, coffret, slab gradé. Reflets, halo |
| **S3 multi** | plusieurs pièces dans l'image, ou un lot, ou un coffret |
| **S4 oblique** | la pièce est nettement de biais, elle paraît ovale |

⚠️ **Le tirage s'est fait sur le TEXTE de l'annonce, qui ment.** Le mot
« capsule » n'apparaît que 3 fois dans tout le parc ; S2 se devine par
`proof` / `blister` / `PCGS` / `belle épreuve`. D'où des erreurs visibles à
l'œil : la planche de contrôle du tirage montre des capsules classées
`S1_facile` et des raws à deux pièces en `S4_oblique`. **C'est la confirmation
humaine, image par image, qui rend la stratification honnête** — et c'est le
seul geste du protocole qu'aucun code ne peut faire.

## Le chrono de l'outil — ce qu'il est, ce qu'il n'est pas

Le panneau affiche une médiane de secondes par image. **Ce n'est pas une
pression sur l'annotateur** : c'est un signal pour le développeur. Une famille
où la médiane s'envole est une famille où la proposition de départ
(`measure_tilt`) est mauvaise — donc une information sur le pré-remplissage, pas
sur la main. Rien à faire côté PO.

*(La première image a pris 804 s : c'est le temps d'apprendre l'outil, pas un
signal. On lira les médianes une fois la séance finie.)*

## Où vit l'or, et ce qui le protège

* **`eurio.db` sur le VPS**, tables `crop_gold_versions` et
  `crop_gold_annotations` (migration `0019`). Une table et pas un bucket :
  `MIRROR_BUCKETS` est une liste en dur, et `eval-corpus` y a manqué deux jours
  sans que rien ne le dise ([D11](./DECISIONS.md)) ;
* **le gel tient RE-5** : tant que `frozen_at` est NULL la version s'annote ;
  une fois gelée elle refuse l'écriture (**409**) et son instantané part dans
  `model-artifacts`, bucket déjà miroité. Le `sha256` est calculé par le
  **serveur** — un gel dont le client fournit l'empreinte n'atteste rien ;
* le fichier `ml/state/gold_crop/v1/gold.json` est un **filet**, pas la source
  de vérité : si le réseau tousse, l'annotation est déjà sur disque et le renvoi
  suivant la rattrape (la route est idempotente).

Lire l'or à tout moment :

```bash
curl -s -H "Authorization: Bearer $EURIO_API_TOKEN" "$EURIO_API_URL/crop-gold/v1"
```

…ou à l'œil : **front admin → Outils → « Jeu d'or du crop »** (`/gold-crop`).
Elle n'est pas `heavy` : elle lit le canonique et des URLs présignées, donc elle
marche aussi depuis le front hébergé.

## Ce qui se passe quand la séance est finie

1. **Geler la `v1`** — `cd ml && python -m bench.gold_crop.geler --version v1`.
   Il refuse tant que la passe 1 n'a pas 60 annotations (`--force` pour passer
   outre, et le dire au journal), gèle, relit l'instantané, **re-calcule son
   empreinte et la compare au `snapshot_sha256` du serveur**, puis le publie
   dans `model-artifacts` ;
2. **Rapatrier l'or gelé** — `python -m bench.gold_crop.fetch --out state/gold_crop/v1`
   (sur la machine du banc, qui peut être le PC : `fetch` complète `sample`,
   il n'apporte que les annotations). Sur une version gelée il re-vérifie
   l'empreinte et échoue bruyamment si elle diverge — c'est RE-5 tenu par
   l'outil, pas par la confiance. Il refuse d'écraser un `gold.json` local
   qui porterait des annotations absentes du canonique (un envoi raté) ;
3. **Exécuter RE-4** — `python -m bench.gold_crop.harness --out state/gold_crop/v1`.
   Il publie la corrélation entre `amputation_rate(baseline_prod)` et le verdict
   humain sur les 60. **Si le juge ne sépare pas les acceptés des rejetés, le
   juge est faux et le banc s'arrête là** — c'est tout l'intérêt du dispositif.
   Test de référence : `quality_score` y échoue à 0,0008 près ;
4. seulement ensuite : L4 (bornes) puis L5 (méthodes candidates).

## Les pièges de cette phase, appris à la dure

| piège | ce qu'il fait |
|---|---|
| **Cloudflare refuse l'UA par défaut d'urllib** | 403 « error code: 1010 », une page HTML au lieu de JSON. `curl` passe, l'outil non : la panne ne se voit QUE dans l'outil. Tout client Python du canonique doit poser un `User-Agent` |
| **une session de test écrit dans le même `gold.json`** | arrivé le 28/08 : une annotation d'essai a fui dans le jeu du PO puis dans le canonique. Toujours utiliser `--version SMOKE-…` pour un essai, jamais `v1` |
| **la reprise se fait sur « annotée », pas sur « touchée »** | confirmer une strate crée une entrée ; reprendre après elle sauterait l'image, en silence. Corrigé, mais c'est le genre de chose à re-vérifier |
| **`gold_replay` doit être à 0 % d'amputation, hors images tronquées par le bord** | s'il est à 100 %, le seuil est mal posé (c'était le cas avant [D9](./DECISIONS.md)). À 9,1 % sur v2 : 4 pièces touchent le bord du raw, `C1_cadre_tronque`, irrécupérables par toute méthode ([D15](./DECISIONS.md)) |
| **C2 est inerte** | `arc_coverage` = 1,000 jusqu'à 25 % d'amputation. Journalisée, hors du critère ([D8](./DECISIONS.md)). Ne pas la ré-armer sans amendement |

## Ce qui attend encore le PO

* **Signer les seuils (RE-1)** — `m = 0` pour l'amputation, `arc ≥ 11/12` pour
  C2 (hors critère), `d = 0,08·a` **mesuré et confirmé** ([D4](./DECISIONS.md)).
  Ils sont appliqués par défaut ; la signature reste à poser avant le premier
  bras candidat ;
* **la planche comparative** (`/gold-crop/planche`, écrite le 2026-09-08) est
  **`heavy`** : elle lit les `run_*.json` du harness sur la machine qui l'a
  lancé, via le ML local `:8042`. Elle montre par image l'or contre le cercle
  de chaque bras, les bornes hors classement, RE-7 (écart < 5 points = non
  départagé) et le bloc RE-4 verbatim. Vide tant que le harness n'a pas tourné.
