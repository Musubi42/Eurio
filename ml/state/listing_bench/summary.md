# Bench detection listing — 2026-05-04 22:20:43

Voir `docs/sources-refacto/listing-crop-roadmap.md` pour le contexte.

Légende : YOLO bboxes (jaune) + cercles finals (vert=accepted, rouge=rejected). Strip 224×224 = crops finals acceptés (= input ArcFace).

| lot.img | size | YOLO | acc | rej | methods accepted | reject reasons | r/short accepted |
|---|---|---|---|---|---|---|---|
| 114573231478.0 | 1200x1600 | 89 | 1 | 1 | yolo+hough+polish | radius_too_small | 0.127 |
| 115143970168.0 | 1200x1600 | 27 | 1 | 1 | yolo+hough+polish | radius_too_small | 0.133 |
| 114573235985.0 | 1600x1200 | 24 | 2 | 0 | yolo+hough+polish, yolo+hough+polish | — | 0.089, 0.088 |
| 117142786358.0 | 1600x1090 | 15 | 2 | 1 | yolo+hough+polish, yolo+hough+polish | low_structure | 0.095, 0.095 |
| 168045333862.0 | 1600x900 | 4 | 4 | 0 | yolo+hough, yolo+hough+polish, yolo+hough, yolo+hough | — | 0.172, 0.178, 0.171, 0.177 |
| 168045333862.1 | 1600x900 | 4 | 4 | 0 | yolo+hough, yolo+hough, yolo+hough, yolo+hough | — | 0.180, 0.181, 0.177, 0.167 |
| 136929255254.0 | 1600x1598 | 0 | 0 | 0 | — | — | — |
| 136929255254.1 | 1600x1598 | 1 | 0 | 0 | — | — | — |
| 146492050953.0 | 800x269 | 10 | 2 | 6 | yolo+hough+polish, yolo+hough | radius_too_small, radius_too_small, radius_too_small, radius_too_small, radius_too_small, radius_too_small | 0.149, 0.152 |
| 168215792107.0 | 1200x1600 | 17 | 1 | 1 | yolo+hough | radius_too_small | 0.145 |
| 168215792107.1 | 1200x1600 | 4 | 1 | 2 | yolo+hough | radius_too_small, radius_too_small | 0.121 |
