# Phase 2.4 — Bench encodeur (banque 2eur_all, set labellisé review)

- 478 crops labellisés · 546 ancres (composition de la banque `2eur_all` live)
- Recall mesuré sur crops in-scope (vérité dans la banque) ; bande pays = ancres du pays cible du listing (même logique que la prod).

| Modèle | dim | in-scope | global@1 | global@5 | pays@1 | pays@5 | ms/img | encode total |
|---|---|---|---|---|---|---|---|---|
| dinov2_vits14 | 384 | 461 | 55.1% | 73.3% | 74.9% | 92.2% | 28 | 29s |
| dinov2_vitl14 | 1024 | 461 | 77.2% | 87.9% | 89.1% | 95.0% | 116 | 119s |


---

> **Suite (2026-08-19).** Le jeu étiqueté est passé de 478 à **1 955 crops**, et
> le sujet a repris dans [`../banque-dino/`](../banque-dino/CONSTAT.md) :
> couverture réelle de la banque (130 pièces sans ancre, toutes avec une image),
> traçabilité (`dino_class_references` vide partout et pourquoi), et le
> protocole pour comparer DINOv3 — testable sans changement de code, `timm`
> expose déjà les 18 variantes.
