/**
 * AUTO-GENERATED — ne pas éditer à la main.
 *
 * Régénérer avec :
 *   mcp__supabase__generate_typescript_types  (via Claude / Supabase MCP)
 * Ou :
 *   supabase gen types typescript --project-id <id>
 *
 * Dernière regen : 2026-06-01 (schéma app-facing v2, cf docs/research/supabase-app-schema-v2.md)
 */

export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  // Allows to automatically instantiate createClient with right options
  // instead of createClient<Database, { PostgrestVersion: 'XX' }>(URL, KEY)
  __InternalSupabase: {
    PostgrestVersion: "14.5"
  }
  public: {
    Tables: {
      coin: {
        Row: {
          canonical_eurio_id: string | null
          collector_only: boolean
          composition: string | null
          country: string
          country_name: string | null
          demonetized: boolean | null
          demonetized_on: string | null
          design_description: string | null
          design_group_id: string | null
          diameter_mm: number | null
          edge_description: string | null
          edge_lettering: string | null
          eurio_id: string
          face_value_cents: number
          is_commemorative: boolean
          mintage: number | null
          obverse_lettering: string | null
          orientation: string | null
          reverse_lettering: string | null
          series_id: string | null
          shape: string | null
          shared_reverse_id: string | null
          theme: string | null
          thickness_mm: number | null
          updated_at: string
          variant_kind: string
          weight_g: number | null
          year: number
        }
        Insert: {
          canonical_eurio_id?: string | null
          collector_only?: boolean
          composition?: string | null
          country: string
          country_name?: string | null
          demonetized?: boolean | null
          demonetized_on?: string | null
          design_description?: string | null
          design_group_id?: string | null
          diameter_mm?: number | null
          edge_description?: string | null
          edge_lettering?: string | null
          eurio_id: string
          face_value_cents: number
          is_commemorative?: boolean
          mintage?: number | null
          obverse_lettering?: string | null
          orientation?: string | null
          reverse_lettering?: string | null
          series_id?: string | null
          shape?: string | null
          shared_reverse_id?: string | null
          theme?: string | null
          thickness_mm?: number | null
          updated_at?: string
          variant_kind?: string
          weight_g?: number | null
          year: number
        }
        Update: {
          canonical_eurio_id?: string | null
          collector_only?: boolean
          composition?: string | null
          country?: string
          country_name?: string | null
          demonetized?: boolean | null
          demonetized_on?: string | null
          design_description?: string | null
          design_group_id?: string | null
          diameter_mm?: number | null
          edge_description?: string | null
          edge_lettering?: string | null
          eurio_id?: string
          face_value_cents?: number
          is_commemorative?: boolean
          mintage?: number | null
          obverse_lettering?: string | null
          orientation?: string | null
          reverse_lettering?: string | null
          series_id?: string | null
          shape?: string | null
          shared_reverse_id?: string | null
          theme?: string | null
          thickness_mm?: number | null
          updated_at?: string
          variant_kind?: string
          weight_g?: number | null
          year?: number
        }
        Relationships: [
          {
            foreignKeyName: "coin_canonical_eurio_id_fkey"
            columns: ["canonical_eurio_id"]
            isOneToOne: false
            referencedRelation: "coin"
            referencedColumns: ["eurio_id"]
          },
          {
            foreignKeyName: "coin_design_group_id_fkey"
            columns: ["design_group_id"]
            isOneToOne: false
            referencedRelation: "design_group"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "coin_series_id_fkey"
            columns: ["series_id"]
            isOneToOne: false
            referencedRelation: "coin_series"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "coin_shared_reverse_id_fkey"
            columns: ["shared_reverse_id"]
            isOneToOne: false
            referencedRelation: "shared_reverse"
            referencedColumns: ["id"]
          },
        ]
      }
      coin_credit: {
        Row: {
          eurio_id: string
          id: number
          name: string
          position: number | null
          role: string
        }
        Insert: {
          eurio_id: string
          id?: never
          name: string
          position?: number | null
          role: string
        }
        Update: {
          eurio_id?: string
          id?: never
          name?: string
          position?: number | null
          role?: string
        }
        Relationships: [
          {
            foreignKeyName: "coin_credit_eurio_id_fkey"
            columns: ["eurio_id"]
            isOneToOne: false
            referencedRelation: "coin"
            referencedColumns: ["eurio_id"]
          },
        ]
      }
      coin_description_i18n: {
        Row: {
          description: string | null
          eurio_id: string
          lang: string
          title: string
        }
        Insert: {
          description?: string | null
          eurio_id: string
          lang: string
          title: string
        }
        Update: {
          description?: string | null
          eurio_id?: string
          lang?: string
          title?: string
        }
        Relationships: [
          {
            foreignKeyName: "coin_description_i18n_eurio_id_fkey"
            columns: ["eurio_id"]
            isOneToOne: false
            referencedRelation: "coin"
            referencedColumns: ["eurio_id"]
          },
        ]
      }
      coin_image: {
        Row: {
          eurio_id: string
          height: number | null
          id: number
          license: string | null
          role: string
          source: string
          storage_path: string
          width: number | null
        }
        Insert: {
          eurio_id: string
          height?: number | null
          id?: never
          license?: string | null
          role?: string
          source: string
          storage_path: string
          width?: number | null
        }
        Update: {
          eurio_id?: string
          height?: number | null
          id?: never
          license?: string | null
          role?: string
          source?: string
          storage_path?: string
          width?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "coin_image_eurio_id_fkey"
            columns: ["eurio_id"]
            isOneToOne: false
            referencedRelation: "coin"
            referencedColumns: ["eurio_id"]
          },
        ]
      }
      coin_mint_release: {
        Row: {
          id: string
          issue_type: string | null
          mint_id: string | null
          mint_year: number | null
          mintage: number | null
          parent_type_id: string
        }
        Insert: {
          id: string
          issue_type?: string | null
          mint_id?: string | null
          mint_year?: number | null
          mintage?: number | null
          parent_type_id: string
        }
        Update: {
          id?: string
          issue_type?: string | null
          mint_id?: string | null
          mint_year?: number | null
          mintage?: number | null
          parent_type_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "coin_mint_release_mint_id_fkey"
            columns: ["mint_id"]
            isOneToOne: false
            referencedRelation: "mint"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "coin_mint_release_parent_type_id_fkey"
            columns: ["parent_type_id"]
            isOneToOne: false
            referencedRelation: "coin"
            referencedColumns: ["eurio_id"]
          },
        ]
      }
      coin_name_i18n: {
        Row: {
          eurio_id: string
          lang: string
          title: string
        }
        Insert: {
          eurio_id: string
          lang: string
          title: string
        }
        Update: {
          eurio_id?: string
          lang?: string
          title?: string
        }
        Relationships: [
          {
            foreignKeyName: "coin_name_i18n_eurio_id_fkey"
            columns: ["eurio_id"]
            isOneToOne: false
            referencedRelation: "coin"
            referencedColumns: ["eurio_id"]
          },
        ]
      }
      coin_price: {
        Row: {
          buy_url: string | null
          currency: string
          eurio_id: string
          grade: string | null
          id: number
          kind: string
          p_high: number | null
          p_low: number | null
          p_mid: number | null
          sampled_at: string
          source: string
        }
        Insert: {
          buy_url?: string | null
          currency?: string
          eurio_id: string
          grade?: string | null
          id?: never
          kind: string
          p_high?: number | null
          p_low?: number | null
          p_mid?: number | null
          sampled_at: string
          source: string
        }
        Update: {
          buy_url?: string | null
          currency?: string
          eurio_id?: string
          grade?: string | null
          id?: never
          kind?: string
          p_high?: number | null
          p_low?: number | null
          p_mid?: number | null
          sampled_at?: string
          source?: string
        }
        Relationships: [
          {
            foreignKeyName: "coin_price_eurio_id_fkey"
            columns: ["eurio_id"]
            isOneToOne: false
            referencedRelation: "coin"
            referencedColumns: ["eurio_id"]
          },
        ]
      }
      coin_series: {
        Row: {
          country: string | null
          designation: string | null
          designation_i18n_json: Json | null
          id: string
          minting_end_reason: string | null
          minting_ended_at: string | null
          minting_started_at: string | null
          supersedes_series_id: string | null
        }
        Insert: {
          country?: string | null
          designation?: string | null
          designation_i18n_json?: Json | null
          id: string
          minting_end_reason?: string | null
          minting_ended_at?: string | null
          minting_started_at?: string | null
          supersedes_series_id?: string | null
        }
        Update: {
          country?: string | null
          designation?: string | null
          designation_i18n_json?: Json | null
          id?: string
          minting_end_reason?: string | null
          minting_ended_at?: string | null
          minting_started_at?: string | null
          supersedes_series_id?: string | null
        }
        Relationships: [
          {
            foreignKeyName: "coin_series_supersedes_series_id_fkey"
            columns: ["supersedes_series_id"]
            isOneToOne: false
            referencedRelation: "coin_series"
            referencedColumns: ["id"]
          },
        ]
      }
      coin_topic: {
        Row: {
          eurio_id: string
          id: number
          lang: string
          topic: string
        }
        Insert: {
          eurio_id: string
          id?: never
          lang: string
          topic: string
        }
        Update: {
          eurio_id?: string
          id?: never
          lang?: string
          topic?: string
        }
        Relationships: [
          {
            foreignKeyName: "coin_topic_eurio_id_fkey"
            columns: ["eurio_id"]
            isOneToOne: false
            referencedRelation: "coin"
            referencedColumns: ["eurio_id"]
          },
        ]
      }
      design_group: {
        Row: {
          designation: string | null
          designation_i18n_json: Json | null
          id: string
        }
        Insert: {
          designation?: string | null
          designation_i18n_json?: Json | null
          id: string
        }
        Update: {
          designation?: string | null
          designation_i18n_json?: Json | null
          id?: string
        }
        Relationships: []
      }
      mint: {
        Row: {
          city: string | null
          country: string | null
          display_name: string | null
          id: string
          mark: string | null
        }
        Insert: {
          city?: string | null
          country?: string | null
          display_name?: string | null
          id: string
          mark?: string | null
        }
        Update: {
          city?: string | null
          country?: string | null
          display_name?: string | null
          id?: string
          mark?: string | null
        }
        Relationships: []
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
        Relationships: [
          {
            foreignKeyName: "set_members_eurio_id_fkey"
            columns: ["eurio_id"]
            isOneToOne: false
            referencedRelation: "coin"
            referencedColumns: ["eurio_id"]
          },
          {
            foreignKeyName: "set_members_set_id_fkey"
            columns: ["set_id"]
            isOneToOne: false
            referencedRelation: "sets"
            referencedColumns: ["id"]
          },
        ]
      }
      sets: {
        Row: {
          active: boolean
          category: string | null
          criteria: Json | null
          description_i18n: Json | null
          display_order: number | null
          expected_count: number | null
          icon: string | null
          id: string
          kind: string | null
          name_i18n: Json | null
          param_key: string | null
          reward: Json | null
        }
        Insert: {
          active?: boolean
          category?: string | null
          criteria?: Json | null
          description_i18n?: Json | null
          display_order?: number | null
          expected_count?: number | null
          icon?: string | null
          id: string
          kind?: string | null
          name_i18n?: Json | null
          param_key?: string | null
          reward?: Json | null
        }
        Update: {
          active?: boolean
          category?: string | null
          criteria?: Json | null
          description_i18n?: Json | null
          display_order?: number | null
          expected_count?: number | null
          icon?: string | null
          id?: string
          kind?: string | null
          name_i18n?: Json | null
          param_key?: string | null
          reward?: Json | null
        }
        Relationships: []
      }
      shared_reverse: {
        Row: {
          applies_to: string | null
          asset_name: string
          id: string
          label: string
          map_version: number | null
        }
        Insert: {
          applies_to?: string | null
          asset_name: string
          id: string
          label: string
          map_version?: number | null
        }
        Update: {
          applies_to?: string | null
          asset_name?: string
          id?: string
          label?: string
          map_version?: number | null
        }
        Relationships: []
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      [_ in never]: never
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {},
  },
} as const
