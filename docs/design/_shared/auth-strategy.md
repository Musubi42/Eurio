# Auth strategy — silencieuse, différée, opt-in

> **Principe directeur** : l'user n'est jamais forcé de se connecter pour utiliser l'app. L'auth n'apparaît que quand une feature l'exige (marketplace, partage public de coffre, sync multi-device).
>
> Décidé le 2026-04-13. Inspiration : Duolingo (tu fais 5 leçons avant qu'on te demande un compte, et quand tu le crées, la progression est conservée).

---

## Les états possibles d'un user

### 1. Guest (default)
- Zéro auth, zéro compte, zéro email demandé.
- `user_id` = UUID généré localement au premier lancement, stocké dans DataStore.
- Tout le coffre est local Room, rattaché à ce UUID.
- Fonctionne 100% offline. Fonctionne 100% de la v1.

### 2. Anonymous (Supabase `signInAnonymously`)
- Créé silencieusement quand une feature réseau est activée la première fois (ex : l'user veut activer la sync des prix eBay, ou accepte le delta fetch du référentiel).
- Supabase émet un JWT anonyme lié au device. Tous les appels réseau sont authentifiés.
- Le coffre reste local ; rien n'est pushé au backend tant que l'user n'a pas explicitement activé la sync cloud.
- Upgrade possible vers un compte complet sans perdre le `user_id` ni la collection.

### 3. Authenticated (Credential Manager → Google Sign-In)
- L'user clique sur "Sauvegarder ma collection" ou "Montrer mon coffre à un ami" → on déclenche Credential Manager.
- Android Credential Manager affiche le bottom sheet natif avec les comptes Google du device. **Zéro tap pour entrer un email.**
- Supabase lie le compte Google au `user_id` anonyme existant via `linkIdentity`. La collection est conservée.
- À partir de là, l'user peut se logger depuis un autre device et retrouver son coffre.

---

## Pattern Duolingo appliqué

Duolingo est la référence : tu ouvres l'app, tu choisis ta langue, tu fais 5 exercices, tu gagnes tes premiers XP, **et seulement après** une popup te propose de "sauvegarder ta progression" avec Google / Apple / email. Si tu skip, tu continues à jouer. La friction d'auth est entièrement décorrelée de la valeur perçue initiale.

Appliqué à Eurio :
1. Open app → pas de login screen, direct sur le scan.
2. Scan première pièce → fiche + "Ajouter au coffre" → ajout local, zero friction.
3. Après la 3ème pièce ajoutée (ou après 48h d'usage), soft prompt : *"Sauvegarde ta collection — un clic avec Google"*. Skippable.
4. Jamais de hard gate. Jamais.

---

## Credential Manager Android

`androidx.credentials:credentials` + `androidx.credentials:credentials-play-services-auth`

Avantages sur l'ancienne API Google Sign-In :
- Bottom sheet natif, pas de webview, pas de redirect.
- Intègre Google + passkeys + password manager dans une seule API.
- **Un seul tap** si l'user est déjà loggé Google sur son device (ce qui est le cas pour 99% des devices Android).
- Recommandé par Google depuis Android 14, backport via Play Services.

À creuser quand on implémentera :
- Comment gérer les devices sans compte Google (possible mais rare) → fallback email/password Supabase.
- Flow de linkIdentity Supabase : garder le même `user_id` quand on passe de anonymous à authenticated.

---

## Ce qu'on fait en v1

- **Tout guest, tout local.** Pas de Credential Manager, pas d'anonymous, pas de Supabase auth dans le code Android v1.
- Le seul point de contact réseau est un fetch anonyme (clé publique Supabase `anon`) vers la table `coins` pour le delta fetch du référentiel et vers Storage pour les images Numista. Pas besoin de user identifié pour ça.
- `user_id` local = UUID généré et stocké en DataStore. Sert à rien d'autre qu'à préparer l'upgrade futur vers un vrai compte.

## Ce qu'on prépare pour v2

- Schema Room avec une colonne `owner_user_id` sur `user_collection` pointant vers le UUID local. Quand on activera l'auth plus tard, un `UPDATE` massif remplacera le UUID local par le user_id Supabase après linkIdentity.
- Pas de modèle d'auth hardcodé dans le code. Toute la logique "guest vs authenticated" passe par un `AuthState` enum qu'on peut étendre.

---

## Questions ouvertes

- [ ] Supabase `signInAnonymously` + `linkIdentity` preservent-ils bien le `user_id` ? À valider avec un POC quand on arrivera à la v2.
- [ ] Pour les features sociales (partager son coffre, voir celui d'un ami), est-ce qu'on veut des profils publics obligatoires ou juste des liens de partage éphémères ? Question produit, pas tech.
- [ ] Export PDF du coffre : est-ce qu'on exige un email pour l'envoyer, ou juste un `ACTION_SEND` local ? → probablement local, zéro friction.
