# Scan — remote fallback (question ouverte)

> **Statut** : non tranché. Brainstorm du 2026-04-13.
>
> Le problème : quand une nouvelle pièce sort (ex : commémo JO Paris), le modèle local de l'user ne la connaît pas. Le scan échoue. Comment on gère ?

---

## Le problème en détail

1. Une nouvelle pièce est frappée (par exemple une commémorative pour un événement du moment).
2. Je ré-entraîne le modèle ArcFace côté `ml/`, j'obtiens un nouveau `.tflite` + nouveau `coin_embeddings.npy`.
3. L'user ouvre l'app pour scanner cette pièce **maintenant** (pas dans 6 mois), parce que c'est l'événement qui fait qu'il a la pièce dans la main.
4. Si son modèle local est vieux, le scan échoue.

Contraintes :
- Pas question de re-télécharger un modèle ML (5–15 MB) à chaque ouverture → friction, data cellulaire, abandon.
- Pas question d'attendre la prochaine release APK (2-3 mois) → la pertinence temporelle est perdue.
- Pas question de laisser l'user sans réponse → expérience dégradée critique sur la killer feature.

---

## Option A — Fallback serveur synchrone

Si le scan local ne matche pas avec confiance suffisante, l'app upload la photo vers un endpoint serveur qui a le modèle à jour et renvoie le `eurio_id` + confidence.

**Pros** :
- Réactivité immédiate, l'user a une réponse même si son modèle est vieux.
- Pas besoin de re-télécharger quoi que ce soit côté device.
- Permet de collecter des images réelles de nouvelles pièces (dataset training gratuit).

**Cons** :
- Nécessite un endpoint serveur avec le modèle ArcFace chargé. Pas faisable en Edge Function Supabase (Deno, pas de TFLite Python). Implique un service Python séparé.
- Coût infra non-nul (RAM pour le modèle, CPU/GPU pour l'inférence).
- Latence réseau (1-3s) sur le fallback, dégradation UX par rapport au scan local.
- Vie privée : l'user accepte d'envoyer une photo de sa pièce à un serveur.
- Option "zéro infra live" (mémoire `project_eurio_stack.md`) violée.

**Hébergement possible** (à explorer) :
- Modal.com, Replicate.com, HuggingFace Inference Endpoints — hébergement Python avec GPU à la demande, paiement à l'usage.
- Supabase Edge Function **ne peut pas** faire tourner du TFLite Python → requiert un autre backend.
- Fly.io / Railway pour un petit container Python persistent.

## Option B — Delta embeddings via Supabase (recommandé provisoirement)

Hypothèse clé : **le modèle ArcFace généralise**. Un embedding produit pour une pièce que le modèle n'a jamais vue en training reste discriminant s'il est dans le même espace latent.

Si cette hypothèse tient, on peut :
1. Garder le même modèle TFLite pendant longtemps (tous les 6-12 mois).
2. Quand une nouvelle pièce est ajoutée au référentiel, on calcule son embedding côté `ml/` avec le modèle stable.
3. On push l'embedding dans Supabase `coin_embeddings` (table existante, vide actuellement).
4. L'app fait un delta fetch périodique sur cette table (quelques Ko par nouvelle pièce).
5. Le scan local continue de fonctionner, avec un catalogue d'embeddings à jour.

**Pros** :
- Pas de serveur d'inférence, zéro infra supplémentaire.
- Delta minuscule (<1 KB par pièce).
- Respect total de la vie privée.
- Pas de latence réseau au scan.

**Cons** :
- Hypothèse à valider : est-ce qu'ArcFace généralise vraiment à des classes non vues ?
- Si l'hypothèse casse, on est obligé de re-entraîner et re-shipper le modèle à chaque ajout → retour case départ.
- Les nouvelles pièces très différentes des pièces vues en training peuvent avoir des embeddings bruités.

## Option C — Hybride

- **v1** : Option B pure, on parie sur la généralisation d'ArcFace.
- **Télémétrie** : on track le taux d'échec de scan côté device (scans qui finissent en "non identifié").
- **Si le taux dépasse X%** (à définir, ex : 5%), on active l'Option A comme fallback optionnel.
- Les nouveaux modèles TFLite sont shipped dans les releases APK régulières (tous les 2-3 mois), pas en hot-patch.

---

## Autre dimension — téléchargement du modèle en background

Indépendamment du fallback, on peut proposer :

- Paramètre "télécharger les nouveaux modèles de pièces" : OFF / Wi-Fi only / Wi-Fi + cellulaire.
- Quand un nouveau modèle est dispo et que la condition est remplie, WorkManager télécharge en background.
- Notification discrète quand c'est fini : "Ton scan connaît maintenant les dernières commémoratives".

C'est compatible avec Option B (on télécharge les nouveaux embeddings) OU Option A (on met à jour le modèle TFLite si on en ship un nouveau).

---

## Recommandation provisoire

**Démarrer en v1 avec Option B pure.** Pas de serveur d'inférence. Pas de fallback réseau sur le scan. On parie sur la généralisation ArcFace (hypothèse centrale de metric learning) et on valide en Phase 2B avec des métriques.

**Si Phase 2B montre que la généralisation casse** → on revient ici et on ajoute Option A comme filet de sécurité.

**Ne pas implémenter Option A avant d'avoir des données** qui justifient son coût.

---

## Questions à répondre avant de trancher

- [ ] Phase 2B : quelle est la R@1 du modèle ArcFace sur des classes **non vues** en training ? (Eval set : pièces réservées qu'on met de côté avant training.)
- [ ] Si on va sur Option A : combien d'appels/mois attendus ? Coût infra ?
- [ ] Si on va sur Option B : à quelle fréquence on doit re-entraîner le modèle pour que la généralisation reste bonne ?
- [ ] Comment l'user est-il informé que son modèle est "vieux" et que certaines pièces peuvent échouer ?
