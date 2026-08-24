import { Activity, BookOpen, Brain, CircleAlert, ClipboardCheck, ClipboardList, Coins, Crop, Database, Eye, Fish, FlaskConical, Gavel, KeyRound, LayoutDashboard, Layers, Network, Scale, ShieldQuestion, Stamp, Target, Users } from 'lucide-vue-next'
import type { Component } from 'vue'

export interface NavItem {
  id: string
  label: string
  icon: Component
  route: string
  badge?: string
  /**
   * Feature lourde (tape l'API ML locale `:8042` ou un endpoint dev-only). Grisée +
   * non-cliquable en hébergé quand `hasLocalMlApi` est faux (cf. AppLayout / capabilities).
   */
  heavy?: boolean
  /**
   * Scope requis pour seulement VOIR l'entrée. Axe **orthogonal** à `heavy` :
   * `heavy` répond « cette machine peut-elle ? », `scope` répond « à qui cette
   * entrée s'adresse-t-elle ? ». Une entrée sans `scope` est visible de tout
   * principal authentifié.
   *
   * ⚠️ « À QUI ELLE S'ADRESSE » N'EST PAS « CE QU'EXIGE LA PAGE », et l'écart
   * est délibéré (review-collaborative-v2, accueil d'un ami). Trois entrées —
   * Besoin, Review queue, Pêche — portent `review:arbitrate` alors que leurs
   * pages ne demandent que `lab:read` / `review:read`. Ce ne sont pas des pages
   * interdites à un ami : ce sont les instruments de qui DÉCIDE où mettre
   * l'effort, quand un ami, lui, entre par une PIÈCE que son accueil lui
   * désigne. Les pages restent ouvertes, et « Trier » mène droit à la pêche.
   *
   * Pourquoi pas un troisième axe (`hidden`, `audience`) : D3 dit « les scopes
   * SONT le modèle de droits ». Et pourquoi pas un retrait de scope : l'accueil
   * d'un ami LIT `/class-need`, gardé par `lab:read` — le lui retirer
   * éteindrait la page qu'on vient de lui construire. `review:arbitrate` est
   * déjà le discriminant « ami vs opérateur » du front (`useHeavyGate`,
   * D11) ; le jour où un ami est promu arbitre, ses entrées réapparaissent
   * seules, sans une ligne de code.
   *
   * ⚠️ C'est du CONFORT, pas une garde. La garde est serveur : `require_scope`,
   * et `require_scope_by_method` pour les routers montés via `_CANDIDATES` dans
   * `server_serve.py` (lot 4b — leur couple lecture/écriture est déclaré dans
   * `serving/router_scopes.py`, et un router sans couple fait échouer le boot).
   * Un ami qui devine une URL prend donc un 403, pas une page.
   */
  scope?: string
}

export interface NavSection {
  title?: string
  items: NavItem[]
}

