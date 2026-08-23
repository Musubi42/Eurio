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
   * `heavy` répond « cette machine peut-elle ? », `scope` répond « cette personne
   * a-t-elle le droit ? ». Une entrée sans `scope` est visible de tout principal
   * authentifié.
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
        id: 'dashboard',
        label: 'Tableau de bord',
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
        scope: 'lab:read',
      },
      {
        id: 'review',
        label: 'Review queue',
        icon: ClipboardCheck,
        route: '/review',
        scope: 'review:read',
      },
      {
        id: 'peche',
        label: 'Pêche',
        icon: Fish,
        route: '/review/peche',
        scope: 'review:read',
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
