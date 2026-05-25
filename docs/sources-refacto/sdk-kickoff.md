# Source SDK — kickoff

> **Statut** : design en cours, **différé post-cohorte 19** (cf. session coin-richness).
> Ce document est **vivant** : il capture la vision actuelle + les findings
> qui remonteront pendant l'implémentation de la cohorte. Sera figé en
> ADR quand la doctrine de provenance aura été validée sur le terrain.
>
> Rédigé : **2026-05-25**. Auteur : session coin-richness brainstorm.

---

## 1. Pourquoi ce doc

Le chantier `coin-richness` a acté deux doctrines structurantes
(cf. `docs/coin-richness/ROADMAP-DB.md` §2) :

1. **`eurio.db` = source de vérité unique** côté dev local.
2. **Provenance first-class** — chaque fact en DB porte sa source via FK
   `source_registry(id)`. Multi-source same value = multi-row.

Conséquence indirecte : **ajouter une nouvelle source de données** (Bundesbank,
2euros.org, FNMT, Münze Österreich, Wikipedia DE, EUR-Lex, ...) doit devenir
une opération **rapide et sûre**. Aujourd'hui, chaque source actuelle (BCE,
eBay, Numista) a son propre code de découverte / fetch / résolution
`external_id → eurio_id`, et son propre vocabulaire de faits. **Pas de contrat
commun** côté référentiel.

Le `module-contract.md` voisin couvre déjà un contrat — mais **image/listing-side**
uniquement (`source_images`, `image_assets`, `coin_market_quotes`). Le pan
**référentiel** (observations, mint_releases, credits, canonical_images,
cross_refs) n'a pas de contrat. C'est ce trou que ce SDK doit combler.

**Décision prise** (2026-05-25) : on développe le SDK **après** la validation
cohorte 19, pour éviter de figer une abstraction sur des cas mal compris. La
cohorte sert de banc d'essai pour le **contrat de données** ; le SDK arrive
quand on est sûr du contrat.

---

## 2. Ce qui existe déjà (image/listing-side)

`docs/sources-refacto/module-contract.md` définit :

- Structure `ml/sources/<source>/{fetch,schema,cli,README}.py` + un `_base/`
  partagé (`run_logger`, `quota_guard`, `dedup`, `storage`, `http`).
- Contrat `def run(ctx: RunContext, filters: Filters) -> FetchResult` qui
  enchaîne discover → upsert source_image → detect & crop → resolve →
  enqueue review.
- Contrat go-task uniforme (`ml:src:<source>:{run,dry,limit,status}`).
- `RunContext` injecte `db_session`, `quota`, `storage_root`, `logger`.

