# Auto-validation de la review — poser le problème

> Écrit le 2026-08-20, en fin de session « scan sans réentraînement ».
> **Rien n'est implémenté.** Ce doc existe pour qu'une session dédiée reprenne
> le sujet sans le redécouvrir.
>
> Contexte modèle : [`../scan-sans-retrain/`](../scan-sans-retrain/DECISION.md) ·
> Skill : `eurio-review`, `eurio-banque`.

## Le constat de départ, dans les mots du PO

> « 10 % des reviews que je fais, je valide automatiquement sans rien
> réajuster, car c'est bon. Mais 10 %, ce n'est pas beaucoup. »

Lu à l'envers : **90 % des décisions demandent un geste humain sur le crop.**

C'est la phrase la plus importante du chantier, parce qu'elle déplace le
goulot. On a passé deux jours à mesurer et améliorer l'**attribution de
classe** — DINO, les encodeurs, la banque. Or l'attribution de classe n'est pas
ce qui coûte du temps. Le cadrage l'est.

⚠️ **Cette lecture n'est pas mesurée.** Elle repose sur une phrase. La mesurer
est le geste zéro du chantier (§3).

---

## 1. Les quatre décisions, et leurs quatre remèdes

Toute décision de review est l'une de ces quatre. Elles n'ont rien en commun.

| | Décision | Ce qui l'automatise | État |
|---|---|---|---|
| **A** | accepter tel quel | seuil de confiance + planche de confirmation | partiellement fait |
| **B** | accepter après recadrage | un meilleur cropper, ou un score de qualité de crop | rien |
| **C** | rejeter (junk, carte, mauvaise pièce) | des détecteurs dédiés | partiel (face, denom) |
| **D** | reclasser (le modèle se trompe) | un meilleur encodeur / la fusion de canaux | c'est ce qu'on a travaillé |

**Le piège** : on optimise D depuis deux jours, alors que B est probablement
l'essentiel du temps humain. Un encodeur parfait ne change rien à un crop mal
cadré.

---

## 2. Ce qu'on sait déjà, mesuré

Ces chiffres sont acquis et n'ont pas à être re-mesurés.

| Fait | Valeur | Source |
|---|---|---|
| Palier d'auto-acceptation `spread ≥ 0,10` | **97,1 %** de précision | `banque-dino/CONSTAT.md`, 1952 crops |
| … et il n'est **pas** gonflé par la fuite du gold | 98,5 % hors banque / 97,4 % sur ancres | ci-dessous |
| Bande **pays** | **97,4 %** pays@1 (vs 91,6 % global@1) | `BENCH-ENCODEURS.md` |
| Matcher **texte** | 69,7 % d'auto-attribution à **94,5 %** de précision | `VISION.md`, 2026-06-12 |
| File ouverte | 6 894 crops | réplique, 2026-08-20 |

Requête du contrôle de fuite, à rejouer :

```sql
WITH ancres AS (SELECT DISTINCT asset_id FROM dino_class_references
                 WHERE anchors_kind='2eur_all' AND asset_id IS NOT NULL),
lab AS (SELECT rq.decided_eurio_id v, p.top1_eurio_id pred, COALESCE(p.spread,0) sp,
               (rq.image_asset_id IN (SELECT asset_id FROM ancres)) est_ancre
          FROM review_queue rq
          JOIN image_asset_dino_predictions p
            ON p.asset_id=rq.image_asset_id AND p.anchors_kind='2eur_all'
         WHERE rq.status='done' AND rq.decided_eurio_id IS NOT NULL)
SELECT est_ancre, COUNT(*), ROUND(100.0*SUM(pred=v)/COUNT(*),1)
  FROM lab WHERE sp >= 0.10 GROUP BY 1;
-- 0 (hors banque) | 463 | 98,5
-- 1 (est une ancre)| 821 | 97,4
```

---

## 3. Le geste zéro : instrumenter, parce qu'on ne sait rien

**Aujourd'hui, rien ne trace ce que l'humain fait.** La colonne
`image_assets.origin` est `NULL` sur **12 330 lignes sur 12 454** :

```sql
SELECT COALESCE(origin,'(NULL)'), COUNT(*), SUM(training_eligible=1)
  FROM image_assets GROUP BY 1;
-- (NULL)    | 12330 | 1988
-- collected |   124 |   45
```

Sans instrumentation, tout le reste de ce document est de l'opinion.

### 3.1 Le piège du signal, soulevé par le PO

> « Est-ce que si j'ouvre la vue recrop, c'est un vrai signal ? Des fois je peux
> ouvrir la vue recrop juste pour la voir en grand et me dire : ok, c'est bon.
> Des fois pour rebouger un peu le truc très légèrement. Des fois je bouge
> complètement le crop. »

