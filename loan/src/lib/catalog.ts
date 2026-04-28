import fs from 'fs'
import path from 'path'
import type { Catalog, CatalogCoin } from '@/types/catalog'

let _catalog: Catalog | null = null

export function getCatalog(): Catalog {
  if (_catalog) return _catalog
  const filePath = path.join(process.cwd(), 'public', 'catalog.json')
  if (!fs.existsSync(filePath)) {
    return { generated_at: '', count: 0, coins: [] }
  }
  _catalog = JSON.parse(fs.readFileSync(filePath, 'utf-8')) as Catalog
  return _catalog
}

export function getCoin(eurioId: string): CatalogCoin | undefined {
  return getCatalog().coins.find(c => c.eurio_id === eurioId)
}
