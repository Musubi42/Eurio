/**
 * Les vignettes canoniques d'une liste de pièces — un point unique.
 *
 * POURQUOI PAS `<img src="/referential/canonical/…/thumb">`
 * ---------------------------------------------------------
 * Cette route-là est gardée par `coins:read`, et une balise `<img>` **n'envoie
 * pas d'en-tête `Authorization`**. En cookie (front hébergé, même site) le
 * navigateur joint la session tout seul ; en **PAT** — le mode de tout poste de
 * dev — elle répond 401 et l'image ne s'affiche pas, sans une ligne en console.
 * Mesuré le 2026-08-24 : `401` sans en-tête, `302` avec.
 *
 * `GET /referential/canonical-thumbs` rend l'ADRESSE au lieu de l'image : des
 * URLs CDN publiques (ou du référentiel externe) qui n'exigent aucun en-tête.
 * Elles marchent dans les deux modes, se mettent en cache navigateur, et ne
 * traversent pas l'API.
 *
 * POURQUOI PAR PAQUETS DE 60
 * --------------------------
 * L'accueil affiche 253 pièces. Tout demander d'un coup ferait une query string
 * de ~10 Ko — au-delà de ce que certains proxys laissent passer, et la panne
 * serait un 414 en production seulement. 60 identifiants ≈ 2,5 Ko : cinq appels,
 * aucune limite frôlée.
 *
 * ⛔ UNE VIGNETTE MANQUANTE N'EST PAS UNE ERREUR. Elle rend `null`, l'appelant
 * dessine son propre vide, et la liste reste utilisable — on ne bloque jamais un
 * travail sur une image d'illustration.
 */
import { ref, type Ref } from 'vue'

import { eurioApi } from '@/shared/api/eurio-api'

const TAILLE_PAQUET = 60

interface Reponse { urls: Record<string, string | null> }

export function useCanonicalThumbs() {
  /** `class_id` → URL, ou `null` quand le référentiel n'a rien. Une clé absente
   *  signifie « pas encore demandé », ce qui n'est pas la même chose. */
  const urls: Ref<Record<string, string | null>> = ref({})

  /**
   * Ce qui est DÉJÀ demandé mais pas encore revenu.
   *
   * 🔴 SANS LUI, LE MÊME LOT PART PLUSIEURS FOIS. Mesuré au navigateur le
   * 2026-08-24 : 8 requêtes pour 253 pièces au lieu de 5, dont **7 copies
   * identiques** d'un même paquet de 13.
   *
   * La cause est une boucle : l'appelant surveille la liste, chaque paquet qui
   * revient modifie `urls`, ce qui recalcule la liste, ce qui redéclenche
   * `load()` — et pendant qu'un paquet est en vol ses identifiants ne sont pas
   * encore dans `urls`, donc ils repartent. `urls` seul ne peut pas répondre
   * « déjà demandé » ; il ne connaît que « déjà revenu ».
   *
   * Personne ne l'aurait vu depuis l'écran : les réponses sont identiques et
   * toutes en 200. Seul le compte des requêtes le disait.
   */
  const enVol = new Set<string>()

  async function load(ids: string[]): Promise<void> {
    const manquants = [...new Set(ids)].filter(
      (id) => !(id in urls.value) && !enVol.has(id),
    )
    if (!manquants.length) return
    for (const id of manquants) enVol.add(id)
    for (let i = 0; i < manquants.length; i += TAILLE_PAQUET) {
      const paquet = manquants.slice(i, i + TAILLE_PAQUET)
      try {
        const r = await eurioApi.get<Reponse>(
          `/referential/canonical-thumbs?ids=${encodeURIComponent(paquet.join(','))}`,
        )
        urls.value = { ...urls.value, ...r.urls }
      } catch {
        // Un paquet qui tombe ne doit pas emporter les autres, ni la liste.
        // On marque ce paquet comme « sans image » plutôt que de le redemander
        // en boucle : l'appelant dessinera son vide, et l'écran reste utilisable.
        const vides: Record<string, string | null> = {}
        for (const id of paquet) vides[id] = null
        urls.value = { ...urls.value, ...vides }
      } finally {
        // Le paquet est retombé — succès ou échec, il n'est plus en vol. Sans
        // ce `finally`, un paquet en erreur resterait marqué « demandé » à vie
        // et ne serait jamais réessayé au chargement suivant.
        for (const id of paquet) enVol.delete(id)
      }
    }
  }

  return { urls, load }
}
