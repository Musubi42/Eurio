# Décisions — review collaborative v2

> Une entrée par décision : ce qu'on fait, **pourquoi**, et surtout **ce que ça
> écarte**. Une décision sans son alternative écartée se re-débat tous les six mois.
> Tranché avec le PO le 2026-08-23.

---

## D1 — Les amis écrivent le canonique, pas un tampon

**Décision.** Suppression de `review.db` et du pont `publish` / `reconcile`. Les amis
travaillent directement sur `review_queue` du canonique, via `eurio-api`.

**Pourquoi.** Le tampon existait parce que `eurio.db` vivait derrière un lease sur le
Mac et qu'il fallait un endroit toujours allumé. Sous Direction A le canonique **est**
sur le VPS : le tampon recopie la donnée d'un serveur vers lui-même.

**Ce que ça écarte.** L'architecture de [`collaborative-review/`](../collaborative-review/)
(juin 2026), qui reste valide *pour son époque*. Ce chantier la **supersède**.

---

## D2 — Authentik, pas de token maison

**Décision.** Un ami = un compte Authentik + le rôle `reviewer`, créé par Raphaël.

**Pourquoi.** Le rôle et ses scopes existent déjà. Créer un ami = une ligne dans
`users` + une dans `user_roles`. Le coût est de deux minutes, une fois, côté Raphaël
— jamais côté ami.

**Ce que ça écarte.** Le lien magique adossé à `pat_tokens` (qui marcherait
techniquement) : il imposerait un second mode d'auth dans le front hébergé (aujourd'hui
en cookie), une route de création hors OIDC et une révocation à gérer. C'est du code
possédé pour toujours — et c'est exactement ce que les tokens `?u=Paolo42` avaient
déjà coûté avant d'être dépréciés.

**Limite connue.** `ROLE_SCOPES` est un dict Python en dur (`auth_principal.py:33`) :
ajuster ce que voit un reviewer = un changement de code + un redéploiement. Acceptable
à trois rôles. Le jour où le réglage devient fin, ce dict doit descendre en base.

---

## D3 — Les scopes SONT le modèle de droits

**Décision.** Aucun second système de permissions. « Accès vue / lecture / modification »
= les scopes existants (`review:read` vs `review:write`, `coins:read` vs `coins:write`…).

**Pourquoi.** Le serveur les fait déjà respecter route par route (`require_scope`). Un
modèle parallèle côté front produirait deux vérités qui divergent.

**Conséquence.** Le filtrage de nav est du **confort**. La vraie garde reste serveur :
un ami qui devine `/training` prend un 403, pas une page.

---

## D4 — La nav a deux axes orthogonaux

**Décision.** `NavItem.heavy` (« cette machine peut-elle ? ») **et** `NavItem.scope`
(« cette personne a-t-elle le droit ? »). Deux drapeaux, deux questions.

**Pourquoi.** Aujourd'hui tout est grisé sur le seul axe machine — les routes review
sont marquées `heavy` alors que l'essentiel de ce qu'elles appellent est déjà servi par
le VPS. Le gel est plus large que sa cause.

**Résultat.** Un `reviewer` voit **Tableau de bord, Pièces, Review, Besoin** — sans
modifier un seul rôle, ses scopes actuels suffisent exactement. `/besoin` est déjà
non-`heavy` délibérément (`router.ts:72`), et sert d'objectif visible : reviewer à
l'infini sans voir à quoi ça sert, c'est fatigant.

---

## D5 — Le navigateur envoie trois flottants, le serveur possède les pixels

**Décision.** Le recadrage reste appliqué côté serveur, par `_crop_mask_resize_float`.
On ajoute `opencv-python-headless` à l'image VPS — **pas** torch.

**Pourquoi.** Ces pixels nourrissent l'entraînement ; le code dit « Format IDENTIQUE à
la prod » et maintient une variante entière « bit-for-bit » pour le port Kotlin.

**Ce que ça écarte.** Le crop en Canvas côté client, techniquement faisable en dix
lignes. `canvas.drawImage` ne rééchantillonne pas comme `INTER_AREA`, et pas pareil
selon le navigateur et le GPU : on obtiendrait des crops qui diffèrent selon la machine
de l'ami. Une pollution silencieuse du jeu d'entraînement — le genre de panne muette
contre laquelle la skill `eurio-verify` existe.

