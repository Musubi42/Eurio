import { ClipboardList, Coins, LayoutDashboard, Layers } from 'lucide-vue-next'
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
  // Futurs domaines :
  // { title: 'Marketplace', items: [{ id: 'marketplace', ... }] },
  // { title: 'Utilisateurs', items: [{ id: 'users', ... }] },
]
