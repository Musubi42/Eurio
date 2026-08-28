"""App serve-role du canonique sur le VPS (Modèle B, chunk C4).

FastAPI LÉGER : writer unique de ``eurio.db`` (volume ``EURIO_DB_PATH``). Monte un
**cœur garanti** (``/healthz`` + auth + ``/ingest/run``) puis les routers
interactifs légers en **best-effort** — tout router dont une dépendance lourde
(cv2/torch/dino…) manque sur l'image lean est **skippé** et journalisé (no CV/ML
sur le VPS, cf. DESIGN.md). Le log de démarrage liste ``montés`` / ``skippés``.

NE PAS confondre avec ``serving/server.py`` (app FULL workstation). Ici aucun
router de calcul lourd n'est exposé.

RÈGLE DE SYNCHRONISATION FULL ↔ LEAN
--------------------------------------
``serving/server.py`` (FULL, workstation Mac/PC) et ce fichier (LEAN, image VPS)
partagent les mêmes routers légers mais divergent intentionnellement sur les
routers lourds (cv2/torch/dino uniquement disponibles sur la workstation).

Lorsqu'un nouveau router est ajouté dans ``server.py`` :
  • S'il est léger (pas de cv2/torch/dino) → l'ajouter également ici en mount
    inconditionnel (section « Cœur garanti » ou bloc direct comme coin_series).
  • S'il est lourd (cv2/torch/dino) → l'ajouter dans ``_CANDIDATES`` ci-dessous ;
    l'image lean le skippera automatiquement à l'ImportError.

Ne jamais supprimer un router de ``_CANDIDATES`` sans le retirer aussi de ``server.py``.
"""
from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from serving import auth as api_auth
from serving import (
    audit_routes,
    auth_routes,
    confusion_routes,
    crop_gold_routes,
    db_migrate,
    db_routes,
    ingest_routes,
    review_routes,
    stats_routes,
    tokens_routes,
    users_routes,
)
from serving.auth_principal import (
    require_principal,
    require_scope,
    require_scope_by_method,
)
# La politique d'accès vit à part : elle doit être lisible et testable sans
# démarrer un serveur (cf. son en-tête).
from serving.router_scopes import RECIPE_SCOPES, ROUTER_SCOPES
from serving.coin_series import router as coin_series_router
from serving import iteration_sync_routes, recipe_routes, whoami_routes
from serving.review_queue import router as review_queue_router
from serving.review_queue.crop_routes import router as review_crop_router
from serving.review_queue.writes import router as review_writes_router
from serving.funnel_writes import router as funnel_writes_router
from serving.lab_read_routes import router as lab_read_router
from serving.dino_thresholds_routes import router as dino_thresholds_router
from serving.encoder_bench_routes import router as encoder_bench_router
from serving.class_need_routes import router as class_need_router
from serving.me_review_stats_routes import router as me_review_stats_router
from serving.thresholds_routes import router as thresholds_router
from serving.sources import router as sources_router
from store import Store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("eurio-api")

_DB_PATH = Path(os.environ.get("EURIO_DB_PATH", "/var/lib/eurio/eurio.db"))

# Migrations idempotentes appliquées AVANT que Store n'ouvre la connexion.
# Couvre les nouvelles tables auth (users/roles/user_roles/api_tokens/auth_audit
# — cf. auth-redesign C2). Les tables existantes (training_*, etc.) sont
# gérées par Store via state/schema.sql.
_applied = db_migrate.run_migrations(_DB_PATH)
if _applied:
    log.info("db_migrate: applied %d migration(s): %s", len(_applied), _applied)

# read_only=False EXPLICITE : ce process est le writer canonique unique
# (Direction A) — il doit rester inscriptible même si un EURIO_DB_READONLY
# traîne dans l'environnement (le défaut StoreBase résout ce flag).
_store = Store(_DB_PATH, read_only=False)
api_auth.bind(_store)

# Boot guard : refuse de démarrer si EURIO_DEV_BYPASS=1 dans un contexte prod.
auth_routes.assert_dev_bypass_safe()

app = FastAPI(title="Eurio API (serve)", version="0.1.0", docs_url="/docs")

