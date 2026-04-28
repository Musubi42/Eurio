export type IssueType =
  | 'circulation'
  | 'commemo-national'
  | 'commemo-common'
  | 'starter-kit'
  | 'bu-set'
  | 'proof'

export type CatalogCoin = {
  eurio_id: string
  country: string
  year: number
  face_value: 2
  is_commemorative: boolean
  issue_type: IssueType | null
  theme: string | null
  design_description: string | null
  mintage: number | null
  images: string[]
  cross_refs: {
    numista_id?: string
    wikipedia?: string
    lmdlp?: string
    [k: string]: string | undefined
  }
  personal_owned: boolean
  market_prices?: {
    ebay_median?: number
    monnaie_de_paris?: number
    fetched_at: string
  }
}

export type Catalog = {
  generated_at: string
  count: number
  coins: CatalogCoin[]
}
