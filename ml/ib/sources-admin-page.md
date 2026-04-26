---
title: Prompt — session de design de la page Sources admin
date: 2026-04-26
status: prompt prêt à copier-coller dans une nouvelle session
---

# Prompt nouvelle session — page Sources admin

---

## Contexte projet

Eurio est une app Android de collection de pièces euro. L'acte central est le scan (identifie une pièce par caméra). Tout le pipeline de données est en Python dans `ml/`, l'admin web est en Vue/Vite dans `admin/packages/web/`.

Le projet a un monorepo :
```
ml/                         # Python standalone
  market/ebay_client.py     # OAuth + Browse API client
  market/scrape_ebay.py     # pipeline prix eBay (--all-commemos --requires-numista --sync-supabase)
  referential/import_numista.py    # fetch métadonnées + images Numista
  referential/numista_keys.py      # gestion quota Numista (SQLite, _MONTHLY_LIMIT=1800)
  referential/eurio_referential.py # référentiel JSON local (~500+ pièces)
  api/server.py             # FastAPI (sert l'admin en local)
  state/store.py            # SQLite store (training state + numista quota)
  ib/ebay-market-prices.md  # stratégie eBay + données empiriques des runs

admin/packages/web/src/
  app/nav.ts                # navigation centralisée
  features/coins/           # page liste + fiche pièce (Supabase)
  shared/supabase/client.ts # client Supabase JS
```

**Sources de données actuelles :**
| Source | Rôle | Quota |
|---|---|---|
| Numista API | Métadonnées canoniques, images, numista_id | 1800 calls/mois (soft limit SQLite) |
| eBay Browse API | Prix de marché P25/P50/P75 | 5 000 calls/jour |
| LMDLP | Variantes + mintage (scraping HTML) | pas de limite connue |
| Monnaie de Paris | Prix d'émission (scraping HTML) | pas de limite connue |
| BCE | Images officielles | pas de limite connue |
| Wikipedia | Mintage | pas de limite connue |

**Ce qui existe déjà côté quota tracking :**
- Numista : `KeyManager.quota_status()` → calls_this_month, remaining, exhausted — stocké SQLite
- eBay : `EbayClient.call_count` compteur en mémoire par run seulement — pas persisté

---

## Le problème

Tous les fetches/scrapes se font en CLI local. C'est correct pour un POC, mais pour entretenir le projet sur la durée, il manque :

1. **Une vue d'état globale** — quand a-t-on fetchés chaque source pour la dernière fois ? Combien de pièces sont couvertes par chaque source ? Combien de quotas reste-t-il ?
2. **Des contrôles** — pouvoir déclencher un fetch depuis l'admin plutôt que d'ouvrir un terminal
3. **De la traçabilité** — historique des runs avec date, calls consommés, pièces enrichies

---

## Ce qu'on veut designer ensemble

Une nouvelle page admin — probablement `/sources` dans `admin/packages/web/` — qui serve de **panneau de contrôle des sources de données**.

### Questions ouvertes à trancher en session

1. **Granularité de la page :** une seule page `/sources` avec toutes les sources, ou des sous-pages par source (`/sources/ebay`, `/sources/numista`) ?

2. **Contenu exact de la vue d'état :**
   - Dernière date de fetch par source (d'où vient cette info ? Supabase ? SQLite ? referential.json ?)
   - Couverture : X pièces enrichies sur Y total — par source
   - Quotas restants : Numista c'est déjà dans SQLite via `quota_status()`, eBay c'est à construire

3. **Déclenchement de fetch depuis l'UI :**
   - Le FastAPI (`ml/api/server.py`) pourrait exposer des endpoints POST `/sources/ebay/fetch`, `/sources/numista/fetch`
   - Ces endpoints lancent les scripts en subprocess ou asyncio
   - L'admin appelle ces endpoints — mais attention : les fetches prennent des minutes, il faut un pattern job async (SSE ou polling de statut)
   - Est-ce qu'on veut ça maintenant, ou juste l'affichage d'état sans bouton de déclenchement pour commencer ?

4. **Suivi quota eBay :**
   - Option A : table SQLite `ebay_run_log (run_at, calls_consumed, coins_enriched)` — simple, cohérent avec Numista
   - Option B : interroger l'eBay Analytics API getRateLimits — dépendance externe, mais donnée authoritative
   - Option C : pas de suivi eBay pour l'instant (quota 5 000/jour est confortable)

5. **Notifications futures :**
   - Nouvelle pièce 2€ émise → d'où vient l'info ? RSS des mints nationaux ? Numista ? BCE ?
   - Ce n'est pas à implémenter maintenant mais la page doit pouvoir l'accueillir dans le futur

---

## Fichiers clés à lire avant de designer

```
ml/referential/numista_keys.py        # quota_status(), _MONTHLY_LIMIT
ml/market/scrape_ebay.py              # args + structure du run eBay
ml/api/server.py                      # endpoints FastAPI existants
admin/packages/web/src/app/nav.ts     # pour voir où insérer /sources
admin/packages/web/src/features/      # pour voir le pattern d'une feature admin
ml/ib/ebay-market-prices.md           # stratégie + données empiriques eBay
```

---

## Résultat attendu de la session

À la fin de la session de design, on doit avoir :
- Le périmètre exact de la page (ce qu'elle affiche, ce qu'elle ne fait pas)
- Le schéma des données qu'elle consomme (SQLite ? Supabase ? JSON local ?)
- La décision sur le suivi quota eBay
- La décision sur le déclenchement depuis l'UI (maintenant ou plus tard)
- Et idéalement, l'implémentation de la page