// Registre centralisé — ajouter un domaine = une entrée ici + un dossier features/
export const navSections: NavSection[] = [
  {
    items: [
      {
        // « Accueil » et non « Tableau de bord » : `/` sert DEUX écrans (KPI
        // pour l'arbitre, sa page pour un ami — cf. `HomePage`). Un seul
        // libellé doit être vrai pour les deux, et « tableau de bord » ne l'est
        // pas pour quelqu'un dont la page n'en est pas un.
        id: 'dashboard',
        label: 'Accueil',
        icon: LayoutDashboard,
        route: '/',
      },
    ],
  },
  {
    title: 'Éditorial',
    items: [
      {
        id: 'sets',
        label: 'Sets',
        icon: Layers,
        route: '/sets',
        scope: 'coins:write',
      },
      {
        id: 'coins',
        label: 'Pièces',
        icon: Coins,
        route: '/coins',
        scope: 'coins:read',
      },
      {
        id: 'numista-review',
        label: 'Revue Numista',
        icon: CircleAlert,
        route: '/coins/numista-review',
        scope: 'coins:write',
        heavy: true,
      },
      {
        id: 'needs-review',
        label: 'Revue référentiel',
        icon: ShieldQuestion,
        route: '/coins/needs-review',
        scope: 'coins:write',
        heavy: true,
      },
    ],
  },
  {
    title: 'Système',
    items: [
      {
        id: 'sources',
        label: 'Sources',
        icon: Database,
        route: '/sources',
        scope: 'sources:read',
      },
      {
        // Non-`heavy` : la lecture du besoin est du SQL pur sur le canonique,
        // donc disponible en hébergé. Les gestes qu'elle propose se grisent
        // tout seuls (cf. BesoinTable).
        id: 'besoin',
        label: 'Besoin',
        icon: Target,
        route: '/besoin',
        // Instrument de DÉCISION, pas d'exécution : ses chiffres sont
        // conditionnés par ce qu'un ami ne voit pas et ne contrôle pas (date du
        // dernier rebuild, filtre pays auto-désarmé, plan d'achat, palier).
        // Son composant de liste, lui, est réimporté sur l'accueil — c'est lui
        // qu'on voulait, pas la page. La page reste ouverte en `lab:read`.
        scope: 'review:arbitrate',
      },
      {
        id: 'review',
        label: 'Review queue',
        icon: ClipboardCheck,
        route: '/review',
        // On entre par une PIÈCE, jamais par une file anonyme. La page reste
        // ouverte en `review:read` — c'est l'ENTRÉE qui part, pas l'accès.
        scope: 'review:arbitrate',
      },
      {
        id: 'peche',
        label: 'Pêche',
        icon: Fish,
        route: '/review/peche',
        // ⛔ La PAGE reste, et elle est même la destination de « Trier » sur
        // l'accueil (`/review/peche?class=…`). Seule son entrée de menu part :
        // un ami y arrive par une pièce qu'il a choisie, pas par un menu.
        scope: 'review:arbitrate',
      },
      {
        // Arbitrage des décisions des amis (lot 8). `review:arbitrate` : un ami
        // ne la voit pas — et le serveur la lui refuserait de toute façon.
        id: 'arbitrage-peer',
        label: 'Arbitrage',
        icon: Stamp,
        route: '/review/arbitrage',
        scope: 'review:arbitrate',
      },
      {
        id: 'audit',
        label: 'Audit log',
        icon: ClipboardList,
        route: '/audit',
        scope: 'audit:read',
      },
      {
        id: 'operations',
        label: 'Operations',
        icon: Activity,
        route: '/operations',
        scope: 'ingest:run',
      },
      {
        id: 'referential',
        label: 'Référentiel',
        icon: BookOpen,
        route: '/referential',
        scope: 'coins:write',
      },
    ],
  },
  {
    title: 'Outils',
    items: [
      {
        id: 'parity',
        label: 'Parity Viewer',
        icon: Eye,
        route: '/parity',
        scope: 'training:run',
        // Dépend du devMiddleware (endpoints JSON servis seulement en `pnpm dev`).
        heavy: true,
      },
      {
        id: 'arbitrage',
        label: 'Arbitrage Numista',
        icon: Scale,
        route: '/coins/arbitrage',
        scope: 'coins:write',
        heavy: true,
      },
      {
        id: 'training',
        label: 'Training',
        icon: Brain,
        route: '/training',
        scope: 'training:run',
        heavy: true,
      },
      {
        id: 'confusion',
        label: 'Cartographie ML',
        icon: Network,
        route: '/confusion',
        scope: 'training:run',
        heavy: true,
      },
      {
        id: 'lab',
        label: 'Lab',
        icon: FlaskConical,
        route: '/lab',
        scope: 'training:run',
        heavy: true,
      },
      {
        id: 'bench',
        label: 'Studio bench',
        icon: Gavel,
        route: '/bench',
        scope: 'training:run',
        heavy: true,
      },
      {
        id: 'crop-bench',
        label: 'Crop Bench',
        icon: Crop,
        route: '/crop-bench',
        scope: 'training:run',
        heavy: true,
      },
      {
        id: 'denom-gold',
        label: 'Gold denom',
        icon: Coins,
        route: '/denom-gold',
        scope: 'training:run',
        heavy: true,
      },
    ],
  },
  {
    title: 'Administration',
    items: [
      {
        id: 'users',
        label: 'Utilisateurs',
        icon: Users,
        route: '/users',
        scope: 'users:read',
      },
      {
        id: 'tokens',
        label: 'Mes tokens',
        icon: KeyRound,
        route: '/me/tokens',
        scope: 'tokens:manage_own',
      },
    ],
  },
  // Futurs domaines :
  // { title: 'Marketplace', items: [{ id: 'marketplace', ... }] },
]
