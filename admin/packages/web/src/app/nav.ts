import { Brain, ClipboardList, Coins, Eye, LayoutDashboard, Layers, Network, Scale } from 'lucide-vue-next'
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
    ],
  },
  {
    title: 'Système',
    items: [
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
    ],
  },
  // Futurs domaines :
  // { title: 'Marketplace', items: [{ id: 'marketplace', ... }] },
  // { title: 'Utilisateurs', items: [{ id: 'users', ... }] },
]
