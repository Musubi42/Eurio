# Comment tester une skill

> Méthode **observée**, pas inventée : elle a été extraite d'une campagne réelle
> menée le **2026-08-17** sur les cinq skills métier d'Eurio. Chaque règle
> ci-dessous existe parce qu'une épreuve l'a produite ; les contre-exemples sont
> ceux qu'on a vus, pas ceux qu'on imagine.

## Pourquoi une skill « vérifiée à la lecture » ne prouve rien

Un agent en lecture seule confirme que les chemins existent. Il ne peut pas dire
si la skill fait **agir juste** — et c'est la seule chose qui compte. Les trois
défauts les plus coûteux trouvés dans cette campagne étaient tous invisibles à la
lecture :

- un chiffre plausible, cité deux fois, que **personne ne pouvait reproduire**
  parce que la skill ne disait pas sur quelle population il portait ;
- un renvoi (« la banque `2eur_all` est celle des suggestions de review ») que le
  code contredit en dur, et qui condamne silencieusement toute une famille de
  pièces ;
- une garde de sécurité dont le **message d'erreur** énonce un mécanisme faux.

---

## Épreuve 1 — l'exécution

**Exécuter chaque affirmation portante, telle qu'elle est écrite, dans
l'environnement que la skill revendique.** Pas « le fichier existe » : « la
commande rend ce que la skill promet ».

Coût : quelques minutes par skill. Ce qu'elle attrape : la péremption, les
chiffres non reproductibles, les commandes mortes. Ce qu'elle n'attrape pas :
tout ce qui concerne le jugement.

Exemples de cette campagne :

| Affirmation testée | Résultat |
|---|---|
| `eurio-run-local` : `ml:api-replica` n'existe plus, la tâche est `ml:api-prod` | ✅ exact, les 5 noms vérifiés un par un |
| `eurio-vps-deploy` : `docker logs … grep "routers montés"` est le contrôle le plus informatif | ⚠️ **la commande marche et induit en erreur** — voir ci-dessous |
| `eurio-review` : « 38 candidats, marge moyenne 0,169 » | ❌ irreproductible : 59 ou 0 selon la population, que la skill ne nomme pas |
| `eurio-enrichment` : `go-task ml:scrape-ebay` est morte | ✅ `ml/market/scrape_ebay.py` : No such file |

### La règle que l'épreuve 1 a produite

> **Tout chiffre dans une skill porte sa requête, pas seulement sa date.**

Le tableau de `eurio-review` annonçait « 38 candidats à sim ≥ 0,855, dont 38
au-dessus de la marge ». Deux agents l'ont mesuré et sont arrivés à **59** et à
**0** — sans se contredire : l'un comptait les crops *prédits comme* la classe,
l'autre les crops *ciblant* la classe. Les deux mesures sont justes. Le chiffre
de la skill, lui, était **infalsifiable**, donc inutilisable dans un document
dont tout l'intérêt est qu'on puisse s'y fier.

Une date de mesure ne suffit pas. Il faut la requête, ou à défaut la phrase qui
dit exactement ce qu'on compte.

---

## Épreuve 2 — l'agent

**Une tâche réelle du domaine, la skill pour seule documentation, exploration du
code autorisée** (c'est le mode normal — une skill ne peut pas tout dire, et
viser ça la transformerait en pavé illisible).

Ce qui en fait un test et non une démonstration, c'est le protocole :

1. **Une seule skill chargée.** Sinon aucune attribution n'est possible. On
   interdit explicitement de suivre les renvois — et on demande de **noter** où
   la skill voulait envoyer. C'est ainsi qu'on mesure la qualité de ses renvois.
2. **Une tâche réelle**, avec un point d'arrêt net avant l'irréversible (« donne
   la commande exacte, ne la lance pas », « amène l'humain au point de décision,
   ne décide pas à sa place »). L'agent doit pouvoir taper l'API, lancer des
   jobs, interroger la base.
3. **Six sections de trace imposées**, dont deux portent tout le poids.

### Les six sections

