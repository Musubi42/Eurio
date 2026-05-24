import { Activity, BookOpen, Brain, CircleAlert, ClipboardCheck, ClipboardList, Coins, Database, Eye, FlaskConical, Gavel, LayoutDashboard, Layers, Network, Scale, ShieldQuestion } from 'lucide-vue-next'
import type { Component } from 'vue'

export interface NavItem {
  id: string
  label: string
  icon: Component
  route: string
  badge?: string
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
      },
      {
        id: 'needs-review',
        label: 'Revue référentiel',
        icon: ShieldQuestion,
        route: '/coins/needs-review',
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
      },
      {
        id: 'arbitrage',
        label: 'Arbitrage Numista',
        icon: Scale,
        route: '/coins/arbitrage',
      },
      {
        id: 'training',
        label: 'Training',
        icon: Brain,
        route: '/training',
      },
      {
        id: 'confusion',
        label: 'Cartographie ML',
        icon: Network,
        route: '/confusion',
      },
      {
        id: 'lab',
        label: 'Lab',
        icon: FlaskConical,
        route: '/lab',
      },
      {
        id: 'bench',
        label: 'Studio bench',
        icon: Gavel,
        route: '/bench',
      },
    ],
  },
  // Futurs domaines :
  // { title: 'Marketplace', items: [{ id: 'marketplace', ... }] },
  // { title: 'Utilisateurs', items: [{ id: 'users', ... }] },
]