**Ouvrir la vue n'est pas un signal.** C'est le piège classique : on
instrumente ce qui est facile à capter (un événement d'UI) au lieu de ce qui
porte l'information (un changement d'état).

Le signal est le **delta de la bbox**, et il a au moins trois régimes qui ne
disent pas la même chose :

| Régime | Ce que ça signifie | Ce que ça implique |
|---|---|---|
| ouverte, **bbox inchangée** | le crop était bon, l'humain a juste voulu voir | **c'est un A**, pas un B — automatisable |
| **retouche légère** (IoU élevé) | le détecteur est presque juste | tolérance du cropper à élargir, ou marge de padding |
| **refaite entièrement** (IoU faible) | le détecteur s'est trompé de cible | vrai échec de détection, à corriger en amont |

Le seuil qui sépare « légère » de « refaite » ne se devine pas : il se lit sur
la distribution des IoU une fois qu'on aura les données. **Ne pas le fixer a
priori.**

### 3.2 Ce qu'il faut logger, par décision

Une ligne par décision de review, append-only :

- `asset_id`, `decided_at`, `decided_by`
- l'issue : `accept` / `accept_after_recrop` / `reject` + motif / `reclassify`
- **bbox avant / bbox après** (la table porte déjà `bbox_json`) et l'**IoU**
- la vue recrop a-t-elle été ouverte (oui, mais comme *contexte*, jamais comme
  signal principal)
- ce que le modèle proposait : `top1`, `spread`, `top1_country` — pour pouvoir
  répondre plus tard à « qu'aurait-on auto-accepté ? » sans rejouer le modèle
- durée de la décision, si elle est captable sans bricolage

**Critère de sortie** : deux semaines de review normale, puis la répartition
A/B/C/D en pourcentage du volume **et** en pourcentage du temps. Les deux
diffèrent, et c'est le temps qui décide où investir.

---

## 4. Les leviers, par famille

### 4.1 Famille A — le débit, pas la précision

**La planche de confirmation.** C'est le levier que le PO et l'analyse
retiennent tous les deux comme prioritaire.

Aujourd'hui : un crop, une décision complète. Alternative : une **grille de 20
à 40 crops** que le modèle juge sûrs ; l'humain balaie et **décoche seulement
les faux**.

Ce n'est pas de la précision en plus, c'est du **débit**. Et ça marche même à
90 % de précision, parce que l'humain devient le correcteur d'erreurs et non le
décideur. Facteur potentiel : ×10 sur le volume traité à temps constant.

⚠️ **À vérifier avant d'inventer** : `bulk_assign_lot_review` existe déjà dans
le code, et la review porte déjà une notion de lot. Regarder ce qui est
réutilisable avant d'écrire un écran.

