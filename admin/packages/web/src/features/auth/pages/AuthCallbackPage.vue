<script setup lang="ts">
// Page de callback après clic sur le magic link.
// Supabase redirige ici avec le token dans l'URL (hash ou query).
// On attend que le client établisse la session, puis on redirige.
import { supabase } from '@/shared/supabase/client'
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const error = ref<string | null>(null)

onMounted(() => {
  // onAuthStateChange capture SIGNED_IN dès que Supabase a traité le token dans l'URL
  const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
    if (event === 'SIGNED_IN' && session) {
      subscription.unsubscribe()
      const role = session.user.app_metadata?.role
      if (role === 'admin') {
        router.replace('/sets')
      } else {
        await supabase.auth.signOut()
        error.value = 'Accès refusé — ce compte n\'a pas le rôle admin.'
      }
    }

    if (event === 'SIGNED_OUT') {
      subscription.unsubscribe()
      router.replace('/login')
    }
  })

  // Fallback : si la session est déjà là (rechargement de page)
  supabase.auth.getSession().then(({ data: { session } }) => {
    if (session) {
      subscription.unsubscribe()
      const role = session.user.app_metadata?.role
      if (role === 'admin') {
        router.replace('/sets')
      } else {
        supabase.auth.signOut().then(() => {
          error.value = 'Accès refusé — ce compte n\'a pas le rôle admin.'
        })
      }
    }
  })

  // Timeout de sécurité : si rien ne se passe en 10s
  setTimeout(() => {
    subscription.unsubscribe()
    if (!error.value) router.replace('/login')
  }, 10_000)
})
</script>

<template>
  <div class="flex min-h-screen items-center justify-center"
       style="background: var(--indigo-900);">
    <div class="text-center">
      <template v-if="error">
        <p class="text-sm font-medium" style="color: var(--danger);">{{ error }}</p>
        <button
          class="mt-4 text-xs underline"
          style="color: rgba(255,255,255,0.4);"
          @click="$router.replace('/login')"
        >
          Retour à la connexion
        </button>
      </template>
      <template v-else>
        <!-- Spinner minimaliste -->
        <div class="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
             style="border-color: var(--gold); border-top-color: transparent;" />
        <p class="mt-3 text-sm" style="color: rgba(255,255,255,0.4);">
          Connexion en cours…
        </p>
      </template>
    </div>
  </div>
</template>