✅ Ce contrat **marche pour les sources qui produisent des images/listings**
(eBay, futures sources d'enchères). Il sera **réutilisé tel quel** par le SDK
— pas de refonte.

❌ Il **ne couvre pas** les sources qui produisent des **facts référentiels** :
mintage par atelier, dates d'émission, credits, JOUE codes, mintage totaux,
descriptions, indices de rareté. Or c'est *exactement* ce qu'on va devoir
multiplier (BCE détaillé, Bundesbank, 2euros.org, Numista enrichi,
Wikipedia DE, ...).

---

## 3. Le vrai gap — extension référentielle du contrat

### 3.1 — Le value-object `Extracted`

Une source référentielle, pour une pièce donnée, peut émettre **plusieurs
types de facts** simultanément. Au lieu de N méthodes spécialisées, le SDK
propose un value object uniforme :

```python
@dataclass(frozen=True)
class Extracted:
    """Tout ce qu'une source peut émettre pour une pièce donnée."""
    observations:     list[Observation]         = field(default_factory=list)
    mint_releases:    list[MintReleaseFact]     = field(default_factory=list)
    canonical_images: list[CanonicalImage]      = field(default_factory=list)
    cross_refs:       list[CrossRef]            = field(default_factory=list)
    credits:          list[Credit]              = field(default_factory=list)
    edge_variants:    list[EdgeVariant]         = field(default_factory=list)
    variants:         list[VariantRow]          = field(default_factory=list)
    prices:           list[PriceQuote]          = field(default_factory=list)
```

Chaque entrée est typée, immutable, et **agnostique de la source** — le
runner injecte `source` depuis `adapter.meta().id` au write time. L'adapter
ne touche **jamais** la DB.

### 3.2 — Le protocol `ReferentialSourceAdapter`

```python
class ReferentialSourceAdapter(Protocol):
    def meta(self) -> SourceMeta: ...
        # → (id, kind, base_url, display_name)
        # id = clé dans source_registry (ex: 'numista_api', '2euros_org')
        # kind ∈ {official, reference, community, manual, derived}

    def discover(
        self, filters: SourceFilters
    ) -> Iterable[ExternalRef]: ...
        # Itère les identifiants externes que la source connaît
        # (numista_id, BCE URL, 2euros.org slug, ...).
        # Peut être multi-stage (cf. open question §5.1).

    def fetch(self, ref: ExternalRef) -> Payload: ...
        # Pull raw (HTTP/scrape/API), cache sur disque obligatoire
        # (ml/datasets/sources/<source>/<ref>.{json,html,pdf}).

    def resolve_eurio_id(
        self, payload: Payload, resolver: EurioIdResolver
    ) -> str | None: ...
        # Match canonique. Délègue au `resolver` partagé pour
        # cross_refs lookup + heuristiques (cf. §3.3).

    def extract(
        self, payload: Payload, eurio_id: str
    ) -> Extracted: ...
        # Émet tous les facts que la source peut tirer du payload.
```

### 3.3 — `EurioIdResolver` partagé (le vrai gain de levier)

Aujourd'hui, **chaque source réinvente** son matcher : Numista a son script,
BCE a le sien, eBay a son theme-matcher. Pourtant tous font fondamentalement
la même chose : *« j'ai un signal externe (titre, country, year, native_id),
trouve-moi l'eurio_id qui correspond »*.

Le SDK fournit :

```python
class EurioIdResolver:
    def by_cross_ref(self, ref_type: str, ref_value: str) -> str | None: ...
        # Lookup direct dans coin_cross_refs
    def by_native_id(self, source_id: str, native_id: str) -> str | None: ...
        # Via referential_catalog(source, source_native_id) → eurio_id mapping
    def by_signals(self, country: str, year: int, denom: float,
                   theme_tokens: list[str]) -> list[str]: ...
        # Heuristique multi-signaux, retourne candidates ranked
    def by_embedding(self, image_path: Path) -> list[str]: ...
        # (futur) via ArcFace/Dino — sources avec image fournie
```

L'adapter écrit son `resolve_eurio_id` en termes de **ces primitives**, pas en
re-implémentant un matcher.

### 3.4 — Le runner partagé

```python
def run_referential_source(
    adapter: ReferentialSourceAdapter,
    options: RunOptions,
) -> RunReport:
    """
    1. Ensure source_registry row exists (upsert from adapter.meta()).
    2. Open source_runs row.
    3. For each ref in adapter.discover(filters):
       a. payload = adapter.fetch(ref)             # cached
       b. eurio_id = adapter.resolve_eurio_id(payload, resolver)
          - if None: enqueue review_queue, continue
       c. extracted = adapter.extract(payload, eurio_id)
       d. writer.persist(extracted, source=adapter.meta().id, run_id=...)
          # writer applique INSERT OR REPLACE sur les UNIQUE canoniques
       e. update run counters
    4. Close source_runs row, return RunReport.
    """
```

**L'idempotence est gérée centrale** via les UNIQUE déclarés dans schema.sql
(`coin_observations(eurio_id, source, observation_type)`, etc.). Un re-run
de la même source = REPLACE des facts, jamais de duplicate, jamais d'orphan.

---

## 4. Vocabulaires canoniques (à figer post-cohorte)

Le SDK fournit des **constantes Python** (et idéalement un test de lint qui
vérifie qu'on n'écrit pas hors vocabulaire) pour :

- `observation_type` (sur `coin_observations`) — ex : `release_date`, `series`,
  `inscription`, `rarity_index`, `theme_description`, `design_obverse`, ...
- `fact_type` (sur `mint_release_observations`) — ex : `mintage`, `released_on`,
  `frequency`, `notes`
- `ref_type` (sur `coin_cross_refs`) — ex : `wikipedia_url`, `lmdlp_url`,
  `mdp_url`, `joue_code`, `numista_id`, `bce_comm_url`, `krause_mishler`,
  `jaeger`, `schon`, `numista_swap_url`
- `role` (sur `coin_credits`) — `designer`, `engraver`, `sculptor`
- `issue_type` (sur `coin_mint_releases`) — `CIRC`, `BU`, `BE`, `PROOF`,
  `COIN_CARD`, `OTHER`
- `finish` (sur `coin_variants`) — `classic`, `coloured`, `hologram`, `gilded`,
  `pattern`, `mule`, `misstrike`, `other`

**Pourquoi figer post-cohorte** : la cohorte 19 va révéler des `observation_type`
qu'on n'a pas anticipés (chaque source ajoutera 1-2 trucs nouveaux). On
formalise après, quand on connaît la liste exhaustive.

---

## 5. Questions ouvertes (à trancher au moment du portage)

### 5.1 — `discover` multi-stage

BCE a une discovery en 2 stages (index par année → détail par pièce). Numista
n'en a pas (on lui passe directement des `eurio_id` via cross_ref `numista_id`).
eBay fait du `discovery_searches` par groupe `(denom, country, year)`.

→ **Soit** `discover()` retourne un Iterable opaque qui cache la complexité
multi-stage à l'intérieur, **soit** on split en `discover_index()` /
`discover_detail(idx_ref)`. Décision **différée jusqu'au portage BCE**, qui
est le cas test.

### 5.2 — Sources avec quota dur (Numista)

`QuotaGuard` existe déjà pour eBay. À étendre / unifier avec un budget
**par source** dans `source_registry` (colonne `monthly_quota INTEGER`).
Adapter doit pouvoir lever `QuotaExhausted` au milieu de `discover`/`extract`.

### 5.3 — Sources sans API (PDF, scrape HTML lourd)

Bundesbank publie des PDFs. 2euros.org est du scrape HTML. Le contrat
`fetch(ref) -> Payload` doit accepter `bytes` + un type discriminé
(`Payload = JsonPayload | HtmlPayload | PdfPayload | ...`) ou un blob brut
+ metadata. À designer en portant Bundesbank (probablement la source la plus
hostile au scrape automatique).

### 5.4 — Linter de vocabulaire

Faut-il un test CI qui scanne `git diff` et vérifie que tout nouvel
`observation_type` / `ref_type` introduit dans le code est déclaré dans le
fichier de constantes canonique ? À discuter quand le vocabulaire sera figé.

### 5.5 — Quand un adapter émet une nouvelle source pour la première fois

`adapter.meta()` retourne une `SourceMeta`. Le runner doit-il **insérer**
automatiquement dans `source_registry` la première fois (upsert) ou bien
**refuser** de tourner si le seed manque (force une décision éditoriale
explicite "j'autorise cette source") ? Reco initiale : **refuser**, parce que
`source_registry` est un point de gouvernance — on ne veut pas qu'un dev
introduise une source à son insu. Mais c'est friction. À valider au premier
portage post-cohorte.

---

## 6. Findings cohorte 19 — à capturer pendant l'implémentation

Cette section est **destinée à être remplie au fur et à mesure** des chunks
P.*/B.*/V.*. Objectif : nourrir le design SDK sans re-deviner après coup.

À noter chaque fois que tu rencontres :

- [ ] Un `observation_type` / `fact_type` / `ref_type` qu'aucune source
      n'avait avant — quel besoin produit l'a justifié ?
- [ ] Une heuristique de matching `external_id → eurio_id` qui marche bien
      pour cette source (pour `EurioIdResolver.by_signals`).
- [ ] Un cas où **deux sources donnent la même valeur** (signal d'agreement —
      forme attendue dans la lecture).
- [ ] Un cas où **deux sources divergent** (Numista 5 800 000 vs Bundesbank
      5 805 250) — comment l'admin a tranché ou choisi de garder les deux ?
- [ ] Un type de payload qui résiste à la modélisation (HTML scrape mal
      structuré, PDF tabulaire, page dynamique) — sera un cas test du SDK.
- [ ] Un quota explosé / un rate-limit hit — informe la conception du
      `QuotaGuard` multi-source.
- [ ] Un script de matcher écrit ad-hoc dont **la moitié pourrait être en
      `EurioIdResolver`** — note la portion réutilisable.
- [ ] Une UNIQUE constraint qui colle ou ne colle pas (idempotence du
      `INSERT OR REPLACE`).

Format suggéré : ajouter une ligne datée dans §7 en bas du doc, avec un lien
vers le chunk concerné.

---

## 7. Journal des findings (rempli pendant la cohorte)

| Date | Chunk | Finding | Implication SDK |
|---|---|---|---|
| _à remplir_ | _ex: B.1_ | _ex: Numista API expose `release_dates` array par mint_release, pas une seule date par Type_ | _ex: `Extracted.mint_releases` doit pouvoir porter `released_on` par row, ✓ déjà prévu_ |

---

## 8. Ordre de portage (post-cohorte 19, après findings figés)

| # | Source | Justification ordre |
|---|---|---|
| 1 | **BCE** | Cas simple : peu de facts (release_date, image canonique, mintage total). Pas de quota. Bon banc d'essai pour valider le contrat `Extracted` minimaliste. |
| 2 | **Numista** | Cas médian : riche en facts (mint_releases, credits, JOUE, variants, prices). Quota dur (2000/mois) → valide `QuotaGuard` cross-source. |
| 3 | **2euros.org** | Cas scrape HTML lourd. Valide le `Payload` non-JSON. |
| 4 | **Bundesbank** | Cas PDF. Le plus hostile. Si le SDK le supporte, il supporte tout. |
| 5 | **eBay** | Déjà demi-refactoré sous `sources-refacto/`. À aligner en dernier — son contrat actuel (image-side) sera conservé, on rajoute juste la couche référentielle (peu de facts car eBay ≠ source référentielle, juste prix). |

**Anti-pattern** : commencer par eBay parce qu'il est le plus complexe →
dimensionner le SDK sur le cas le plus tordu et l'imposer aux sources
simples. On commence simple, on étend.

---

## 9. Out-of-scope (à ne PAS faire dans la première version du SDK)

- ❌ Sync sortant SQLite → Supabase. Reste un script dédié, pas une
  responsabilité d'adapter.
- ❌ ML/embedding-based resolver (`EurioIdResolver.by_embedding`). Stub
  d'interface OK, implémentation différée à quand on aura un usage.
- ❌ Cross-source reconciliation automatique (qui décide quelle source
  l'emporte). C'est de la **lecture** côté admin/API, pas de l'écriture.
  Le SDK ne reconcilie jamais — il écrit la donnée brute multi-source.
- ❌ Sources transactionnelles (live marketplace). Le SDK est conçu pour
  des fetches batch, pas pour du streaming.

---

## 10. Liens

- `docs/sources-refacto/module-contract.md` — contrat existant image/listing-side
- `docs/coin-richness/ROADMAP-DB.md` — doctrine de provenance qui justifie ce SDK
- `docs/coin-richness/chantier-C-mintage.md` — pattern identity + observations
- `docs/sources-refacto/orchestration.md` — orchestration actuelle (à aligner)
- `docs/sources-refacto/decisions.md` — décisions historiques sources-refacto
