"""Pydantic schemas du domaine `review_queue`.

Shape JSON aligné sur `review/review_queue_routes.py` legacy (consommé par
`admin/packages/studio-local/src/features/review/composables/*`).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ─── Review item shape (list + detail) ──────────────────────────────────────


class ReviewBbox(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ReviewCandidate(BaseModel):
    eurio_id: str
    score: float
    label: str
    country: str
    denomination: str
    year: int | None = None
    canonical_thumb_url: str = ""


class ReviewItem(BaseModel):
    id: str
    crop_url: str
    bbox: ReviewBbox | None
    source: str
    source_ref: str
    listing_title: str | None
    listing_url: str | None
    listing_price: float | None
    listing_kind: str | None = None
    listing_kind_confidence: float | None = None
    condition: str | None = None
    condition_confidence: float | None = None
    listing_origin_date: str | None = None
    sold_qty: int | None = None
    candidates: list[ReviewCandidate]
    face_detected: str | None
    priority: int
    is_multi_coin_lot: bool
    quality_score: float
    enqueued_at: str
    target_eurio_id: str | None = None
    target_candidate: ReviewCandidate | None = None
    group_candidates: list[ReviewCandidate] = []
    standard_candidates: list[ReviewCandidate] = []
    dino_top1: ReviewCandidate | None = None
    # Signaux de la banque des SUGGESTIONS (`2eur_all`), pas de celle du
    # verdict. Ils portent le tri : sans eux, l'écran classerait les crops par
    # un critère qu'il ne peut pas montrer, et l'opérateur n'aurait aucun moyen
    # de savoir pourquoi celui-ci est en tête.
    sugg_top1_eurio_id: str | None = None
    sugg_top1_sim: float | None = None
    sugg_spread: float | None = None


# ─── Stats ──────────────────────────────────────────────────────────────────


class ReviewStats(BaseModel):
    n_pending: int
    n_done_today: int
    n_done_this_week: int
    median_seconds_per_decision: float


class TriageVerdictCounts(BaseModel):
    auto_candidate: int
    partial: int
    divergent: int
    unknown: int


class TriageLaneCounts(BaseModel):
    manual: int
    auto_accept: int


class TriageStats(BaseModel):
    """Réponse de /review-queue/triage-stats. Mirror du legacy."""
    n_pending: int
    n_done_today: int
    n_done_today_auto_dino: int
    n_done_this_week: int
    by_verdict: TriageVerdictCounts
    by_lane: TriageLaneCounts
    by_lane_lot: TriageLaneCounts
    n_lot_crops: int
    n_rejected: int
    n_skipped: int


# ─── Rejected crops ─────────────────────────────────────────────────────────


class RejectedCrop(BaseModel):
    review_id: str
    image_asset_id: str
    crop_url: str
    listing_title: str | None
    quality_reason: str | None
    decided_at: str | None
    target_eurio_id: str | None
    target_label: str | None


# ─── Lots ───────────────────────────────────────────────────────────────────


class LotListItem(BaseModel):
    listing_key: str
    source: str
    target_eurio_id: str | None
    listing_title: str | None
    listing_price: float | None
    listing_currency: str
    is_lot_suspected: bool
    n_images: int
    n_crops_in_review: int
    oldest_enqueued_at: str
    thumb_url: str | None
    # Combien de crops de CE listing la banque rattache à la classe pêchée.
    # `None` hors périmètre pêche : « la question n'a pas été posée » ne se
    # confond pas avec « la réponse est zéro » — un listing à 0 ne sort pas.
    n_matching_crops: int | None = None


class DinoCandidatesSummary(BaseModel):
    """Ce que la banque propose pour UNE classe, et ce qui est atteignable.

    Trois populations, jamais additionnées à l'écran : deux sont déjà dans une
    file, la troisième n'est dans aucune — et c'est précisément le genre de
    stock qu'un écran ne doit pas taire.
    """

    class_id: str
    #: Les étiquettes sous lesquelles la banque indexe cette classe (une
    #: courante est indexée sous le plus ancien millésime de son ère).
    bank_class_ids: list[str]
    rank: int
    min_spread: float | None
    n_open_single: int
    n_open_lot: int
    #: La meilleure marge disponible dans chaque file. Un compte sans elle ment
    #: par omission : « 4 à l'unité » peut être quatre faux positifs à 0,02.
    best_spread_single: float | None = None
    best_spread_lot: float | None = None
    #: Le pays sur lequel le filtre mord, ou `None` s'il est désactivé / la
    #: classe n'a pas de pays résoluble.
    country: str | None = None
    #: Combien de crops le filtre pays MASQUE. Un filtre actif par défaut qui ne
    #: dit pas ce qu'il retire ment par omission — celui-ci écarte ~5 % de vrais
    #: positifs, des coffrets multi-pays.
    n_other_country: int = 0
    #: 🔴 Le filtre pays s'est-il RETIRÉ parce qu'il ne laissait rien (O4c) ?
    #: Sans ce drapeau, `country` est renseigné et l'écran affiche « pays LV »
    #: au-dessus d'une file qui sert TOUS les pays : le back se désarme, la
    #: pastille prétend le contraire. Mesuré le 2026-08-23 : ça concerne 147 des
    #: 293 classes en besoin, soit 82 % du palier 1 — donc la majorité des
    #: pêches ouvertes depuis `/besoin`.
    country_disarmed: bool = False
    #: Crops en `needs_review` SANS ligne de review ouverte : jamais enfilés,
    #: invisibles partout. Ils ne deviennent péchables qu'après un enfilage
    #: explicite (POST /coins/assets/reflag-needs-review) — on ne les enfile
    #: JAMAIS au fil d'une lecture.
    n_orphans: int
    #: Plafonné (cf. `ORPHAN_IDS_CAP`) : de quoi enfiler, pas de quoi pagier.
    orphan_asset_ids: list[str]
    #: Déjà validés pour l'entraînement — le dénominateur du « il en manque N ».
    n_training_eligible: int
    #: Le résumé a-t-il été cadré par le besoin (D9) ? Les comptes ci-dessus
    #: sont alors ceux que la FILE SERT, pas ceux du pool brut.
    need_only: bool = False
    #: Ce que ce cadrage retire — parqué, ni fermé ni supprimé (D3). Sur une
    #: classe pleine c'est tout le pool : sans ce nombre, l'écran afficherait
    #: « 0 à l'unité » et se lirait « rien à trancher », plausible et faux.
    n_parked: int = 0
    #: L'état de la classe, pour que l'écran dise POURQUOI c'est parqué.
    #: `None` si la banque des suggestions n'indexe pas cette classe.
    class_have: int | None = None
    class_target: int | None = None
    class_bottleneck: str | None = None


class LotListResponse(BaseModel):
    items: list[LotListItem]
    total: int


# ─── Avancement par run source ──────────────────────────────────────────────


class RunProgressCounts(BaseModel):
    """`total = open + done + skipped`, à la maille d'un kind ou de l'ensemble.

    - `done` : `review_queue.status = 'done'` (accepté OU rejeté — tranché)
    - `skipped` : passé par l'opérateur ; ces rows restent servies par la file
      (`status='open'`, `decision_notes='skipped'`, priorité repoussée), donc
      elles sont « restantes » au sens de la file mais comptées à part
    - `open` : le reste — jamais vu
    """
    total: int
    open: int
    done: int
    skipped: int


class RunParked(BaseModel):
    """Les rows OUVERTES que le filtre `need_only` écarte de la file (D2/D3).

    - `full_class` : top-1 (banque des suggestions) dans une classe déjà à sa
      cible — parquée, ni fermée ni supprimée
    - `no_prediction` : pas de top-1 dans cette banque ; on ne sait pas où le
      crop tombe, donc on ne le sert pas sous ce filtre
    """
    full_class: int
    no_prediction: int


class RunProgress(BaseModel):
    run_ids: list[str]
    need_only: bool = False
    total: int
    open: int
    done: int
    skipped: int
    by_kind: dict[str, RunProgressCounts]
    #: Présent seulement sous `need_only` ; alors `total = open + done +
    #: skipped + parked.full_class + parked.no_prediction` (et `by_kind[*].open`
    #: ne compte que les rows en besoin).
    parked: RunParked | None = None


class LotCrop(BaseModel):
    asset_id: str
    review_id: str
    crop_url: str
    crop_index: int
    phash: int | None
    current_eurio_id: str | None
    candidate_eurio_ids: list[ReviewCandidate]
    bbox: ReviewBbox | None
    # L'ÉTAT de la row de review de ce crop, tel quel. Le détail d'un lot sert
    # TOUS les crops du listing — y compris ceux déjà tranchés, qui portent le
    # contexte visuel du coffret. Sans ces deux champs, le front ne pouvait pas
    # distinguer « à trancher » de « déjà tranché » : il se rabattait sur
    # `review_id` non vide et re-servait des crops clos comme actionnables (751
    # lots, 2303 crops, mesuré le 2026-08-26). `None` = aucune row de review.
    review_status: str | None = None
    review_kind: str | None = None
    # PÊCHE : la banque rattache-t-elle CE crop à la classe qu'on pêche ?
    # `None` hors pêche. Sans ce drapeau, un coffret de 36 vignettes dont une
    # seule est la classe se trie entièrement à l'œil — l'écran saurait laquelle
    # et ne le dirait pas.
    matches_dino_class: bool | None = None
    # La MARGE de la prédiction sur ce crop (COALESCE(country_spread, spread)),
    # lue dans la banque des suggestions. C'est elle qui sépare, pas la
    # similarité — et elle sert ici à deux choses : ouvrir le lot sur le crop le
    # plus net plutôt que sur le premier venu, et dire à l'écran à quel point la
    # proposition tient. `None` quand la banque n'a pas scoré le crop.
    dino_spread: float | None = None


class LotDetection(BaseModel):
    cx: int
    cy: int
    r: int
    accepted: bool
    reject_reason: str | None
    method: str
    crop_index: int | None


class LotImage(BaseModel):
    source_image_id: str
    image_index: int | None
    raw_url: str
    raw_width: int | None
    raw_height: int | None
    detections: list[LotDetection]
    crops: list[LotCrop]


class LotDetail(BaseModel):
    listing_key: str
    source: str
    target_eurio_id: str | None
    target_candidate: ReviewCandidate | None = None
    listing_title: str | None
    listing_price: float | None
    listing_currency: str
    is_lot_suspected: bool
    is_multi_crop_single: bool
    images: list[LotImage]
    prev_listing_key: str | None
    next_listing_key: str | None


# ─── Text signals ───────────────────────────────────────────────────────────


class TextSignalsResponse(BaseModel):
    """Snapshot des signaux extraits du titre du listing (table
    `listing_text_signals`).
    """
    source_image_id: str
    extractor_version: str
    listing_title: str | None = None
    target_eurio_id: str | None = None
    countries: list[str]
    years: list[int]
    denominations: list[float]
    theme_tokens: list[str]
    rejected_markers: list[str]
    is_lot: bool
    coverage: str
    matched: dict[str, list[str]]
    vs_target_verdict: str | None = None
    contradictions: list[str] = []
    convergences: list[str] = []
    computed_at: str | None = None


# ─── /review-queue/{…}/dino-suggestions (lot 6a) ────────────────────────────
#
# Miroir LEAN de la réponse servie jusqu'ici par le seul
# `review/review_queue_routes.py` (module `import cv2`, donc absent du VPS).
# Le contrat est celui que consomme `useDinoSuggestions.ts` — le front n'a rien
# à changer, il change seulement d'adresse.


class DinoSuggestion(BaseModel):
    """Un candidat du top-K, hydraté de ses métadonnées de pièce."""

    eurio_id: str
    sim: float
    country: str | None = None
    country_name: str | None = None
    year: int | None = None
    theme: str | None = None
    denomination: float | None = None
    is_commemorative: bool | None = None
    obverse_url: str | None = None


class DinoCriterionOut(BaseModel):
    key: str   # top1_target | top1_country_sim | country_spread
    state: str  # pass | fail | absent


class AutoValidateVerdictOut(BaseModel):
    """Détail par critère. N'est PAS le verdict de routage : c'est
    `consensus_verdict` qui fait foi."""

    level: str
    reason: str
    criteria: list[DinoCriterionOut]


class ConsensusVerdictOut(BaseModel):
    """Verdict de CONSENSUS — la décision qui a posé la lane."""

    outcome: str
    lane: str
    reason: str
    rule: str
    confidence: float


class DinoVerdictThresholdsOut(BaseModel):
    top1_country_sim_min: float
    country_spread_min: float


class DinoAbstentionThresholdsOut(BaseModel):
    """Seuils d'abstention — le front les AFFICHE (« spread sous 0,02 »).

    Champ NON optionnel : `DinoSuggestions.vue` fait
    `data.abstention_thresholds.spread_uncertain_max.toFixed(2)` sans garde dès
    que `abstention_state === 'uncertain'`. L'omettre ne produit pas une valeur
    manquante mais une exception de rendu — tout le panneau disparaît, et
    seulement pour les crops incertains, c'est-à-dire ceux où il est le plus
    utile."""

    spread_uncertain_max: float
    spread_confident_min: float


class DinoSuggestionsResponse(BaseModel):
    asset_id: str
    encoder_version: str
    anchors_kind: str
    anchors_count: int
    computed_at: str | None = None
    duration_ms: int | None = None
    # Non-null : un RECADRAGE a rendu cette prédiction suspecte (migration 0013).
    # Elle est servie quand même — l'ajustement au micro ne la change presque
    # jamais, et le reviewer recadre AVANT de choisir la pièce. L'écran le dit,
    # l'humain arbitre, le backfill la réencode.
    stale_since: str | None = None
    spread: float | None = None
    top1_eurio_id: str | None = None
    top1_sim: float | None = None
    top_k: list[DinoSuggestion] = Field(default_factory=list)
    target_country: str | None = None
    country_anchors_count: int | None = None
    country_spread: float | None = None
    top1_country_eurio_id: str | None = None
    top1_country_sim: float | None = None
    top_k_country: list[DinoSuggestion] = Field(default_factory=list)
    target_eurio_id: str | None = None
    verdict_thresholds: DinoVerdictThresholdsOut
    abstention_thresholds: DinoAbstentionThresholdsOut
    auto_validate_verdict: AutoValidateVerdictOut | None = None
    consensus_verdict: ConsensusVerdictOut | None = None
    abstention_state: str = "unknown"
    multi_country_lot: bool = False