_origins = [o for o in os.environ.get("EURIO_API_CORS_ORIGINS", "").split(",") if o]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        # credentials=True nécessaire pour le cookie eurio_session côté panel.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Routes auth OIDC + identité (sans `require_token` legacy — elles ont leur
# propre dep `require_principal` ou sont publiques pour le flow).
app.include_router(auth_routes.router)
app.include_router(users_routes.router)
app.include_router(tokens_routes.router)
app.include_router(review_routes.router)
app.include_router(confusion_routes.router)
app.include_router(audit_routes.router)
# D2 data-layer-unification : domaine `coin_series` (READ) layered, scope
# coins:read — remplace le dernier supabase.from('coin_series') de studio-local.
app.include_router(coin_series_router)
# Recettes d'augmentation (CRUD) : métadonnée PURE (nom/zone/JSON), servie par le
# writer canonique → une recette créée sur Mac/PC atterrit dans la DB canonique et
# reste récupérable partout. Léger (Store + validateur pur, sans cv2) → mount
# inconditionnel sur l'image lean. Le rendu lourd (/augmentation/preview) reste
# sur le ML local :8042. Scope aligné sur les autres routes protégées.
recipe_routes.bind(_store)
# Lot 4b : `require_principal` nu laissait un `reviewer` créer/supprimer des
# recettes d'augmentation. Métadonnée de lab → lecture `lab:read`, écriture
# `training:run`.
app.include_router(
    recipe_routes.router,
    dependencies=[Depends(require_scope_by_method(*RECIPE_SCOPES))],
)
# R3 (Model B) : itérations canoniques — état (métadonnée + métriques
# dénormalisées) partagé Mac↔PC. Router léger (Store + validateur pur). Scopes
# PAR-ROUTE (lab:read en lecture, ingest:write pour l'upsert poussé par le
# compute) déjà déclarés dans le module → pas de dep globale ici.
iteration_sync_routes.bind(_store)
app.include_router(iteration_sync_routes.router)
# /whoami : origine machine (mac/pc/vps) + principal optionnel. Public (ne 401
# jamais) — le front s'en sert pour gater les actions lourdes hors machine d'origine.
app.include_router(whoami_routes.router)
# F9 dashboard KPIs : compteurs read-only agrégés, filtrés par scope (lean).
app.include_router(stats_routes.router)
# Phase 2b data-layer-unification : domaine `sources` (READ) layered, sans
# dépendances ML lourdes — mount inconditionnel sur l'image lean.
app.include_router(sources_router)
# Phase 2c data-layer-unification : domaine `review_queue` (READ) layered.
# Endpoints heavy (manual-crop, dino-suggestions, auto-crop) restent dans le
# legacy `review.review_queue_routes` (skipped sur lean image via cv2).
app.include_router(review_queue_router)
# Auto-acceptation — module LEAN dédié (2026-08-27). Monté par les DEUX
# serveurs : il porte un seul chemin, donc aucun doublon avec le module
# lourd, d'où la route a été retirée.
from serving.review_queue.auto_accept import (  # noqa: E402
    router as auto_accept_router,
)
app.include_router(auto_accept_router)
# TC2 (Model B) : écritures review (decide/skip/reject/restore) SQL-pures, cv2-free
# → servies sur l'image lean (scope review:write). Le full app `server.py` garde le
# legacy `review.review_queue_routes` (mêmes paths + crops cv2) → ne PAS monter ici-bas
# dans server.py (routes dupliquées).
app.include_router(review_writes_router)
# Lot 6b (review-collaborative-v2) : le RECADRAGE, servi par le canonique.
# `opencv-python-headless` est dans l'image (D5) — les pixels restent au serveur
# parce que `canvas.drawImage` ne rééchantillonne pas comme `INTER_AREA`. DINO,
# lui, ne monte PAS (D6) : le crop recadré voit ses prédictions MARQUÉES périmées
# (`stale_since`, migration 0013) — toujours servies, l'écran le dit — et le Mac
# les recalcule en lot. Chemins identiques aux routes legacy → NE PAS monter
# sur server.py (collision, comme review_writes).
app.include_router(review_crop_router)
# C2a (Direction A) : décisions funnel (accept-training/reopen/training-eligible/
# reassign) + décision de lot, SQL-pures (logique dans store.decisions), cv2-free
# → portées sur l'image lean (scope review:write). Chemins identiques aux routes
# locales lourdes → NE PAS monter sur server.py (collision, comme review_writes).
app.include_router(funnel_writes_router)
# C3 (Direction A) : lecture funnel — état-DB-portable autoritatif (crops/
# classes, statut/éligibilité/routage), SQL-pure (logique dans store.funnel),
# cv2/torch/numpy-free → portée sur l'image lean (scope lab:read). Miroir
# lecture de funnel_writes_router. Chemin identique à la route locale lourde
# (serving/lab_routes.cohort_training_crops) → NE PAS monter sur server.py
# (collision, comme funnel_writes/review_writes).
app.include_router(lab_read_router)
# Seuils d'entraînement (plancher/cible/refus dur) : configuration, donc état,
# donc canonique. stdlib + sqlite3 (logique dans store.thresholds) → mount
# inconditionnel. Lecture lab:read, écriture training:run. PAS sur server.py : la
# workstation lit une réplique en lecture seule, y écrire ne produirait qu'un
# `readonly database` déguisé (cf. l'en-tête de serving/thresholds_routes.py).
app.include_router(thresholds_router)
# Seuils DINO : même doctrine, table distincte — valeurs réelles et portée
# (banque, encodeur) au lieu de la cohorte. stdlib + sqlite3 (logique dans
# store.dino_thresholds) → mount inconditionnel.
app.include_router(dino_thresholds_router)
# Banc multi-encodeurs (0009) : les résultats sont une DONNÉE, pas une sortie
# terminal — la page admin qui les affiche est servie par le front HÉBERGÉ, qui
# n'a pas accès au ML local. Lecture seule (lab:read) ; l'écriture passe par
# POST /ingest/encoder-bench. stdlib + sqlite3 (logique dans store.encoder_bench),
# aucun import lourd → mount inconditionnel sur l'image lean.
app.include_router(encoder_bench_router)
# Jeu d'or du cadrage (juge-du-crop L2, migration 0019) : l'or est une DONNÉE,
# pas un fichier local — c'est ce qui manquait à `denom-gold`, dont le verdict
# humain vit dans un `.jsonl` invisible du front hébergé et hors sauvegarde.
# Lecture lab:read (la planche doit être regardable depuis un téléphone),
# écriture review:arbitrate (un ami invité TRANCHE, il ne fixe pas la
# référence). stdlib + sqlite3 → mount inconditionnel sur l'image lean.
app.include_router(crop_gold_routes.router)
# R2 (Model B) : réplique servie DIRECTEMENT par le writer unique (snapshot
# VACUUM INTO cohérent), remplace le détour `canonical_sync → MinIO`. Léger
# (stdlib + sqlite3) → mount inconditionnel sur l'image lean. Scope ingest:run.
app.include_router(db_routes.router)
# Le besoin par classe (O1/O2) : SQL pur sur le canonique, stdlib + sqlite3,
# aucun import lourd → mount inconditionnel. C'est TOUT l'enjeu d'O2 §Où elle
# vit : savoir ce qui manque, et ce que ça coûterait, ne doit pas dépendre d'un
# Mac allumé. Seuls les GESTES que la page propose sont lourds, et le front les
# grise tout seul. Lecture lab:read.
app.include_router(class_need_router)
from serving.dino_drift_routes import router as dino_drift_router
app.include_router(dino_drift_router)
# Les deux compteurs personnels d'un reviewer (review-collaborative-v2, accueil
# d'un ami) : SQL pur sur le canonique, stdlib → mount inconditionnel. C'est la
# SEULE donnée de la page d'accueil qui ne soit pas déjà dans `/class-need`.
# Lecture review:read — voir ce qu'on a fait soi-même n'est pas arbitrer.
app.include_router(me_review_stats_router)


