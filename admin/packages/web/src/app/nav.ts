import { Brain, CircleAlert, ClipboardList, Coins, Database, Eye, FlaskConical, LayoutDashboard, Layers, Network, Scale, TrendingUp } from 'lucide-vue-next'
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
        id: 'audit',
        label: 'Audit log',
        icon: ClipboardList,
        route: '/audit',
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
        id: 'benchmark',
        label: 'Benchmark',
        icon: TrendingUp,
        route: '/benchmark',
      },
      {
        id: 'lab',
        label: 'Lab',
        icon: FlaskConical,
        route: '/lab',
      },
    ],
  },
  // Futurs domaines :
  // { title: 'Marketplace', items: [{ id: 'marketplace', ... }] },
  // { title: 'Utilisateurs', items: [{ id: 'users', ... }] },
]