---

## D6 — DINO ne va ni sur le VPS ni dans le navigateur

**Décision.** Après un recadrage, le crop est marqué « DINO à réencoder » ; le Mac
rattrape en lot. Les suggestions DINO sont servies en **lecture pure** par le VPS.

> ⚠️ **Amendé le 2026-08-23 au soir — « marqué » ne veut PAS dire « retiré ».**
> La première implémentation (lot 6b) SUPPRIMAIT les prédictions du crop d'avant :
> l'absence servait de marqueur, sans colonne ni table. Réfuté par la première
> vraie session de review :
>
> > « moi je commence toujours par faire le recadrage et après je pick la bonne
> >   pièce. Souvent, la suggestion de Dino de base est bonne. »
>
> Le geste réel est un ajustement **au micro** du cadrage, suivi du choix de la
> pièce. Supprimer retirait l'aide juste avant le moment où elle sert, pour un
> recadrage qui ne la change presque jamais.
>
> **Corrigé par la migration 0013** (`stale_since`) : la prédiction reste servie
> et datée comme suspecte, l'écran dit « calculée avant ton recadrage », le
> backfill la réencode sans `--force`, et un ré-encodage lève la péremption.
>
> **Ce que l'erreur enseigne** : « le marqueur EST l'absence » était le plus
> élégant des deux designs, et le seul à ne rien coûter en schéma. Il supposait
> qu'une prédiction périmée ne vaut rien. Elle vaut souvent encore la bonne
> réponse — ce que seul l'usage pouvait dire.

**Pourquoi.** 0 crop sans prédiction persistée sur 21 223 : le fallback lourd ne
s'allume jamais. Et le recalcul post-recadrage est déjà *best-effort* dans le code.

**Ce que ça écarte.** (a) Un conteneur DINO CPU sur le VPS — gardé en réserve si
l'absence de suggestion fraîche après recadrage gêne à l'usage. (b) DINO dans le
navigateur : la banque passerait (7,8 Mo) mais elle est encodée en vitl14 (~300 M
paramètres) ; le seul modèle navigable, vits14, mesure 41,6-45,5 % contre 77,8 %. On
servirait aux amis un DINO deux fois moins bon.

---

## D7 — Quarantaine par scope, pas par rôle

**Décision.** Nouveau scope `review:arbitrate`, donné à `owner` et `admin` seulement.
Un principal qui ne l'a pas voit ses décisions atterrir dans `peer_review_decisions`
en `pending`, sans toucher `review_queue` ni `image_assets`.

**Pourquoi le scope et pas le rôle.** Les scopes effectifs sont `jeton ∩ rôles`. Avec
un scope, Raphaël se forge un PAT restreint et **vit toute l'expérience « Paolo » depuis
son propre compte** — donc les lots 1 à 7 se testent sans créer aucun compte Authentik.
Avec un rôle, il aurait fallu un second utilisateur pour tester quoi que ce soit.

**Ce que ça écarte.** La confiance réglable par personne, reportée : le calcul existe
déjà (`/peer-arbitration/reviewers`) mais tournerait à vide — `peer_review_decisions`
contient 0 ligne. On décidera quand Paolo aura trois cents décisions derrière lui,
sur des données plutôt que sur un pari.

---

## D8 — La vue bulk trie les désaccords en tête, et ne les coche pas

**Décision.** Tout coché par défaut **sauf** les désaccords avec DINO, placés en tête.

**Pourquoi.** « Tout validé par défaut » sur un scroll infini, c'est un tampon en
caoutchouc : le geste devient « je scrolle vite et je clique OK ». Or 62,6 % des
décisions rejoignent DINO top-1 (67,3 % avec le re-rank pays) : les deux tiers
concordants peuvent défiler vite, et le tiers restant — celui où l'humain contredit la
machine, donc celui où il y a quelque chose à apprendre — exige un geste positif.

**Précédent réutilisé.** `AutoAcceptReviewPage.vue` fait déjà tout ça, garde
`BULK_CONFIRM_THRESHOLD` comprise.