@app.get("/healthz")
def healthz() -> dict:
    """Liveness — ouvert (pas d'auth), pour Traefik/monitoring."""
    return {"ok": True, "role": "serve", "db": str(_DB_PATH)}


# ─── Cœur garanti : ingest run-batch (auth au niveau route) ──────────────────
ingest_routes.bind(_store)
app.include_router(ingest_routes.router)

# local-sync (event-log/outbox hub de merge) retiré C6a (démonté) + C6b
# (module supprimé) — Direction A pousse directement au canonique via
# /ingest/* (crops/faces/dino/run).

# ─── Routers interactifs légers, best-effort (skip si dep lourde absente) ────
# (nom, module, a un bind(store) ?). Les heavy (review_queue/coin_assets : cv2/
# crop_edit) sont listés mais échoueront à l'import sur l'image lean → skippés.
#
# ⚠️ L'ORDRE COMPTE, et `coin_assets` doit rester AVANT `coins`.
# FastAPI résout dans l'ordre d'enregistrement. `coins_routes` déclare
# `GET /coins/{eurio_id}` : monté en premier, il avale `/coins/enrichment-counts`
# et répond « coin enrichment-counts not found » — un 404 parfaitement crédible
# qui ressemble à une route absente, alors que le routeur est bien monté.
# `serving/server.py` (ML API local) applique le même ordre, sans quoi le bug
# n'apparaîtrait que sur le VPS. Ne pas réordonner cette liste par confort de
# lecture. Verrouillé par `tests/test_serve_router_order.py`.
_CANDIDATES = [
    ("coin_assets", "serving.coin_assets_routes", True),
    ("coins", "serving.coins_routes", True),
    ("sets", "serving.sets_routes", True),
    ("operations", "serving.operations_routes", False),
    # `bind` OBLIGATOIRE ici : sans lui, `_store()` importe `serving.server`,
    # qui tire `training` — absent de l'image lean. Le router se montait,
    # et toutes ses routes qui lisent la base répondaient 500 (mesuré en
    # prod le 2026-08-24 : plus une seule vignette canonique sur le front
    # hébergé, écran de review compris).
    ("referential", "serving.referential_routes", True),
    ("peer_arbitration", "review.peer_arbitration_routes", False),
    ("review_queue", "review.review_queue_routes", False),
]
_mounted: list[str] = []
_skipped: list[str] = []
for _name, _modpath, _has_bind in _CANDIDATES:
    try:
        _mod = importlib.import_module(_modpath)
        if _has_bind and hasattr(_mod, "bind"):
            _mod.bind(_store)
        # Auth-redesign C3.5 : migration require_token (legacy bearer machine
        # via table api_tokens) → require_principal (cookie OIDC + PAT). Le
        # legacy bearer n'est plus accepté sur ces routes ; les workflows
        # Mac/PC doivent utiliser un PAT (eurio_<43 base64url>).
        # Pas de défaut permissif : un router sans couple déclaré fait ÉCHOUER le
        # boot. Un `require_principal` de repli rouvrirait le trou en silence le
        # jour où quelqu'un ajoute un router sans y penser.
        if _name not in ROUTER_SCOPES:
            raise RuntimeError(
                f"router '{_name}' monté sans scopes déclarés — ajoute son couple "
                "(lecture, écriture) à _ROUTER_SCOPES."
            )
        _read_scope, _write_scope = ROUTER_SCOPES[_name]
        _dep = require_scope_by_method(_read_scope, _write_scope)
        app.include_router(_mod.router, dependencies=[Depends(_dep)])
        _mounted.append(_name)
    except (ImportError, ModuleNotFoundError) as exc:
        # Skip uniquement si une dépendance lourde (cv2/torch/dino…) est absente
        # de l'image lean — ces routers lèvent ImportError/ModuleNotFoundError à
        # l'import. Toute autre exception (typo, init bug, AttributeError…) doit
        # remonter en clair pour ne pas masquer un vrai problème de câblage.
        _skipped.append(f"{_name} ({type(exc).__name__}: {exc})")
        log.warning("serve: router '%s' NON monté (dep absente) → %s", _name, exc)

log.info("serve-role prêt | DB=%s | auth=%s", _DB_PATH, api_auth.auth_required())
log.info("routers montés : %s", _mounted)
if _skipped:
    log.warning("routers skippés : %s", _skipped)
