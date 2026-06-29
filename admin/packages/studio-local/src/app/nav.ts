import { Activity, BookOpen, Brain, CircleAlert, ClipboardCheck, ClipboardList, Coins, Crop, Database, Eye, FlaskConical, Gavel, KeyRound, LayoutDashboard, Layers, Network, Scale, ShieldQuestion, Users } from 'lucide-vue-next'
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
      },
      {
        id: 'coins',
        label: 'Pièces',
        icon: Coins,
        route: '/coins',
      },
      {
        id: 'numista-review',
        label: 'Revue Numista',
        icon: CircleAlert,
        route: '/coins/numista-review',
        heavy: true,
      },
      {
        id: 'needs-review',
        label: 'Revue référentiel',
        icon: ShieldQuestion,
        route: '/coins/needs-review',
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
      },
      {
        id: 'review',
        label: 'Review queue',
        icon: ClipboardCheck,
        route: '/review',
        heavy: true,
      },
      {
        id: 'audit',
        label: 'Audit log',
        icon: ClipboardList,
        route: '/audit',
      },
      {
        id: 'operations',
        label: 'Operations',
        icon: Activity,
        route: '/operations',
      },
      {
        id: 'referential',
        label: 'Référentiel',
        icon: BookOpen,
        route: '/referential',
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
        // Dépend du devMiddleware (endpoints JSON servis seulement en `pnpm dev`).
        heavy: true,
      },
      {
        id: 'arbitrage',
        label: 'Arbitrage Numista',
        icon: Scale,
        route: '/coins/arbitrage',
        heavy: true,
      },
      {
        id: 'training',
        label: 'Training',
        icon: Brain,
        route: '/training',
        heavy: true,
      },
      {
        id: 'confusion',
        label: 'Cartographie ML',
        icon: Network,
        route: '/confusion',
        heavy: true,
      },
      {
        id: 'lab',
        label: 'Lab',
        icon: FlaskConical,
        route: '/lab',
        heavy: true,
      },
      {
        id: 'bench',
        label: 'Studio bench',
        icon: Gavel,
        route: '/bench',
        heavy: true,
      },
      {
        id: 'crop-bench',
        label: 'Crop Bench',
        icon: Crop,
        route: '/crop-bench',
        heavy: true,
      },
      {
        id: 'denom-gold',
        label: 'Gold denom',
        icon: Coins,
        route: '/denom-gold',
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
      },
      {
        id: 'tokens',
        label: 'Mes tokens',
        icon: KeyRound,
        route: '/me/tokens',
      },
    ],
  },
  // Futurs domaines :
  // { title: 'Marketplace', items: [{ id: 'marketplace', ... }] },
]