```
(a) Commandes exactes lancées, dans l'ordre.
(b) Ce que la skill m'a évité : nomme le piège, ET le moment précis
    où j'allais tomber dedans.
(c) Ce que j'ai dû chercher hors de la skill : quoi, où, combien
    d'aller-retours.
(d) Ce que j'allais improviser (outil, script, requête) avant de la lire.
(e) Vers quoi la skill m'a renvoyé, et à quel moment.
(f) Ce qui, dans la skill, est FAUX ou PÉRIMÉ — uniquement ce que tu as
    vérifié EN EXÉCUTANT. Cite la commande et sa sortie.
```

**(b) et (d) sont le test.** Ce sont les deux seuls endroits où la valeur d'une
skill devient observable, parce qu'ils capturent le contrefactuel : ce qui se
serait passé sans elle. Exiger *le moment précis* est ce qui empêche la réponse
de complaisance — un agent qui ne peut pas dater son évitement ne l'a pas vécu.

Récolte réelle en (d), toutes épreuves confondues : une planche HTML de vignettes
(l'outil exact que la skill existe pour empêcher), un framework maison de
mutation testing, trois requêtes SQL à seuil inventé, une copie `cp` d'un SQLite
en WAL, un rebuild d'ancres de 1 h 30 « par précaution ».

**(f) doit être formulée pour être falsifiable.** La rédaction « uniquement ce
que tu as vérifié en exécutant, cite la commande » a fonctionné : un agent l'a
laissée quasi vide en l'écrivant noir sur blanc — *« Rien. Je ne veux pas remplir
cette section par politesse. »* Une section (f) toujours pleine est le signe que
la consigne est trop molle.

### Le contrôle — et pourquoi il est indispensable

**Faire tourner la même tâche sans aucune skill.** Sans lui, (b) et (d) restent
auto-rapportées, donc flatteuses : l'agent sait qu'on l'interroge sur une skill,
et il a envie qu'elle ait servi.

**Ce que le contrôle a donné le 2026-08-17, et il faut le dire tel quel : il n'a
pas eu besoin de la skill.**

Même tâche que le bras `eurio-review` (préparer l'acceptation des crops de
`fr-2euro-standard-t1`), aucune skill chargée. Le contrôle a :

- trouvé le front tout seul, avec **les bonnes URLs et le bon paramètre**
  (`?mode=lot&design_group=…`) — que la skill, elle, ne donnait pas ;
- **renoncé deux fois** à fabriquer un outil, en écrivant explicitement
  pourquoi : *« Deux fois j'ai commencé à écrire un outil, et deux fois le dépôt
  l'avait déjà »* — planche HTML abandonnée au profit de `LotReviewView` +
  `DinoVerdict.vue`, script de scoring abandonné au profit de
  `preflight_classes` ;
- atteint la bonne piste en **~4 aller-retours** contre ~18 pour le bras skill ;
- trouvé seul le seuil canonique, le gate `face='reverse'`, et le
  `[mock fallback]` silencieux du front.

Il a même produit une mesure que le bras skill n'avait pas : **35 des 41
candidats viennent d'une seule annonce**, cinq photos d'un même vendeur. Un
plancher franchi numériquement, pas en diversité.

Trois réserves d'honnêteté sur ce résultat :

1. **contamination légère** — un `grep` a fait apparaître deux lignes d'un
   `SKILL.md` dans sa sortie ; le contrôle l'a signalé et n'a pas utilisé ces
   chiffres ;
2. **le `CLAUDE.md` reste chargé** dans les deux bras : le contrôle n'est pas
   « sans documentation », il est « sans skill » ;
3. **il n'a pas trouvé la cécité `2eur_commemo`** — il a mesuré les prédictions
   existantes sans filtrer sur la banque que le verdict interroge, et a donc
   annoncé 41 candidats là où l'écran en montrera zéro.

**Ce qu'on en conclut, et c'est le résultat le plus utile de la campagne :** sur
cette tâche, la skill `eurio-review` ne gagnait pas son principal argument (« ne
fabrique pas de planche parallèle ») — un agent compétent ne tombait pas dans le
piège. Ce qu'elle apportait vraiment était ailleurs : la **cécité structurelle du
verdict**, que le contrôle a manquée. La skill a donc été corrigée dans les deux
sens : on a **retiré** de la valeur à son piège central en le déplaçant du rang
d'avertissement principal, et **ajouté** ce qu'elle seule pouvait porter.

Sans le contrôle, on aurait durci le mauvais bout.

Un contrôle par campagne suffit — choisir la skill dont le piège central est le
plus vérifiable de l'extérieur. Et budgéter d'être contredit.

---

## La grille de verdict, et sa règle d'attribution

Le critère n'est **pas** que l'agent réussisse sans explorer. C'est qu'il évite
les pièges que la skill existe pour éviter, qu'il sache où aller lire quand elle
s'arrête, qu'il ne réinvente pas un outil que le projet possède, et qu'il
s'oriente vite.

| Ce que l'agent a fait | Verdict |
|---|---|
| Tombé dans un piège **que la skill nomme** | La skill est mal écrite — corriger la **forme** (enterré, ambigu), pas ajouter du texte |
| Tombé dans un piège du domaine **qu'elle ne nomme pas** | **Ajouter** |
| **Réinventé un outil que le projet possède** | **Ajouter** — c'est le défaut le plus cher, et le plus fréquent |
| S'est arrêté sans savoir où aller | **Ajouter un renvoi**, pas le contenu |
| A dû lire du code métier pour avancer | **Normal. Ne rien faire.** |
| A buté sur un détail hors périmètre déclaré | **Normal.** Le noter comme frontière, ne pas durcir |

### Le compteur d'orientation, et comment le lire

La section (c) donne un nombre d'aller-retours hors skill. Mesurés ici : **10**
(`eurio-verify`), **~18** (`eurio-review`), **~22** (`eurio-enrichment`).

Ce nombre **n'est pas un seuil d'échec**. Ce qui compte est *sur quoi* ils
portent :

- ~22 aller-retours dans du code métier périphérique pour `eurio-enrichment` →
  **normal**, la skill ne prétend pas porter le pipeline eBay.
- mais **la moitié des 18 de `eurio-review` portaient sur les paramètres d'URL du
  front** — c'est-à-dire précisément sur ce que la skill s'était donné pour
  mission de fournir (« amener l'humain à l'endroit exact »). Elle donne les
  chemins de page et aucun paramètre de scope. → **correction**.

Règle : *un aller-retour cher sur le cœur de mission de la skill est un défaut ;
vingt aller-retours en périphérie n'en sont pas un.*

---

## Ce qu'on n'attendait pas, et qui est le meilleur rendement de la méthode

**Sur cinq épreuves, chaque agent a rapporté au moins un défaut du _projet_, pas
de la skill.** Tester une skill revient à auditer le domaine qu'elle décrit,
parce qu'on force quelqu'un à exécuter ce que plus personne n'exécute.

Récolte de la campagne du 2026-08-17 :

| Défaut | Trouvé par l'épreuve de |
|---|---|
| Le verdict de review joint en dur `anchors_kind='2eur_commemo'`, banque qui ne contient **aucune** pièce standard (0/446 étiquettes) → aucun crop de pièce standard ne peut jamais être `auto_candidate` | `eurio-review` |
| La garde de promotion refuse pour la bonne raison mais son message **énonce un mécanisme faux**, et `--force` la désarme sans un mot | `eurio-verify` |
| `/operations/cohorts` renvoie `n_members: 0` pour toutes les cohortes — il compte une table `cohort_members` vide et jamais alimentée, pendant que les membres vivent dans `eurio_ids_json` | épreuve d'exécution |
| Le hot-path review est **déjà reroutré** au VPS ; ce que le repo documente comme « résiduel » ne l'est plus | `eurio-data-writes` |
| `dino_class_references` est vide dans les **6 bases** : la sélection FPS des ancres n'est traçable nulle part | `eurio-enrichment` |
| Le log de boot du VPS annonce « routers skippés : review_queue » alors que `/review-queue/*` répond 200 — **deux modules homonymes**, l'un lean et monté, l'autre lourd et skippé | épreuve d'exécution |

**Corollaire pratique** : budgéter le temps de dépouillement. Une campagne de
cinq épreuves rend cinq rapports denses et une demi-douzaine de défauts réels à
trancher. Ce n'est pas du bruit, c'est le produit.

## Éprouve aussi les skills que tu viens d'écrire — surtout celles-là

Les deux skills neuves de la campagne (`eurio-cohort`, `eurio-promote`) ont été
soumises au même protocole immédiatement après rédaction. Résultats opposés, et
tous deux instructifs :

- **`eurio-cohort` : section (f) vide.** *« Rien. »* Toutes ses affirmations
  chiffrées reproduites à l'identique, cinq pièges nommés effectivement évités.
  Une skill peut passer.
- **`eurio-promote` : elle conduisait droit à une catastrophe.** Sa checklist
  disait *« lis `absent_in_promotion` : c'est ce que l'APK va perdre »*. Or
  `_diff_classes` compare à `prod/current`, absent sur cette machine ⇒
  `absent_in_promotion` **toujours vide** et `n_current: 0`. Le dry-run annonçait
  « rien de perdu » là où la comparaison à l'asset réel de l'APK donne **16
  pièces perdues sur 23**. L'épreuve a aussi trouvé que la cible Supabase de la
  promotion **n'existe pas** — l'échec arriverait *après* le point de non-retour.

La leçon est directe : **une skill fraîchement écrite est au maximum de son
risque**, parce qu'elle vient d'être rédigée depuis une expérience partielle. La
mienne était juste sur tout ce que j'avais exécuté, et fausse exactement là où
j'avais fait confiance à une sortie sans vérifier ce qu'elle mesurait.

Et une observation de forme : après correction, `eurio-review` et
`eurio-enrichment` dépassent 250 lignes. Le remède au pavé n'est pas de couper
du contenu vrai, c'est la section **« Ce que cette skill ne couvre PAS »** avec
les chemins de fichiers — la seule qui n'a jamais été prise en défaut.

---

## Ne pas prendre un rapport d'agent pour argent comptant

Deux agents ont mesuré la même classe et rendu **59** et **0**. Le second en a
conclu que la skill mentait. Les deux avaient raison sur leur population.

**Toute accusation de « la skill est fausse » se remesure soi-même avant
correction.** Dans ce cas la remesure a donné les deux chiffres, expliqué le
désaccord, et produit une correction meilleure que celle que chaque agent
proposait — plus la découverte du `2eur_commemo`, que ni l'un ni l'autre n'avait
formulée entièrement.

**Et la remesure peut être la fausse.** Vérifiant un « 10 annonces » rapporté par
deux agents, j'ai obtenu **0** et failli les corriger — mon parseur lisait la clé
`lots` d'une réponse qui s'appelle `items`, et `dict.get(…, [])` rendait
poliment une liste vide. Les agents avaient raison. C'est le motif exact du
catalogue `eurio-verify` : *une valeur par défaut plausible là où il fallait une
erreur*. Avant d'infirmer un chiffre, **imprime la forme du payload**, pas
seulement le compte que ton code en tire.

---

## Écrire une skill : ce que la campagne dit

1. **Ne l'écris pas de mémoire juste après avoir vécu la chose.** C'est l'origine
   des cinq erreurs de la session précédente. Écris, puis **relance les commandes
   que tu viens d'écrire**, et colle leur sortie.
2. **Chaque chiffre porte sa requête.** Sinon il est infalsifiable (§Épreuve 1).
3. **Nomme les pièges comme des gestes, pas comme des concepts.** Ce qui a
   fonctionné : « ⛔ Ne fabrique pas d'outil de review parallèle », « ⛔ jamais
   `pkill -f` avec un motif qu'on retape ». Un agent s'arrête sur un impératif ;
   il ne s'arrête pas sur un paragraphe d'architecture.
4. **Déclare tes frontières.** Une section « Ce que cette skill ne couvre PAS »
   avec les chemins de fichiers vaut mieux que dix pages : elle transforme un
   trou en renvoi. C'est la section qui a le mieux tenu à l'épreuve.
5. **Un diagnostic doit interroger l'état qui tourne, pas un état neuf.** Le
   snippet de `eurio-data-writes` importait `serving.server` dans un process
   frais pour savoir quelle base l'API utilise ; la bonne question est *quelle
   base utilise l'API **qui tourne***, et `ps eww -p $(lsof -ti :8042)` y répond
   en 50 ms sans rien importer.
6. **Chaîne les skills explicitement**, et vérifie le chaînage : la section (e)
   des rapports dit si les renvois tombent au bon moment.
