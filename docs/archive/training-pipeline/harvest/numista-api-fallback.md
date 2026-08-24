# Numista API — fallback image → pièce (exploration)

> Canal d'acquisition B (cf. `README.md`). **À explorer / pas démarré.** Kickoff 2026-06-07.

## But

Déléguer l'identification d'une pièce à **Numista** quand notre modèle on-device ne sait pas (encore) :
1. **Fallback in-app au début** — éviter de frustrer l'utilisateur tant que notre embedder n'est pas mûr.
2. **Source de label** — une pièce identifiée = un couple `(photo, eurio_id)` exploitable pour le dataset.

## Ce qu'on sait déjà de l'API Numista

- On l'utilise déjà comme **source catalogue** (`ml/sources/numista/`) : métadonnées par `numista_id`,
  prix via `/issues/{id}/prices` (7 grades → mapping UNC/TTB/TB, cf. memory `reference_numista_prices`).
- **Quota serré** : plan gratuit ~2000 calls/mois (memory `reference_numista_ratelimit`) — un fallback
  in-app grand public exploserait ce quota. À chiffrer (plan payant ? cache agressif ?).

## La grande inconnue à lever en premier

**Numista expose-t-il un endpoint de reconnaissance VISUELLE (image → candidats pièce) ?**
- Si OUI : c'est le fallback idéal (on envoie le crop, on récupère des candidats `numista_id` → `eurio_id`).
- Si NON (probable — Numista est un catalogue, pas un moteur de vision) : le « fallback image » n'existe
  pas côté Numista. Alors le fallback in-app réaliste devient :
  - soit **l'identification manuelle utilisateur** (canal A, `user-harvest.md`) — plus sûr,
  - soit un **moteur visuel tiers** (Google Lens-like) hors scope,
  - et Numista reste utile pour **enrichir** une fois l'`eurio_id` connu, pas pour le trouver depuis une image.

## Plan d'exploration (avant de coder)

1. Lire la doc API Numista à jour : endpoints disponibles, y a-t-il du search/visual ? termes d'usage,
   limites, coût des plans payants.
2. Tester : peut-on faire un search par attributs (pays, année, valeur, mots-clés) → liste de candidats ?
   (utile même sans vision : on pré-filtre par contexte de scan.)
3. Trancher la stratégie fallback réelle selon le résultat (cf. inconnue ci-dessus).
4. Si exploitable : chiffrer le quota pour un usage in-app + concevoir le cache.

## Décision attendue
Ce doc est une **exploration**, pas un plan figé. Sortie = une décision claire : « Numista sert de
fallback visuel » (si l'endpoint existe) **ou** « Numista n'est qu'un enrichisseur post-ID, le fallback
in-app = identification manuelle utilisateur ». Probable que ce soit la seconde.
