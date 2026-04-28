# Eurio — Status

> **À quoi sert ce doc** : reprendre une session froide sans faire d'erreur. Photo instantanée de où on en est. Pas de détail, pas de journal — juste ce qui est fait, ce qui reste, et les gotchas à connaître.
>
> **Dernière mise à jour** : 2026-04-13
> **Pour l'overview complète** : [`ARCHITECTURE.md`](./ARCHITECTURE.md)

---

## Où on en est

**La data layer est production-ready.** Le référentiel canonique (2 938 pièces euro) est bootstrapped, enrichi par 6 sources, et synchronisé vers Supabase. Le tooling de review humaine est en place. **Ce qui reste bloquant pour la beta** : entraîner le modèle ML pour le scan utilisateur (Phase 2B) et construire les écrans Android pour le coffre (Phase 3).

---

## ✅ Fait

| Phase | Résumé | Doc de référence |
|---|---|---|
| **Phase 0 — Setup** | flake.nix, projet Android Kotlin+Compose, CameraX, LiteRT, Supabase projet | [`ARCHITECTURE.md`](./ARCHITECTURE.md) §6 |
| **Phase 1 — ML v1 POC** | Classification 5 classes MobileNetV3, 80% val accuracy, TFLite exporté, scan Android fonctionnel | mémoire `project_phase1_decisions.md` |
| **Phase 1B — YOLO détection** | Tentative YOLOv8n, faux positifs massifs sur dataset réel, **à retravailler** ou abandonner | `docs/research/yolo-detection-findings.md` (ancien) |
| **Phase 2B.1 — ArcFace 5 classes** | Validation de l'approche metric learning : R@1 100% sur 5 pièces | journal historique ci-dessous |
| **Phase 2C.1a — Bootstrap commémoratives** | 517 entrées 2€ commemo depuis Wikipedia | [`phase-2c1-review.md`](./research/phase-2c1-review.md) |
| **Phase 2C.1b — Bootstrap circulation** | 2 374 entrées circulation 24 pays depuis Wikipedia | idem |
| **Phase 2C.1c — DE Auflagen** | 122 entrées DE 2002-2024 depuis de.wikipedia (détail par mint A/D/F/G/J) | [`phase-2c-referential.md`](./phases/phase-2c-referential.md) §2C.1c |
| **Phase 2C.2 — Scraper lmdlp** | 268 coins enrichis via WooCommerce Store API, 73% match auto | [`phase-2c2-lmdlp-run.md`](./research/phase-2c2-lmdlp-run.md) |
| **Phase 2C.3 — Scraper Monnaie de Paris** | 5 coins enrichis avec prix d'émission officiel, 100% match | [`phase-2c3-mdp-run.md`](./research/phase-2c3-mdp-run.md) |
| **Phase 2C.4 — Scraper eBay** | 30 coins enrichis avec P25/P50/P75 velocity-weighted, 30 API calls | [`phase-2c4-ebay-run.md`](./research/phase-2c4-ebay-run.md) |
| **Phase 2C.5 — Review tool** | Web server local avec images BCE side-by-side + 419 images canoniques scrapées | [`phase-2c5-review-tool-run.md`](./research/phase-2c5-review-tool-run.md) |
| **Phase 2C.7 — Sync Supabase** | Drop legacy schema + 6 tables canoniques + RLS + script idempotent | [`phase-2c7-supabase-sync-run.md`](./research/phase-2c7-supabase-sync-run.md) |

**Datum référentiel** : 2 938 coins · 3 695 observations · 419 avec images BCE · 197 items en review queue · 1 771 matching decisions · 83 tests unitaires verts.

---

## 🔄 En cours

- **Phase 2A — Classification bridge** (fine-tuning MobileNetV3-Small sur ~500 classes du catalogue) — travail ML actif avant de passer à ArcFace 500+.

---

## ⏳ À faire ensuite (ordre recommandé)