---

## D9 — Le recadrage prend effet immédiatement

**Décision.** `apply_manual_crop` écrase le crop dans MinIO tout de suite. La vue bulk
affiche le crop **recadré**, donc l'arbitrage juge le cadrage et la classe d'un coup.

**Ce que ça écarte.** (a) Conserver l'ancien crop sous une autre clé pour rendre le
recadrage réversible — coût de stockage et une colonne, pour un geste qui améliore
presque toujours. (b) Mettre le recadrage en quarantaine comme la décision : l'ami ne
verrait pas le résultat de son propre geste, et DINO n'aurait rien à réencoder.

**Asymétrie assumée.** Rejeter la décision d'un ami ne défait pas son recadrage.

---

## D10 — Le nettoyage est un lot final, pas un fil au fur et à mesure

**Décision.** Suppression du code et de la doc morts en un lot, une fois les lots 1-8
vérifiés. L'inventaire est tenu à jour en continu dans [`NETTOYAGE.md`](NETTOYAGE.md).

**Pourquoi.** Supprimer au fil de l'eau ferait tomber `eurio-review.musubi.dev` avant
que son remplaçant soit prouvé. Mais découvrir l'inventaire à la fin, c'est en oublier
la moitié — d'où le fichier tenu dès maintenant.

---

## D11 — Un ami ne doit jamais voir le mot « local », ni un numéro de port

> ✅ **Appliqué le 2026-08-23** — la règle vit dans
> `shared/composables/useHeavyGate.ts` (`showHeavyGesture = canRunHeavy ||
> canArbitrate`), vérifiée au DOM sur les deux profils. Détail :
> [`ROADMAP.md`](ROADMAP.md) §D11.

**Constaté en production le 2026-08-23**, par le PO, avec un vrai compte reviewer :
« pour faire la review, on nous dit que c'est en local ».

**Cause exacte**, diagnostiquée : la page `/review` (`ReviewDashboardPage`) propose
DEUX entrées — `/review/manual` et `/review/auto-accept`. La seconde porte encore
`meta: heavy` **et** relève de l'arbitre. Un ami clique dessus et tombe sur la page
pleine « Cette vue tourne en local ». Le lot 5 avait masqué le *bouton* `AUTO-ACCEPT`
dans la barre de review, pas la *carte* du tableau de bord — l'entrée n'avait pas été
regardée.

**Décision.** Pour un principal SANS `review:arbitrate` :
1. les entrées qui mènent à une vue `heavy` ne sont **pas proposées** ;
2. les contrôles gatés par la machine sont **masqués**, pas grisés — un ami ne peut
   rien faire d'une infobulle « disponible uniquement en local (API ML :8042) » ;
3. aucun texte visible ne mentionne « local », `:8042`, ni un nom de machine.

**Ce que ça écarte, et pourquoi c'est un revirement partiel du lot 5.** Le lot 5 avait
tranché « ce qui est hors de portée reste visible et grisé », pour dire à l'utilisateur
que le geste existe ailleurs. C'est le bon rendu **pour l'arbitre sur son poste** — il
sait ce qu'est `:8042` et il peut y aller. Ce n'est pas le bon pour un ami : le geste
n'existera jamais pour lui *tant que 6b n'est pas fait*, et un bouton mort qui parle
de port est du bruit inquiétant. Le grisé RESTE pour qui a `review:arbitrate`.

**Le vrai remède reste le lot 6b** : quand le recadrage tournera sur le VPS, il n'y
aura plus rien à masquer. D11 est ce qu'on fait en attendant — et ce qui restera vrai
pour les rares gestes qui resteront à jamais locaux.

**Ce que 6b a effectivement retiré** (même journée) : le recadrage n'est plus gaté
du tout, ni masqué ni grisé — il marche pour un ami. Ce que D11 continue de masquer
est donc ce qui restera local pour de bon : la DÉTECTION (auto-crop, re-détecter,
sync crops, crop manuel), qui charge un modèle. La décision ne perd pas son objet
en devenant plus étroite — elle gagne en précision : on masque ce qui n'arrivera
jamais, on ne masque pas ce qui n'est pas encore arrivé.
