# Crop Forensics — Cerveau d'orchestrateur

> **Tu lis ceci en début de session.** Charge les 5 fichiers de ce dossier
> dans l'ordre, puis exécute la **prochaine étape** de `plan.md`. Pas
> plus. Si tu doutes du périmètre, demande à Raphaël avant de coder.
>
> Ce dossier EST ton cerveau persistant entre sessions. Il **doit**
> évoluer : à la fin de chaque session, mets à jour `plan.md` et
> `evolution-log.md` pour que la session suivante hérite de ton état.

## Ordre de lecture (~5 min)

1. [`personality.md`](./personality.md) — qui tu es, ton rôle, ta voix
2. [`vision.md`](./vision.md) — but du chantier, critères de succès, état de l'art
3. [`plan.md`](./plan.md) — sessions numérotées à exécuter (mutable)
4. [`workflow.md`](./workflow.md) — protocole opérationnel (MCP, subagents, screenshots, commit/kill)
5. [`evolution-log.md`](./evolution-log.md) — découvertes passées qui ont muté le plan

Puis charge la session courante depuis `plan.md` (la 1ère entrée non
marquée ✅), et exécute son **objectif unique**.

## Kickoff verbatim (à coller dans Claude au début d'une session)

```
Charge le cerveau orchestrateur :
  docs/crop-forensics/orchestrator/README.md

Puis lis dans l'ordre les 5 fichiers du dossier, identifie la prochaine
session non-✅ dans plan.md, et exécute-la selon workflow.md. À la fin :
update plan.md + evolution-log.md, commit, propose le pas suivant.
```

## Règles dures

- **Petits fichiers** : aucun fichier orchestrateur > ~150 lignes. Split.
- **Pas de surcharge contexte** : pour les lectures volumineuses
  (transcripts, gros JSONs, logs), délègue à un subagent
  (`Explore` / `general-purpose`) avec instruction de retour synthétique.
- **Mesure ou tais-toi** : aucune théorie ne passe sans expérience
  visuelle (chrome-devtools screenshot + œil) ou numérique (script +
  assertion). Si tu ne peux pas mesurer, déclare-le explicitement.
- **Un objectif par session** : ne pas empiler. Si une session déborde,
  marque le reste dans `plan.md` comme session N+1.
- **Commit après chaque chunk fini**. Pas de batch géant en fin de
  session — Raphaël veut voir le diff par étape.
- **Tu mens jamais sur le résultat**. Une expé inconcluante reste
  inconcluante ; tu ne forces pas le verdict pour avancer.
