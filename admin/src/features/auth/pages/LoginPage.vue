<script setup lang="ts">
import { supabase } from '@/shared/supabase/client'
import { Mail } from 'lucide-vue-next'
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const email = ref('')
const loading = ref(false)
const sent = ref(false)
const error = ref<string | null>(null)

async function sendMagicLink() {
  if (!email.value.trim()) return

  loading.value = true
  error.value = null

  const { error: authError } = await supabase.auth.signInWithOtp({
    email: email.value.trim(),
    options: {
      emailRedirectTo: `${window.location.origin}/auth/callback`,
    },
  })

  loading.value = false

  if (authError) {
    error.value = authError.message
  } else {
    sent.value = true
  }
}

// Si déjà connecté avec le bon rôle, rediriger directement
supabase.auth.getSession().then(({ data: { session } }) => {
  if (session?.user.app_metadata?.role === 'admin') {
    router.push('/')
  }
})
</script>

<template>
  <div class="flex min-h-screen items-center justify-center px-4"
       style="background: var(--indigo-900);">

    <div class="w-full max-w-sm">
      <!-- Card -->
      <div class="rounded-lg p-8 shadow-lg"
           style="background: var(--surface); box-shadow: var(--shadow-lg);">

        <!-- Header -->
        <div class="mb-8 text-center">
          <h1 class="font-display text-3xl italic font-semibold leading-tight"
              style="color: var(--indigo-700);">
            Eurio
          </h1>
          <p class="mt-1 text-sm font-ui"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            CABINET DE L'ADMINISTRATEUR
          </p>
          <!-- Séparateur or -->
          <div class="mx-auto mt-4 h-px w-16"
               style="background: var(--gold);"></div>
        </div>

        <!-- Sent state -->
        <template v-if="sent">
          <div class="text-center">
            <div class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full"
                 style="background: var(--success-soft);">
              <Mail class="h-5 w-5" style="color: var(--success);" />
            </div>
            <p class="font-medium text-sm" style="color: var(--ink);">
              Lien envoyé
            </p>
            <p class="mt-1 text-sm" style="color: var(--ink-500);">
              Vérifiez <strong>{{ email }}</strong><br />et cliquez sur le lien de connexion.
            </p>
            <button
              class="mt-6 text-xs underline underline-offset-4 transition-opacity hover:opacity-70"
              style="color: var(--ink-400);"
              @click="sent = false"
            >
              Renvoyer
            </button>
          </div>
        </template>

        <!-- Form -->
        <template v-else>
          <form @submit.prevent="sendMagicLink" class="space-y-4">
            <div>
              <label for="email" class="block text-xs font-medium mb-1.5"
                     style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
                ADRESSE EMAIL
              </label>
              <input
                id="email"
                v-model="email"
                type="email"
                autocomplete="email"
                required
                placeholder="raphaelthi59@gmail.com"
                class="w-full rounded-md border px-3 py-2 text-sm outline-none transition-all
                       focus:ring-2 placeholder:opacity-40"
                style="
                  border-color: var(--surface-3);
                  background: var(--surface);
                  color: var(--ink);
                  --tw-ring-color: var(--indigo-700);
                "
              />
            </div>

            <div v-if="error"
                 class="rounded-md px-3 py-2 text-sm"
                 style="background: var(--danger-soft); color: var(--danger);">
              {{ error }}
            </div>

            <button
              type="submit"
              :disabled="loading || !email.trim()"
              class="w-full rounded-md px-4 py-2.5 text-sm font-medium transition-all
                     disabled:opacity-50 disabled:cursor-not-allowed"
              style="background: var(--indigo-700); color: white;"
            >
              {{ loading ? 'Envoi…' : 'Envoyer le lien magique' }}
            </button>
          </form>
        </template>
      </div>

      <!-- Footer -->
      <p class="mt-4 text-center text-xs" style="color: rgba(255,255,255,0.2);">
        Accès restreint — Eurio Admin v1
      </p>
    </div>
  </div>
</template>
