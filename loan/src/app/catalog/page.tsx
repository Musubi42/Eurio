import { getCatalog } from '@/lib/catalog'
import CatalogClient from './CatalogClient'

export default function CatalogPage() {
  const catalog = getCatalog()
  return <CatalogClient coins={catalog.coins} generatedAt={catalog.generated_at} />
}
