import { getCatalog, getCoin } from '@/lib/catalog'
import { notFound } from 'next/navigation'
import CoinDetailClient from './CoinDetailClient'

export async function generateStaticParams() {
  const catalog = getCatalog()
  return catalog.coins.map(c => ({ eurio_id: c.eurio_id }))
}

type Props = { params: Promise<{ eurio_id: string }> }

export default async function CoinDetailPage({ params }: Props) {
  const { eurio_id } = await params
  const coin = getCoin(decodeURIComponent(eurio_id))
  if (!coin) notFound()
  return <CoinDetailClient coin={coin} />
}