Question de conception à trancher : la planche montre-t-elle des crops **d'une
même classe** (l'œil compare vite, mais on rate une intruse plausible) ou
**mélangés** (plus dur, moins d'effet d'ancrage) ? Ça se mesure.

### 4.2 Famille D — fusionner des canaux indépendants

Trois signaux existent, **et ne sont jamais combinés** :

1. **DINO** — 91,6 % global@1, et surtout **97,4 % en bande pays**. Le pays est
   aujourd'hui utilisé pour re-ranker, **jamais pour décider**. Or un crop dont
   le pays est quasi certain et qui n'a qu'une classe plausible dans ce pays
   est pratiquement tranché.
2. **Le texte** du listing — 69,7 % d'auto-attribution à 94,5 %. Canal
   **indépendant** de la vision : c'est ce qui rend la fusion payante.
3. **Le contexte du listing** — `target_eurio_id`, pays du vendeur, millésime
   annoncé.

Fusionner deux canaux indépendants à ~95 % chacun donne bien plus de couverture
à précision constante que de pousser l'un des deux à 97 %. C'est le levier le
mieux fondé du document, et le moins coûteux : aucune donnée nouvelle.

**Les seuils par classe.** `banque-dino/DECISIONS.md` laissait la question
ouverte : *« le schéma le portera, l'écran ne l'exposera pas tant qu'aucune
mesure ne dira laquelle est difficile »*. Les mesures existent maintenant
(`COURBE-REFERENCES.md`, `BENCH-ENCODEURS.md`). Une classe à 10 exemplaires et
une classe à canonique seul ne méritent pas le même seuil.

### 4.3 Famille C — les rejets automatisables

Le PO en nomme un précis : **la carte**.

> « Sur cette photo, on voit la carte. Pas intéressé, c'est le design de la
> carte. »

Les listings montrent souvent le **coincard / blister** plutôt que la pièce.
C'est une classe visuelle nette, apprenable, et le rejet est certain — donc un
candidat idéal à l'automatisation totale. Même patron que le détecteur de
**face** déjà livré (C7 : 0 % de faux positifs sur 562 avers, ancres = deux
designs de revers communs, **zéro entraînement**).

Le patron existe donc : une petite banque d'ancres « carte » + un seuil. À
mesurer : quelle fraction de la file ouverte est de la carte.

Autres rejets probablement automatisables, à quantifier : lots multi-pièces,
pièces sous capsule/plastique réfléchissant, photos de catalogue/dessin plutôt
que de vraie pièce (c'est l'hypothèse **H8** de `VISION.md`, jamais testée).

### 4.4 Famille B — le cropper

C'est probablement le gros du temps, et c'est celle dont on sait le moins.
Elle reste **en attente de l'instrumentation** : sans la distribution des IoU
et des cas d'échec, tout choix serait aveugle.

Les questions à poser aux données, une fois qu'on les aura : les recadrages se
concentrent-ils sur les **bimétalliques** (le détecteur accroche le disque
intérieur — piège déjà documenté, padding Hough à 25 %) ? sur les images à
**plusieurs pièces** ? sur les **cadrages lointains** ?

Livrable plausible : un **score de qualité de crop** qui ne route vers l'humain
que les mauvais — ce qui transforme B en A pour tout le reste.

---

## 5. La dimension absente : l'état et le prix

Soulevée par le PO, et **non traitée nulle part dans le projet aujourd'hui**.

> « Le prix d'une pièce se fait par catégorie : si elle n'a jamais été ouverte,
> utilisée mais en très bon état, si l'état est dégradé, si elle est très
> dégradée. Actuellement je fais de la review et je me fous du prix. »

C'est un **axe orthogonal** à tout ce qui précède : l'attribution de classe dit
*quelle pièce*, le grade dit *quelle valeur*. Les deux se lisent sur la même
image, et la review les voit passer ensemble — mais une seule est captée.

Ce qu'il faut décider avant d'y toucher :

- **Le vocabulaire.** Reprend-on une échelle numismatique existante (Sheldon,
  ou l'échelle européenne SUP/SPL/FDC) ou une échelle propre à 3-4 crans ?
  Une échelle trop fine ne sera ni annotable de façon fiable ni apprenable.
- **Qui produit le label.** Le vendeur eBay l'annonce parfois dans son texte —
  canal gratuit, à évaluer comme on l'a fait pour le theme-matcher. Sinon c'est
  de l'annotation humaine, donc un coût qui s'ajoute à la review.
- **À quoi ça sert d'abord.** Estimer la valeur du coffre de l'utilisateur ?
  Filtrer les crops trop usés hors de la banque d'ancres (une pièce très usée
  est un mauvais représentant de sa classe) ? Le second est un bénéfice
  **immédiat pour le modèle**, le premier est un bénéfice produit.
- **Le coût sur la review.** Ajouter un geste par crop irait à l'exact opposé
  du but de ce chantier. Si le grade entre dans la review, ce doit être par un
  canal qui ne coûte rien à l'humain — le texte du listing, ou un modèle.

⚠️ Ce point mérite sa propre décision produit avant tout code. Il n'est pas
dans le chemin critique du scan.

---

## 6. L'ordre que je propose

1. **Instrumenter** (§3). Une ligne de log par décision, le delta de bbox comme
   signal. Deux semaines de review normale. **Rien d'autre ne se décide avant.**
2. **La planche de confirmation** (§4.1). Indépendante de la mesure, gain de
   débit immédiat, réutilise probablement `bulk_assign_lot_review`.
3. **La fusion de canaux** (§4.2). Aucune donnée nouvelle requise, le levier le
   mieux fondé.
4. **Le détecteur de carte** (§4.3). Patron déjà éprouvé par le détecteur de
   face, zéro entraînement.
5. **Le cropper** (§4.4) — seulement quand 1 aura dit que c'est là qu'est le
   temps.
6. **L'état et le prix** (§5) — décision produit séparée.

## 7. Ce qui rendrait ce document faux

Si l'instrumentation montre que **A domine déjà** et que le « 90 % » était une
impression, alors le goulot n'est pas le crop mais le **volume** : 6 894 crops
en file et une seule paire d'yeux. Dans ce cas la planche de confirmation
devient le seul chantier qui compte, et B/C/D passent au second plan.

C'est un résultat parfaitement possible. C'est pour ça qu'on mesure d'abord.
