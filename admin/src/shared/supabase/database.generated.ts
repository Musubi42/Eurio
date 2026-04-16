/**
 * AUTO-GENERATED — ne pas éditer à la main.
 *
 * Régénérer avec :
 *   mcp__supabase__generate_typescript_types  (via Claude / Supabase MCP)
 * Ou :
 *   supabase gen types typescript --project-id <id>
 *
 * Dernière regen : 2026-04-15
 */
export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  __InternalSupabase: {
    PostgrestVersion: '14.5'
  }
  public: {
    Tables: {
      coin_embeddings: {
        Row: {
          created_at: string
          embedding: number[]
          eurio_id: string
          model_version: string
        }
        Insert: {
          created_at?: string
          embedding: number[]
          eurio_id: string
          model_version: string
        }
        Update: {
          created_at?: string
          embedding?: number[]
          eurio_id?: string
          model_version?: string
        }
        Relationships: [
          {
            foreignKeyName: 'coin_embeddings_eurio_id_fkey'
            columns: ['eurio_id']
            isOneToOne: true
            referencedRelation: 'coins'
            referencedColumns: ['eurio_id']
          },
        ]
      }
      coin_series: {
        Row: {
          country: string
          created_at: string
          description: string | null
          designation: string
          designation_i18n: Json | null
          id: string
          minting_end_reason: string | null
          minting_ended_at: string | null
          minting_started_at: string
          superseded_by_series_id: string | null
          supersedes_series_id: string | null
          updated_at: string
        }
        Insert: {
          country: string
          created_at?: string
          description?: string | null
          designation: string
          designation_i18n?: Json | null
          id: string
          minting_end_reason?: string | null
          minting_ended_at?: string | null
          minting_started_at: string
          superseded_by_series_id?: string | null
          supersedes_series_id?: string | null
          updated_at?: string
        }
        Update: {
          country?: string
          created_at?: string
          description?: string | null
          designation?: string
          designation_i18n?: Json | null
          id?: string
          minting_end_reason?: string | null
          minting_ended_at?: string | null
          minting_started_at?: string
          superseded_by_series_id?: string | null
          supersedes_series_id?: string | null
          updated_at?: string
        }
      }
      coins: {
        Row: {
          collector_only: boolean
          country: string
          cross_refs: Json
          currency: string
          design_description: string | null
          eurio_id: string
          face_value: number
          first_seen: string
          images: Json
          is_commemorative: boolean
          is_withdrawn: boolean
          issue_type: string | null
          last_updated: string
          mintage: number | null
          national_variants: Json | null
          needs_review: boolean
          review_reason: string | null
          series_id: string | null
          sources_used: string[]
          theme: string | null
          withdrawal_reason: string | null
          withdrawn_at: string | null
          year: number
        }
        Insert: {
          collector_only?: boolean
          country: string
          cross_refs?: Json
          currency?: string
          design_description?: string | null
          eurio_id: string
          face_value: number
          first_seen?: string
          images?: Json
          is_commemorative?: boolean
          is_withdrawn?: boolean
          issue_type?: string | null
          last_updated?: string
          mintage?: number | null
          national_variants?: Json | null
          needs_review?: boolean
          review_reason?: string | null
          series_id?: string | null
          sources_used?: string[]
          theme?: string | null
          withdrawal_reason?: string | null
          withdrawn_at?: string | null
          year: number
        }
        Update: {
          collector_only?: boolean
          country?: string
          cross_refs?: Json
          currency?: string
          design_description?: string | null
          eurio_id?: string
          face_value?: number
          first_seen?: string
          images?: Json
          is_commemorative?: boolean
          is_withdrawn?: boolean
          issue_type?: string | null
          last_updated?: string
          mintage?: number | null
          national_variants?: Json | null
          needs_review?: boolean
          review_reason?: string | null
          series_id?: string | null
          sources_used?: string[]
          theme?: string | null
          withdrawal_reason?: string | null
          withdrawn_at?: string | null
          year?: number
        }
      }
      set_members: {
        Row: {
          eurio_id: string
          position: number | null
          set_id: string
        }
        Insert: {
          eurio_id: string
          position?: number | null
          set_id: string
        }
        Update: {
          eurio_id?: string
          position?: number | null
          set_id?: string
        }
      }
      sets: {
        Row: {
          active: boolean
          category: string
          created_at: string
          criteria: Json | null
          description_i18n: Json | null
          display_order: number
          expected_count: number | null
          icon: string | null
          id: string
          kind: string
          name_i18n: Json
          param_key: string | null
          reward: Json | null
          updated_at: string
        }
        Insert: {
          active?: boolean
          category: string
          created_at?: string
          criteria?: Json | null
          description_i18n?: Json | null
          display_order?: number
          expected_count?: number | null
          icon?: string | null
          id: string
          kind: string
          name_i18n: Json
          param_key?: string | null
          reward?: Json | null
          updated_at?: string
        }
        Update: {
          active?: boolean
          category?: string
          created_at?: string
          criteria?: Json | null
          description_i18n?: Json | null
          display_order?: number
          expected_count?: number | null
          icon?: string | null
          id?: string
          kind?: string
          name_i18n?: Json
          param_key?: string | null
          reward?: Json | null
          updated_at?: string
        }
      }
      sets_audit: {
        Row: {
          action: string
          actor: string
          after: Json | null
          at: string
          before: Json | null
          id: number
          set_id: string
        }
        Insert: {
          action: string
          actor: string
          after?: Json | null
          at?: string
          before?: Json | null
          id?: number
          set_id: string
        }
        Update: {
          action?: string
          actor?: string
          after?: Json | null
          at?: string
          before?: Json | null
          id?: number
          set_id?: string
        }
      }
    }
    Views: { [_ in never]: never }
    Functions: { [_ in never]: never }
    Enums: { [_ in never]: never }
    CompositeTypes: { [_ in never]: never }
  }
}
