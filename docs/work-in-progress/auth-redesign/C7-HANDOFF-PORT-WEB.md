# C7 — Panel : portage complet de `admin/packages/web/` (split C7a + C7b)

> **But (1 phrase)** : reproduire dans le panel **tous** les écrans utiles de
> `admin/packages/web/`, en remplaçant **chaque** appel Supabase direct par un
> appel `eurio-api` équivalent (et créer les endpoints `ml/serving/` manquants
> au passage).
>
> **Ne fait PAS** : décommissionner `admin/packages/web` Vercel (C9), ni l'UI
> Users/Tokens (C8). Ne touche pas non plus au schéma Supabase — la DB est
> préservée intégralement, seule la **voie d'accès** change (browser → Vercel
> → Supabase  ⇒  browser → panel → eurio-api → Supabase service-role).
>
> **All-in (cf. DESIGN.md D9)** : tous les écrans doivent être portés. On ne
> garde pas une moitié sur Vercel. Si un écran legacy obscur n'est pas porté,
> il doit être **explicitement listé** dans le résumé et tranché avec
> l'opérateur **avant** C9 (archive ou portage tardif, jamais ignoré).

## 0. Pré-requis

- C5 ✅ — panel shell.
- C2 ✅ — auth + Principal.
- Branche : `auth-redesign-c7a` (puis `auth-redesign-c7b`).

## 0.1 Split obligatoire

L'audit cohérence 2026-06-19 a montré que `admin/packages/web/src/` contient
~18 features admin appelant Supabase directement. Faire C7 en un seul chunk =
~3000-5000 LoC à produire. **Split en deux chunks séquencés** :

- **C7a — Editorial core** : surfaces les plus directes, schéma stable, peu de
  logique métier complexe.
- **C7b — Sets & analytics** : surfaces avec preview live, design groups,
  confusion maps, parity, lab — chacune avec sa propre dette d'endpoints.

## 0.2 Audit préalable (à faire en début de C7a)

```bash
# Lister tous les écrans réels
ls -la admin/packages/web/src/features/

# Lister tous les appels Supabase à porter
grep -rn "supabase\." admin/packages/web/src/ | grep -v node_modules | sort -u

# Lister les composables qui consomment Supabase
grep -rln "import.*supabase" admin/packages/web/src/

# Vérifier ce qui existe déjà côté ml/serving/
ls -la ml/serving/*_routes.py
```

Reporter le résultat **en haut du résumé** : un compteur "X écrans, Y appels
supabase à supprimer, Z routes API existantes".

## 0.3 Service-role Supabase — pas un risque "exposée" en prod

Contrairement à ce qu'a pu suggérer l'inventaire historique (`HANDOFF.md §1`
non corrigé), la clé service-role n'est **pas dans le bundle Vercel prod** :
`admin/packages/web/src/shared/supabase/client.ts:27-38` la gate sous
`import.meta.env.DEV` — elle est tree-shakée hors du bundle de production.
**Priorité = correcte, pas urgente** : on supprime cet usage entièrement à C9
en même temps que le projet Vercel, pas avant.

---

## C7a — Editorial core

### A1. Surfaces à porter

| Surface | Écrans | État côté `ml/serving/` |
|---|---|---|
| **Sources** | list, create, edit, status, scrape trigger | ❌ à créer `sources_routes.py` |
| **Coins (référentiel)** | list, search, detail, edit metadata, upload images | ❌ à créer `coins_routes.py` |
| **Audit — coins** | logs d'ingest par coin, anomalies | ❌ à créer `audit_routes.py` |
| **Audit — decisions** | historique des décisions reviewer, export | ❌ à créer (ou sous-section `audit_routes.py`) |
| **Audit — export** | dump CSV/JSON paramétrable | ❌ à créer |
| **Referential** | countries, issuers, series, denominations (lookup + édition) | ❌ à créer `referential_routes.py` |

L'inventaire ci-dessus est à **vérifier et compléter** lors du `ls -la admin/packages/web/src/features/` (étape 0.2). Si une surface non listée apparaît, l'ajouter à C7a si elle est éditoriale (lecture/écriture simple), sinon la basculer à C7b.

### A2. Pattern de portage (par surface)

1. **Lister** les composables Vue de la surface (`useXxxApi.ts`).
2. **Lister** les requêtes Supabase qu'ils font (`.from('table').select(…)`, `.insert(…)`, `.update(…)`, RPC).
3. **Créer** l'endpoint `eurio-api` équivalent dans `ml/serving/<surface>_routes.py` :
   - GET liste + filtres → `GET /<surface>/`
   - GET détail → `GET /<surface>/{id}`
   - POST création → `POST /<surface>/`
   - PUT/PATCH édition → `PUT /<surface>/{id}`
   - DELETE → `DELETE /<surface>/{id}`
   - Scopes appliqués via `Depends(require_scope("..."))`.
   - Le code lit/écrit Supabase via `supabase_client.py` côté serveur (service-role en SOPS sur VPS).