1. **Phase 2B — ArcFace 500+ classes** — training + export TFLite + `coin_embeddings.npy` pré-calculé. Bloque le scan utilisateur réel ET la Phase 2C.6 (Stage 4 visual matching).
2. **Phase 3 — Coffre Android** — écrans Kotlin Compose, branchement Supabase via supabase-kt, collection user. Peut avancer en parallèle de 2B.
3. **Phase 2C.6 — Stage 4 visual** — brancher ArcFace dans `matching.py::match()` pour résoudre les escalades FR↔EN restantes. Dépend de Phase 2B.
4. **Phase 2C.8 — Enrichissement multi-sources + admin** — URL BCE cross_refs, sync bce_comm → Supabase, mintage BCE+Numista, images BCE download, LMDLP prix avec qualité, filtres cumulables `/coins`. Voir [`docs/phases/phase-2c8-enrichment-admin.md`](./phases/phase-2c8-enrichment-admin.md).
5. **Phase 2C — Review manuelle de la queue** — 121 groupes uniques à trancher dans le web tool, ~20 min. Optionnel, pas bloquant.
6. **Phase 4 — Gamification** — achievements, series completion, streak. Dépend de Phase 3.
7. **Phase 5 — Polish + beta** — UI finale, onboarding, beta closed puis ouverte.

---

## ⚠️ Gotchas — à NE PAS oublier en reprenant

1. **Le référentiel canonique est la source de vérité, pas Numista.** L'ancienne approche (Numista IDs comme PK, `coin_catalog.json`) est **superseded** depuis le 13 avril. Utiliser `eurio_id` partout.
2. **Supabase schema a été reset le 13 avril.** Les anciennes tables (`coins UUID`, `price_history`, ...) n'existent plus. Les 6 tables canoniques sont : `coins`, `source_observations`, `matching_decisions`, `review_queue`, `coin_embeddings`, `user_collections`. Voir [`ARCHITECTURE.md`](./ARCHITECTURE.md) §6.2.
3. **Bootstrap merge pattern** — les 3 scripts `bootstrap_*.py` préservent maintenant `images`, `design_description` et `sources_used` sur re-run. Quand on ajoute un nouveau champ enrichi au schema canonique, il faut étendre le merge (bug corrigé en 2C.7, à surveiller).
4. **scrape_lmdlp filtre les bundles et multipacks** au scrape time (`^N x 2 euros` et ` + ` entre thèmes). Ne pas re-introduire.
5. **Tests = stdlib `unittest`** uniquement, pas de pytest. Lancer `python ml/test_eurio_referential.py`.
6. **Scan UX = QR scanner** — continuous auto-scan, zéro bouton, zéro guide visuel. Style Yuka.
7. **Ne jamais créer d'entrée canonique automatiquement** depuis un scraper. Seul le bootstrap officiel peut. Les collisions vont dans `review_queue`, pas en auto-suffixe `-v2`.
8. **eBay Finding API est morte** (décommissionnée février 2025). Utiliser Browse API + velocity weighting (`ebay_client.py` + `scrape_ebay.py`).
9. **Numista API a un rate limit 2000 calls/mois** (plan gratuit, épuisé en avril 2026) et **n'expose aucun prix**. Ne pas compter dessus pour le live.
10. **Toutes les deps passent par `flake.nix`** — pas de `brew install`, pas de `pip install` hors `ml/.venv/`. Si un package manque, ajouter à `flake.nix`.

---

## Docs de référence par niveau de profondeur

- **Overview 15 min** → [`ARCHITECTURE.md`](./ARCHITECTURE.md)
- **Vision produit** → [`PRD.md`](../PRD.md) (en cours d'absorption vers ARCHITECTURE.md)
- **Data model spec** → [`docs/research/data-referential-architecture.md`](./research/data-referential-architecture.md)
- **Phase 2C plan & sous-phases** → [`docs/phases/phase-2c-referential.md`](./phases/phase-2c-referential.md)
- **Run reports détaillés** → `docs/research/phase-2c{1..7}-*.md` (un par sous-phase)
- **Décisions écosystème** → `docs/research/euro-ecosystem-map.md`, `ebay-api-strategy.md`, `referential-bootstrap-research.md`
- **Mémoires Claude** → `~/.claude/projects/-Users-musubi42-Documents-Musubi42-Eurio/memory/MEMORY.md`

---

## Journal historique (avant 2026-04-13)

Le contenu retrospective détaillé de Phase 0, Phase 1, Phase 1B, Phase 2B.1 (ArcFace 5 classes) était dans ce fichier jusqu'au 13 avril — avec les métriques, les décisions prises, les écarts par rapport au plan. Tout est archivé côté mémoire Claude (`project_phase1_decisions.md`) et référencé dans les mémoires du projet. On garde ce doc focalisé **présent + futur** pour ne pas le laisser grossir indéfiniment.
