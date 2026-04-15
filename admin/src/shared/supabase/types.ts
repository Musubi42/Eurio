// Types Supabase générés manuellement — à régénérer avec :
//   supabase gen types typescript --project-id <id> > src/shared/supabase/types.ts
//
// Pour l'instant, types stricts alignés sur sets-architecture.md §4.

export type Json = string | number | boolean | null | { [key: string]: Json } | Json[]

export interface Database {
  public: {
    Tables: {
      sets: {
        Row: Set
        Insert: Omit<Set, 'created_at' | 'updated_at'>
        Update: Partial<Omit<Set, 'id' | 'created_at'>>
      }
      set_members: {
        Row: SetMember
        Insert: SetMember
        Update: Partial<SetMember>
      }
      sets_audit: {
        Row: SetAudit
        Insert: Omit<SetAudit, 'id' | 'at'>
        Update: never
      }
      coins: {
        Row: Coin
        Insert: never
        Update: never
      }
    }
  }
}

export interface Set {
  id: string
  kind: 'structural' | 'curated' | 'parametric'
  name_i18n: I18nField
  description_i18n: I18nField | null
  criteria: SetCriteria | null
  param_key: string | null
  reward: SetReward | null
  display_order: number
  category: SetCategory
  icon: string | null
  expected_count: number | null
  active: boolean
  created_at: string
  updated_at: string
}

export interface SetMember {
  set_id: string
  eurio_id: string
  position: number | null
}

export interface SetAudit {
  id: number
  set_id: string
  action: 'create' | 'update' | 'delete' | 'activate' | 'deactivate' | 'publish'
  before: Json | null
  after: Json | null
  actor: string
  at: string
}

export interface Coin {
  eurio_id: string
  country: string
  year: number
  denomination: number
  title: string | null
  issue_type: IssueType | null
  series: string | null
  ruler: string | null
  theme_code: string | null
  mintage: number | null
  series_rank: number | null
  numista_id: number | null
  active: boolean
}

// DSL criteria — figé v1 (sets-architecture.md §3)
export interface SetCriteria {
  country?: string | string[]
  issue_type?: IssueType | IssueType[]
  year?: number | [number, number] | 'current'
  denomination?: number[]
  series?: string
  ruler?: string
  theme_code?: string
  distinct_by?: 'country'
  min_mintage?: number
  max_mintage?: number
}

export type IssueType =
  | 'circulation'
  | 'commemo-national'
  | 'commemo-common'
  | 'starter-kit'
  | 'bu-set'
  | 'proof'

export type SetCategory = 'country' | 'theme' | 'tier' | 'personal' | 'hunt'

export interface I18nField {
  fr: string
  en?: string
  de?: string
  it?: string
}

export interface SetReward {
  badge?: 'bronze' | 'silver' | 'gold'
  xp?: number
  level_bump?: boolean
}
