import { createClient } from '@supabase/supabase-js'
import sharp from 'sharp'
import fs from 'fs'
import path from 'path'
import https from 'https'
import http from 'http'

const SUPABASE_URL = process.env.SUPABASE_URL
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.error('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set')
  process.exit(1)
}

const supabase = createClient(SUPABASE_URL, SUPABASE_KEY)

const PUBLIC_DIR = path.join(process.cwd(), 'public')
const COINS_DIR = path.join(PUBLIC_DIR, 'coins')
const CATALOG_PATH = path.join(PUBLIC_DIR, 'catalog.json')

function download(url: string): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const proto = url.startsWith('https') ? https : http
    proto.get(url, (res) => {
      const chunks: Buffer[] = []
      res.on('data', (c: Buffer) => chunks.push(c))
      res.on('end', () => resolve(Buffer.concat(chunks)))
      res.on('error', reject)
    }).on('error', reject)
  })
}

async function main() {
  fs.mkdirSync(COINS_DIR, { recursive: true })

  // Fetch curated 2€ coins
  const { data: coins, error } = await supabase
    .from('coins')
    .select('eurio_id, country, year, face_value, is_commemorative, issue_type, theme, design_description, mintage, images, cross_refs, personal_owned')
    .eq('face_value', 2)
    .not('cross_refs->numista_id', 'is', null)
    .neq('images', '[]')
    .not('images', 'is', null)
    .order('country')
    .order('year', { ascending: false })
    .order('eurio_id')

  if (error) { console.error('Supabase error:', error); process.exit(1) }
  if (!coins) { console.error('No coins returned'); process.exit(1) }

  console.log(`Fetched ${coins.length} curated 2€ coins`)

  // Fetch market prices (latest per eurio_id)
  const { data: pricesRaw } = await supabase
    .from('coin_market_prices')
    .select('eurio_id, source, price_eur, fetched_at')
    .in('eurio_id', coins.map((c: {eurio_id: string}) => c.eurio_id))
    .order('fetched_at', { ascending: false })

  const pricesByEurioId = new Map<string, { ebay_median?: number; monnaie_de_paris?: number; fetched_at: string }>()
  for (const p of pricesRaw ?? []) {
    const existing = pricesByEurioId.get(p.eurio_id) ?? { fetched_at: p.fetched_at }
    if (p.source === 'ebay' && existing.ebay_median == null) existing.ebay_median = p.price_eur
    if (p.source === 'monnaie_de_paris' && existing.monnaie_de_paris == null) existing.monnaie_de_paris = p.price_eur
    if (!pricesByEurioId.has(p.eurio_id)) pricesByEurioId.set(p.eurio_id, existing)
  }

  let imageCount = 0
  let skippedCount = 0
  let totalBytes = 0

  const catalogCoins = []

  for (const coin of coins) {
    // images is { obverse: [{url, source, thumb_url}], reverse: [...] }
    type ImgEntry = { url: string; source: string; thumb_url?: string }
    type ImagesObj = { obverse?: ImgEntry[]; reverse?: ImgEntry[] }
    const imagesObj = (coin.images ?? {}) as ImagesObj
    const imageUrls: string[] = [
      ...(imagesObj.obverse?.map(e => e.url) ?? []),
      ...(imagesObj.reverse?.map(e => e.url) ?? []),
    ]

    const localImages: string[] = []
    const coinDir = path.join(COINS_DIR, coin.eurio_id)
    fs.mkdirSync(coinDir, { recursive: true })

    for (let i = 0; i < imageUrls.length; i++) {
      const imageUrl = imageUrls[i]
      const outPath = path.join(coinDir, `${i}.jpg`)
      const relPath = `/coins/${coin.eurio_id}/${i}.jpg`
      localImages.push(relPath)

      if (fs.existsSync(outPath)) {
        skippedCount++
        continue
      }

      try {
        const buf = await download(imageUrl)
        const resized = await sharp(buf).resize({ width: 800, withoutEnlargement: true }).jpeg({ quality: 80 }).toBuffer()
        fs.writeFileSync(outPath, resized)
        totalBytes += resized.length
        imageCount++

        if (imageCount % 50 === 0) console.log(`  ${imageCount} images downloaded…`)
      } catch (e) {
        console.warn(`  Failed to download image for ${coin.eurio_id}[${i}]: ${(e as Error).message}`)
      }
    }

    const market_prices = pricesByEurioId.get(coin.eurio_id)

    catalogCoins.push({
      eurio_id: coin.eurio_id,
      country: coin.country,
      year: coin.year,
      face_value: coin.face_value,
      is_commemorative: coin.is_commemorative,
      issue_type: coin.issue_type ?? null,
      theme: coin.theme ?? null,
      design_description: coin.design_description ?? null,
      mintage: coin.mintage ?? null,
      images: localImages,
      cross_refs: coin.cross_refs ?? {},
      personal_owned: !!coin.personal_owned,
      ...(market_prices ? { market_prices } : {}),
    })
  }

  const catalog = {
    generated_at: new Date().toISOString(),
    count: catalogCoins.length,
    coins: catalogCoins,
  }

  fs.writeFileSync(CATALOG_PATH, JSON.stringify(catalog, null, 2))

  const ownedCount = catalogCoins.filter(c => c.personal_owned).length
  const mb = (totalBytes / 1024 / 1024).toFixed(1)
  console.log(`\nDone: ${catalogCoins.length} coins, ${ownedCount} personal_owned, ${imageCount} images downloaded (${skippedCount} skipped), ~${mb} MB new images`)
  console.log(`Catalog written to ${CATALOG_PATH}`)
}

main().catch(e => { console.error(e); process.exit(1) })
