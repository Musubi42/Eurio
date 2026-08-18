"""Preflight « assez d'images par classe ? » avant un run de training.

Pourquoi : un run ArcFace lit ses classes depuis ``training_staging`` (ou les
``classes_added``/``classes_after`` d'un run), mais rien ne vérifiait, *avant*
de dépenser du GPU, que chaque classe a assez de sources réelles. Conséquences
observées (cf. ``docs/work-in-progress/cohort-readiness/HANDOFF.md`` §7) :

- une classe **sans aucune source** (réf morte / jamais acquise, ex. un eurio_id
  de cohorte qui n'existe plus en catalogue) est **silencieusement absente** du
  dataset (``ImageFolder`` ignore un dossier vide) → on croit entraîner N classes,
  on en entraîne N-k ;
- si **toutes** les classes sont vides → 0 classe → ``MPerClassSampler`` plante
  (``length_of_single_pass == 0`` → division par zéro) ;
- une classe avec **moins de ``m_per_class`` sources réelles** n'apporte aucun
  signal : ``MPerClassSampler`` rééchantillonne *avec remise* (cf.
  ``safe_random_choice``) → la classe s'entraîne sur des doublons quasi-identiques
  (mémorisation, pas de généralisation).

Ce module calcule, par classe stagée, le *seed* (= nombre de vues réelles
distinctes) en réutilisant **exactement** la collecte de sources du bake
(``iteration_augmentations.real_training_sources``) et la doctrine de plancher
(``foundation/enrichment``). Il classe chaque classe en ``ok`` / ``warn`` /
``block`` et l'appelant (``training/pipeline.py``) refuse le run si une classe
bloque — message clair, *avant* la préparation et l'entraînement.

Seed d'une classe = somme sur ses eurio_ids membres (une classe ``design_group``
agrège plusieurs eurio_ids) de : avers Numista (FS) + crops eBay reviewés
(``training_eligible=1``) + réfs officielles BCE / EUR-Lex JO.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from store import ClassRef, Store
from training.eval.class_resolver import Resolver, build_resolver
from store.funnel_constants import M_PER_CLASS, MIN_REAL
from training.iteration_augmentations import real_training_sources

# Plancher mécanique dur : en-dessous, ArcFace ne voit que des doublons
# rééchantillonnés avec remise (MPerClassSampler). Aligné par défaut sur
# ``m_per_class`` du run, qui pilote combien d'exemplaires/classe par batch.
#
# DÉFAUTS uniquement : les valeurs qui s'appliquent sont résolues en base
# (``store/thresholds.resolve``) et passées par l'appelant. Elles restent le
# filet quand la table n'existe pas encore.
DEFAULT_M_PER_CLASS = M_PER_CLASS
DEFAULT_MIN_REAL = MIN_REAL


@dataclass
class ClassPreflight:
    class_id: str
    class_kind: str
    n_numista: int
    n_ebay: int
    n_ref: int
    seed: int
    status: str  # 'ok' | 'warn' | 'block'
    reason: str | None = None
    missing_eurio_ids: tuple[str, ...] = ()  # membres absents du catalogue

    def to_dict(self) -> dict:
        return {
            "class_id": self.class_id,
            "class_kind": self.class_kind,
            "n_numista": self.n_numista,
            "n_ebay": self.n_ebay,
            "n_ref": self.n_ref,
            "seed": self.seed,
            "status": self.status,
            "reason": self.reason,
            "missing_eurio_ids": list(self.missing_eurio_ids),
        }


@dataclass
class PreflightReport:
    classes: list[ClassPreflight] = field(default_factory=list)
    m_per_class: int = DEFAULT_M_PER_CLASS
    min_real: int = DEFAULT_MIN_REAL

    @property
    def blocked(self) -> list[ClassPreflight]:
        return [c for c in self.classes if c.status == "block"]

    @property
    def warned(self) -> list[ClassPreflight]:
        return [c for c in self.classes if c.status == "warn"]

    @property
    def ok(self) -> bool:
        return not self.blocked

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "m_per_class": self.m_per_class,
            # Le plancher SOUS LEQUEL une classe est dite pauvre. Exposé pour
            # que le front n'ait pas à le deviner (il n'en définit aucun).
            "min_real": self.min_real,
            "n_total": len(self.classes),
            "n_blocked": len(self.blocked),
            "n_warned": len(self.warned),
            "classes": [c.to_dict() for c in self.classes],
            "summary": self.summary(),
        }

    def summary(self) -> str:
        """Tableau lisible (logué tel quel par le pipeline)."""
        if not self.classes:
            return "preflight: AUCUNE classe stagée — rien à entraîner (BLOCK)."
        lines = [
            f"preflight: {len(self.classes)} classe(s) "
            f"({len(self.blocked)} block, {len(self.warned)} warn) "
            f"— seuil dur = {self.m_per_class} sources réelles/classe, "
            f"plancher = {self.min_real} crops eBay/classe",
            f"  {'classe':<55} {'seed':>4} {'num':>3} {'ebay':>4} {'ref':>3}  statut",
        ]
        for c in sorted(self.classes, key=lambda x: (x.status != "block", x.status != "warn", x.class_id)):
            mark = {"block": "✗ BLOCK", "warn": "⚠ warn", "ok": "ok"}[c.status]
            reason = f"  — {c.reason}" if c.reason else ""
            lines.append(
                f"  {c.class_id:<55} {c.seed:>4} {c.n_numista:>3} "
                f"{c.n_ebay:>4} {c.n_ref:>3}  {mark}{reason}"
            )
        return "\n".join(lines)


def preflight_classes(
    classes: list[ClassRef],
    store: Store,
    *,
    m_per_class: int = DEFAULT_M_PER_CLASS,
    min_real: int = DEFAULT_MIN_REAL,
    resolver: Resolver | None = None,
) -> PreflightReport:
    """Évalue chaque classe stagée. Voir le module pour les tiers.

    ``m_per_class`` (refus dur) et ``min_real`` (plancher « classe pauvre »)
    viennent de ``store/thresholds.resolve`` chez l'appelant : deux notions
    distinctes, réglables séparément. Les passer explicitement est ce qui
    garantit que le 409 de création d'itération et le verdict affiché parlent
    du même seuil.

    ``resolver`` injectable pour les tests ; sinon construit depuis eurio.db.
    """
    report = PreflightReport(m_per_class=m_per_class, min_real=min_real)
    if not classes:
        return report  # ok==False (blocked vide mais .ok regarde block ; cf. pipeline)

    resolver = resolver or build_resolver()
    for ref in classes:
        descriptor = resolver.for_class(ref.class_id)
        if descriptor is None or not descriptor.eurio_ids:
            # La classe n'existe pas en catalogue (réf morte / slug drift) :
            # aucune source possible, elle serait silencieusement absente.
            report.classes.append(
                ClassPreflight(
                    class_id=ref.class_id,
                    class_kind=ref.class_kind,
                    n_numista=0,
                    n_ebay=0,
                    n_ref=0,
                    seed=0,
                    status="block",
                    reason="classe absente du catalogue (réf morte / slug drift)",
                )
            )
            continue

        n_numista = n_ebay = n_ref = 0
        missing: list[str] = []
        # real_training_sources lit l'avers FS par numista_id ; pour une classe
        # design_group multi-membres, chaque eurio_id a SON numista_id (le
        # descriptor n'agrège que l'union) → résolution par eurio_id précise.
        for eurio_id in descriptor.eurio_ids:
            nid = _numista_of(resolver, eurio_id)
            src = real_training_sources(eurio_id, nid, store)
            n_numista += src.n_numista
            n_ebay += src.n_ebay
            n_ref += src.n_ref
            if src.total == 0:
                missing.append(eurio_id)
        seed = n_numista + n_ebay + n_ref

        status, reason = _verdict(seed, n_ebay, m_per_class, min_real)
        report.classes.append(
            ClassPreflight(
                class_id=ref.class_id,
                class_kind=ref.class_kind,
                n_numista=n_numista,
                n_ebay=n_ebay,
                n_ref=n_ref,
                seed=seed,
                status=status,
                reason=reason,
                missing_eurio_ids=tuple(missing),
            )
        )
    return report


def _numista_of(resolver: Resolver, eurio_id: str) -> int | None:
    """numista_id d'un eurio_id précis (classe multi-membres : ne pas prendre
    le premier numista_id du groupe, qui appartiendrait à un autre membre)."""
    for coin in resolver._coins:  # noqa: SLF001 — accès lecture du cache résolveur
        if coin.eurio_id == eurio_id:
            return coin.numista_id
    return None


def _verdict(
    seed: int, n_ebay: int, m_per_class: int, min_real: int
) -> tuple[str, str | None]:
    if seed == 0:
        return "block", "aucune source réelle (avers Numista, crop eBay ni réf BCE/EUR-Lex)"
    if seed < m_per_class:
        return (
            "block",
            f"{seed} source(s) réelle(s) < m_per_class={m_per_class} "
            "→ entraînement sur doublons rééchantillonnés (pas de signal)",
        )
    if n_ebay < min_real:
        return (
            "warn",
            f"{n_ebay} crop(s) eBay réel(s) < {min_real} "
            "→ s'appuie sur l'augmentation (aller chercher plus d'eBay)",
        )
    return "ok", None