4. **Reproduire** l'écran dans `admin/packages/panel/src/views/<surface>/`, en consommant le nouveau endpoint via `api/client.ts`.
5. **Tester** parité visuelle + parité fonctionnelle (création / édition / suppression).
6. **Ne pas toucher** au schéma Supabase. Si l'écran a besoin d'une donnée non disponible, la lire via une `supabase.rpc(...)` existante ou ajouter une vue Postgres en lecture seule (commit séparé, justifié).

### A3. Critères d'acceptation C7a

- Toutes les surfaces du tableau A1 sont portées.
- `grep -rn "supabase\." admin/packages/panel/src/` → **0 résultat**.
- `pnpm --filter panel build` produit un bundle sans aucune référence à `@supabase/supabase-js` (`grep -r supabase dist/`).
- Smoke tests fonctionnels documentés : créer une source, éditer un coin, voir un audit log, exporter.
- `admin/packages/web/` legacy **reste déployable** et utilisable en parallèle jusqu'à C9.

---

## C7b — Sets & analytics

### B1. Surfaces à porter

| Surface | Écrans | État côté `ml/serving/` |
|---|---|---|
| **Sets** | list, create, edit (DSL), preview, publish | ✅ partiel — `sets_routes.py` existe, vérifier la couverture |
| **Criteria preview (live)** | éval temps réel d'un critère contre la base coins | ❌ à créer (`POST /sets/preview` ?) |
| **Design groups** | groupes de visuels équivalents (avers/revers), matching | ❌ à créer `design_groups_routes.py` |
| **Confusion** | confusion maps coin↔coin, edition manuelle | ❌ à créer `confusion_routes.py` |
| **Fragment audit** | qualité des fragments OCR/Vision, filtre par denom | ❌ à créer `fragment_audit_routes.py` |
| **Crop recovery** | re-crop par lot, file d'attente | ❌ à créer `crop_recovery_routes.py` |
| **Denom gold** | jeu de référence "or" par dénomination | ❌ à créer `denom_gold_routes.py` |
| **Parity** | parité proto ↔ Android (tables/screenshots) | ❌ à créer `parity_routes.py` (ou rester local-only ? trancher) |
| **Lab** | écrans expérimentaux, à inventorier | ❌ à inventorier et trancher au cas par cas |

### B2. Pattern de portage

Idem C7a §A2. Particularités :

- **Criteria preview live** : si la préview est latency-critical (debounce 200ms), l'endpoint `eurio-api` doit être rapide. Cache en mémoire si nécessaire.
- **Design groups + confusion** : ces écrans manipulent souvent des images depuis MinIO. Le serveur signe les URLs côté `eurio-api` (`get_object_presigned_url`) plutôt que d'exposer les creds MinIO au browser.
- **Parity** : si la feature dépend d'outils Playwright/screenshots local-only, on peut décider de la **garder en `admin/packages/parity/`** (déjà séparé du workspace web) et ne pas la porter dans le panel. À trancher dans le résumé.

### B3. Critères d'acceptation C7b

- Toutes les surfaces du tableau B1 sont portées **ou explicitement marquées "non portée" avec justification** dans le résumé.
- `grep -rn "supabase\." admin/packages/panel/src/` → toujours 0 résultat après C7b.
- Pas de régression sur les écrans portés en C7a.
- L'opérateur a pu utiliser au moins une fois chaque écran porté pendant la phase de coexistence test.

---

## 5. Garde-fous transverses C7

- Si un écran legacy faisait une chose qu'on n'a pas le temps de porter
  proprement : **lister** dans le résumé et trancher avec l'opérateur avant
  C9. Ne pas silently dropper.
- Garder `admin/packages/web` legacy déployable jusqu'à C9 pour fallback.
- **Aucune migration Supabase** dans C7. Aucun DROP. La voie d'accès change,
  pas la donnée.
- Si un endpoint `eurio-api` nouveau a besoin d'une lecture Supabase complexe
  (jointures, RPC), préférer une vue Postgres en lecture seule plutôt que
  d'imbriquer du SQL ad-hoc dans le code Python.

## 6. Résumé à produire (par chunk)

```
## C7a — résumé portage editorial core

- Inventaire écrans + appels supabase (compteur) : <…>
- Surfaces portées : sources / coins / audit-coins / audit-decisions / audit-export / referential
- Endpoints API créés côté ml/serving/ : <liste>
- Build panel sans supabase : OUI/NON
- Tests fonctionnels : <…>
- Surfaces non portées (à trancher) : <…>
- Déviations / open questions pour C7b : <…>

## C7b — résumé portage sets & analytics

- Surfaces portées : sets / criteria-preview / design-groups / confusion / fragment-audit / crop-recovery / denom-gold / parity / lab
- Endpoints API créés côté ml/serving/ : <liste>
- Parity : portée OUI/NON (justifier si NON, ex : reste en admin/packages/parity)
- Lab : surfaces gardées / archivées / portées : <…>
- Build panel sans supabase : OUI/NON
- Tests fonctionnels : <…>
- Surfaces non portées (à trancher avec opérateur avant C9) : <…>
```
