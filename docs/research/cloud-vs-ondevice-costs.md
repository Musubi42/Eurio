# Cloud vs On-Device — Analyse de coûts

> Décision prise : **100% on-device** pour l'inférence scan.

---

## 1. Contexte

Le scan de pièce est la feature core d'Eurio. Chaque utilisateur peut scanner plusieurs pièces par session. Le modèle économique est freemium avec scan gratuit et illimité. Le coût marginal par scan doit tendre vers zéro.

---

## 2. Coûts cloud par service

| Service | Coût / 1K inférences | Training | Export on-device | Statut |
|---|---|---|---|---|
| Google Vertex AI (AutoML) | ~1.50€ | ~3.15€/h | Oui (TFLite via Firebase) | Stable |
| Azure Custom Vision | ~2.00€ | Free tier (2 projets) | Oui (TFLite, ONNX, CoreML) | **Retrait prévu 2028** |
| AWS Rekognition Custom Labels | ~4€/h (endpoint always-on) | ~1€/h | Non | Inadapté au mobile |
| Clarifai | Inclus dans crédits (30€/mois Essential) | Inclus | Limité | Opaque |
| Roboflow | Free: 1K/mois, Starter: 49€/mois (100K) | Inclus | Oui (TFLite, ONNX) | Stable |

---

## 3. Projections de coûts selon le volume

### Hypothèses
- Utilisateur moyen : 5 scans/session, 3 sessions/mois = 15 scans/mois
- Coût cloud de référence : 1.50€/1K inférences (Google, le moins cher)

| Scénario | MAU | Scans/mois | Coût cloud/mois | Coût on-device/mois |
|---|---|---|---|---|
| POC | 50 | 750 | ~1€ | 0€ |
| Beta privée | 500 | 7 500 | ~11€ | 0€ |
| Lancement | 5 000 | 75 000 | ~112€ | 0€ |
| Croissance | 20 000 | 300 000 | ~450€ | 0€ |
| Objectif 1 an | 50 000 | 750 000 | ~1 125€ | 0€ |

### Coût total sur 12 mois (scénario croissance progressive)

```
Cloud :  ~1 + 11 + 30 + 50 + 80 + 112 + 150 + 200 + 280 + 350 + 400 + 450 = ~2 114€
On-device : 0€

Économie : ~2 100€ la première année
```

À 50K MAU le cloud coûte plus de **13 000€/an** pour le scan seul.

---

## 4. Coût on-device

| Composant | Coût |
|---|---|
| Modèle TFLite dans l'APK | 0€ (embarqué) |
| Inférence sur le téléphone de l'utilisateur | 0€ (CPU/GPU du device) |
| Base d'embeddings (~500 KB JSON) | 0€ (stocké localement) |
| Sync des embeddings via Supabase | Négligeable (~500 KB/sync) |
| **Total** | **0€ par scan, pour toujours** |

---

## 5. Avantages supplémentaires du on-device

| Critère | Cloud | On-device |
|---|---|---|
| Latence | 200-500ms (réseau) | < 10ms |
| Fonctionne hors-ligne | Non | **Oui** |
| Vie privée utilisateur | Images envoyées au serveur | Images restent sur le device |
| Dépendance serveur | Oui (downtime = app cassée) | Non |
| RGPD / données personnelles | Complexe (traitement d'images) | **Aucun transfert = simplifié** |

---

## 6. Où le cloud est utilisé (hors scan)

Le scan est on-device, mais d'autres composants nécessitent un backend :

| Composant | Hébergement | Coût estimé |
|---|---|---|
| Base d'embeddings (sync) | Supabase Storage | Free tier |
| Catalogue pièces (métadonnées) | Supabase PostgreSQL | Free tier (< 50K rows) |
| Historique de prix | Supabase PostgreSQL | Free tier |
| Auth utilisateur | Supabase Auth | Free tier (< 50K MAU) |
| API enrichissement (fiche pièce) | Supabase Edge Functions ou Fastify (Fly.io) | ~5€/mois |
| Cron eBay pricing | Supabase Edge Functions ou cron externe | ~0-5€/mois |
| **Total infra** | | **~5-10€/mois** |

---

## 7. Décision

**Scan = 100% on-device.** Le modèle freemium illimité n'est viable qu'avec un coût marginal de 0€ par scan. Le cloud est réservé aux données (catalogue, prix, sync) qui représentent un trafic faible et prévisible.
