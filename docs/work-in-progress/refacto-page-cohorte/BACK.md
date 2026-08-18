# Le back — qui calcule quoi, sur quelle machine

> État constaté le 2026-08-18. Les chiffres portent leur mesure.

## Les trois machines

| Machine | Rôle | Contrainte |
|---|---|---|
| **Mac** | dev, scraping, découpe, review, **itérations d'essai** | pas de GPU |
| **PC** (NixOS, 1080 Ti) | **entraînements sérieux** | seule machine à GPU |
| **VPS** | **writer canonique**, MinIO, API, fronts | pas de GPU, image allégée |

Objectif à tenir : **un essai doit pouvoir tourner sur le Mac**, un vrai run sur
le PC, et les deux doivent se retrouver dans le même état côté serveur.

## La règle de circulation

- Mac et PC **lisent une réplique** de la base canonique (`eurio.replica.db`),
  rafraîchie par autopull **toutes les 120 s**.
- Mac et PC **écrivent au canonique** par HTTP (`POST /ingest/*`, routes de review).
- **Le calcul ne voyage pas** : bake, entraînement, artefacts restent sur la
  machine qui calcule.
- Les **transitions d'itération** sont poussées au canonique, ce qui permet à
  Mac et PC de voir le même état.

⚠️ **Conséquence directe sur l'UX** : tout compteur lu localement peut avoir
2 minutes de retard sur une décision de review. Les compteurs d'état doivent se
lire **au canonique**.

## Qui sert quoi

| Besoin | Adresse | Pourquoi |
|---|---|---|
| Compteurs d'état d'une classe | **canonique** `GET /lab/cohorts/{id}/training-crops` | c'est la vérité ; 68 Ko compressés, 0,29 s |
| Décisions de review | **canonique** | c'est un fait, il doit être unique |
| Stock de crops en attente, funnel | **local** `:8042` | dérivé lourd (3,6 s), pas critique à la seconde |
| Découpe, recrop, probes DINO | **local** | c'est du calcul GPU/CPU, il ne voyage pas |
| Bake, entraînement, benchmark | **local** (Mac essai / PC réel) | idem |
| Artefacts de modèle | MinIO | pour être repris ailleurs |

## Pièges à ne pas réintroduire

1. **Le flip lecture seule.** Le devShell pose la base en lecture seule sur
   Mac/PC. Une route qui écrit en direct répond `503 canonical_readonly` — ce
   n'est pas une panne, c'est le rappel qu'il faut passer par le canonique.

2. **Les secrets côté PC.** Un entraînement lancé sans les secrets crée
   l'itération, renvoie 200, et **n'atteint jamais le serveur**. À encadrer :
   l'écran doit refuser de lancer si l'environnement ne permet pas la remontée.

3. **Les passes désactivées par défaut.** La passe de secours bimétal est éteinte
   en prod (choix R0 : aucun impact sur le scan téléphone). Le mode
   d'enrichissement hors ligne **doit** la poser. Le bouton de recrop ne le
   faisait pas → il annonçait « épuisé » sur un stock intact.

4. **L'API locale sans rechargement.** Elle tourne sans `--reload` : un correctif
   n'est actif qu'après redémarrage. Vérifier l'environnement réel du job, pas le
   fichier source.

## Ce qui reste à décider

- **Où vivent les seuils** (cf. `SEUILS.md`) : table de configuration au canonique,
  surcharge par cohorte, valeur figée dans l'itération.
- **Comment l'écran choisit la machine** pour un run, et ce qu'il fait si la
  machine choisie ne peut pas remonter son résultat.
- **Que devient un artefact calculé sur le Mac** quand on rejoue sur le PC :
  on recalcule, ou on transporte ?
- **Le rerouting des dernières routes d'écriture** encore non jumelées côté VPS
  (`POST /review-queue/requalify-lot/batch`, `POST /coins/assets/reflag-needs-review`).
