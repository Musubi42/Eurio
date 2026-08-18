# Décisions — ce qui est tranché

> Écrit le 2026-08-18, en réponse aux questions ouvertes de `SEUILS.md` et
> `DONNEES.md`. Chaque décision dit ce qu'elle **écarte**, sinon on la rejouera.
> Ce fichier est la référence : quand `SEUILS.md` pose une question, la réponse
> est ici.

## D1 · Le seuil est un réglage vivant, pas une propriété de la cohorte

**Décidé** : on travaille une cohorte au seuil du moment. Si la cohorte suivante
monte le seuil de 10 à 50, **les classes validées à 10 redeviennent incomplètes**.
Elles n'ont pas régressé : la règle a changé, et une classe porte son état au
regard de la règle en vigueur.

Conséquence directe sur l'écran (vue 4) : quand le plancher monte, la page ne
dit pas « 12 classes sont retombées sous le plancher ». Elle dit **« le plancher
est passé de 10 à 50 le 3 septembre — 12 classes qui le franchissaient ne le
franchissent plus »**. La cause est nommée, sinon ça se lit comme une panne.

**Écarté** : figer le seuil dans la cohorte à sa création (« cette cohorte est
une cohorte-10 pour toujours »). Ça donnerait des cohortes incomparables entre
elles et empêcherait justement l'expérience qu'on veut mener.

**Nuance qui n'est PAS écartée** : la valeur *utilisée* par un entraînement est
gelée dans l'itération (cf. D5). Le réglage vit ; la trace de ce qu'on a fait ne
bouge plus.

## D2 · Un seuil par classe : le schéma le porte, l'écran ne l'expose pas

Oui, une classe difficile peut légitimement exiger plus d'images qu'une classe
très typée. **Mais on n'a aujourd'hui aucune statistique pour dire laquelle est
difficile.** Décider à la main sans mesure, c'est fabriquer du bruit.

**Décidé** : la résolution du seuil prend un `class_id` optionnel dès
maintenant, et la table porte un `scope = 'class'` inutilisé. Le jour où le
benchmark donne un `r_at_1` par classe sur plusieurs runs, activer la surcharge
par classe coûte une insertion de lignes — pas une refonte.

**Écarté** : un champ « seuil » éditable par classe dans l'interface. Tant que
personne ne sait sur quoi se baser, ce champ serait rempli à l'intuition et
rendrait les runs inexplicables.

**Ce qui débloquera D2** : `benchmark_runs.per_coin_json` + `confusion_json`
agrégés par classe (déjà servis par `training-overlay`). Deux ou trois runs
suffisent à voir si les classes pauvres échouent *en tant que* classes pauvres.

## D3 · Un seul seuil — la promotion se décide sur la mesure

**Décidé** : le plancher autorise l'entraînement, et c'est tout. La décision de
promouvoir un modèle dans l'APK se prend au vu du **benchmark** (`r_at_1` par
classe, confusions), jamais d'un compteur de photos.

**Écarté** : un second seuil « assez pour être promue ». Il aurait l'air rigoureux
et ne mesurerait rien : 40 photos d'une classe qui se confond avec sa voisine ne
valent pas 12 photos d'une classe nette. Le compteur de photos est un
**prédicteur** de qualité ; une fois qu'on a la qualité mesurée, on n'a plus
besoin du prédicteur.

La place reste libre dans le schéma (`key = 'min_real_promote'` n'existe pas,
mais rien n'empêche de l'ajouter) — si l'expérience montre qu'on promeut trop
vite, on rouvrira D3 avec des chiffres.

## D4 · Les crops partis sur des pièces sœurs hors cohorte : on les affiche

Mesuré sur `giga-40-vague1` : **56 crops sur 37 pièces sœurs hors cohorte**
(4 crops du Bleuet de France atterris sur sa version *colorée*).

**Décidé** : l'écran le dit noir sur blanc, avec la liste. **On ne bouge rien.**
Ces crops restent en base et redeviendront utiles le jour où ces pièces entreront
dans une cohorte. Le travail n'est pas perdu — il est *ailleurs*, et le seul
défaut aujourd'hui est qu'on ne le voit pas.

**Écarté (pour l'instant)** :
- *rattacher automatiquement les sœurs à la cohorte* — élargir une classe est
  une décision de regroupement, elle appartient à la vue 1, pas à un effet de
  bord de la découpe ;
- *réattribuer les crops à la pièce de la cohorte* — une colorée n'est pas une
  standard. Réattribuer sans regarder, c'est polluer la classe qu'on essaie
  justement de mesurer.

Le back sert déjà la donnée : `rescued_to_sisters[]` dans `funnel-status`
(`ml/serving/lab_routes.py`). Il n'y a rien à calculer, seulement à afficher.

## D5 · Où vivent les seuils, concrètement

Trois notions, trois clés, **jamais fusionnées** (le désordre actuel vient de ce
qu'on les appelle toutes « assez ») :

| Clé | Aujourd'hui | Nature | Nom à l'écran |
|---|---:|---|---|
| `m_per_class` | 4 | technique, imposé par la composition d'un batch | « refus dur » |
| `min_real` | 10 | choix produit, à régler par l'expérience | « plancher » |
| `training_target` | 100 | paramètre de bake (après augmentation) | « cible » |

### La résolution, dans cet ordre

```
surcharge de classe   (scope='class',  prévu, inutilisé — D2)
      ↓ sinon
surcharge de cohorte  (scope='cohort')
      ↓ sinon
défaut global         (scope='global', modifiable sans redéploiement)
      ↓ sinon
constante Python      (le filet : si la table est vide ou absente)
```

Le dernier étage n'est pas de la dette, c'est une **précondition de démarrage** :
l'image lean du VPS et le préflight doivent fonctionner sur une base qui n'a pas
encore reçu la migration.

### Le stockage

Table au **canonique** (`eurio.db`, VPS) — un seuil est un fait de configuration,
donc de l'état, donc il vit là où vit l'état. Lue par un module **stdlib-only**
(contrainte d'image lean, cf. l'en-tête de `ml/store/funnel_constants.py`).

### Le gel dans l'itération

À la création d'une itération, les trois valeurs résolues sont écrites dans
`experiment_iterations.training_config_json` — là où `m_per_class` vit déjà.
Sans ça, on ne peut plus dire **avec quel plancher** un modèle a été entraîné, et
la comparaison entre runs perd son sens.

### Ce que le front ne fait jamais

Le front **n'écrit aucun seuil en dur**. `FLOOR = 10` / `GOAL = 30` dans
`useCohortFloor.ts` sont une dette du 2026-08-18, à retirer dans le même lot.

⚠️ **Le décalage de la réplique s'applique aussi aux seuils.** Le front écrit au
canonique (effet immédiat sur ce qu'il affiche), mais le préflight tourne sur la
machine locale, qui lit une **réplique rafraîchie toutes les 120 s**. Un seuil
qu'on vient de changer peut donc mettre jusqu'à 2 minutes à changer le verdict du
préflight. **L'écran doit le dire** — c'est exactement le genre de panne muette
que `VISION.md` interdit.

## D6 · Ce qui reste ouvert (et ne bloque rien)

- Quelle machine lance un run, et que faire si elle ne peut pas remonter son
  résultat (cf. `BACK.md`).
- Le rerouting des deux dernières routes d'écriture non jumelées au VPS.
- L'inventaire des tables abandonnées avant de figer le schéma
  (`docs/architecture/dette-de-stockage.md`).
