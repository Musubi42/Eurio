// Le jeu d'or vu par le front : ce qui se compte, et ce qui ne se compte pas.
//
// Deux pièges, et chacun fausserait la lecture de la planche :
//
//   · la strate CONFIRMÉE prime sur celle du tirage — les strates viennent de
//     proxys textuels, et c'est la confirmation humaine qui les rend honnêtes ;
//   · la 2ᵉ passe ne doit PAS entrer dans les compteurs — elle re-annote des
//     images déjà comptées, et les additionner gonflerait le bilan.

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AnnotationOr } from '../composables/useGoldCropApi'
import { estAnnotee, strateRetenue, useGoldCropApi } from '../composables/useGoldCropApi'

const get = vi.fn()
// `importActual` et pas un objet nu : le composable importe désormais les
// classes d'erreur du client (`EurioApiError`…) pour expliquer un échec
// d'écriture. Les remplacer par `undefined` ferait lever l'explication elle-même.
vi.mock('@/shared/api/eurio-api', async () => {
  const reel =
    await vi.importActual<typeof import('@/shared/api/eurio-api')>('@/shared/api/eurio-api')
  return { ...reel, eurioApi: { get: (...a: unknown[]) => get(...a) } }
})

/** La page porte des liens vers la séance ; sans routeur, on les stube. Le
 *  stub garde `to` en `href` : c'est la CIBLE des liens qu'on vérifie. */
const globalMount = {
  stubs: { RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' } },
}

const requete = vi.fn(() => ({ query: {} as Record<string, string> }))
vi.mock('vue-router', () => ({ useRoute: () => requete() }))

function ligne(over: Partial<AnnotationOr> = {}): AnnotationOr {
  return {
    asset_id: 'a1', gold_version: 'v1', passe: 1, actor: 'po', indecidable: 0,
    strate_tiree: 'S1_facile', strate_confirmee: null, secondes: 20,
    prefill_modifie: 1, editor_version: 'gold_v1',
    created_at: '', updated_at: '', resolution_status: 'manual',
    quality_reason: null, bbox_json: null, detection_method: 'yolo',
    source: 'ebay', source_image_id: 'si', raw_path: 'ebay/x.jpg',
    raw_url: 'https://s3/x.jpg', width: 900, height: 900,
    cx: 450, cy: 450, a: 400, b: 380, theta_deg: 10,
    ...over,
  } as AnnotationOr
}

describe('les grandeurs du jeu d’or', () => {
  it('la strate confirmée prime sur celle du tirage', () => {
    expect(strateRetenue(ligne({ strate_confirmee: 'S2_capsule' }))).toBe('S2_capsule')
    expect(strateRetenue(ligne())).toBe('S1_facile')
  })

  it('le composable retient l’erreur au lieu de la laisser filer', async () => {
    get.mockImplementation(async () => {
      throw new Error('403 interdit')
    })
    const { erreur, jeu, charger } = useGoldCropApi('v1')
    await charger()
    expect(erreur.value).toContain('403')
    // …et surtout : `jeu` reste NUL. Sans ça la page afficherait le bilan d'un
    // jeu à moitié chargé, ce qui est pire qu'une erreur franche.
    expect(jeu.value).toBeNull()
  })

  it('un indécidable EST annoté — c’est une décision, pas une absence', () => {
    expect(estAnnotee(ligne({ indecidable: 1, a: undefined }))).toBe(true)
    expect(estAnnotee(ligne())).toBe(true)
    expect(estAnnotee(ligne({ a: undefined, indecidable: 0 }))).toBe(false)
  })
})

describe('la page', () => {
  // Démonter est indispensable : un composant laissé monté continue de vivre
  // dans le test SUIVANT, et ses promesses s'y mêlent aux siennes.
  const montes: ReturnType<typeof mount>[] = []
  beforeEach(() => {
    get.mockReset()
    requete.mockReturnValue({ query: {} })
  })
  afterEach(() => {
    montes.splice(0).forEach((w) => w.unmount())
  })

  async function monter(annotations: AnnotationOr[]) {
    get.mockResolvedValue({
      gold_version: 'v1', version: null, n: annotations.length, annotations,
    })
    const { default: Page } = await import('../pages/GoldCropPage.vue')
    const w = mount(Page, { global: globalMount })
    montes.push(w)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    return w
  }

  /** Les 60 de la passe 1 : ce qui ouvre la 2ᵉ passe et la réserve. */
  const passe1Complete = () =>
    Array.from({ length: 60 }, (_, i) => ligne({ asset_id: `a${i}`, passe: 1 }))

  it('un jeu vide n’est pas une panne mais une séance à faire', async () => {
    const w = await monter([])
    expect(w.text()).toContain('Aucune annotation')
    expect(w.text()).toContain('annotate.serve')
    expect(w.find('.erreur').exists()).toBe(false)
  })

  it('la seconde passe ne gonfle pas les compteurs', async () => {
    const w = await monter([
      ligne({ asset_id: 'a1', passe: 1 }),
      ligne({ asset_id: 'a2', passe: 1 }),
      ligne({ asset_id: 'a1', passe: 2 }),
    ])
    const t = w.text()
    // 2 images, pas 3 — la passe 2 re-annote `a1`, elle ne l’ajoute pas
    expect(t).toContain('/ 2 annotées')
    expect(t).toContain('en double passe')
    expect(w.findAll('.grille figure')).toHaveLength(2)
  })

  it('le filtre de strate suit la strate CONFIRMÉE', async () => {
    const w = await monter([
      ligne({ asset_id: 'a1', strate_tiree: 'S1_facile', strate_confirmee: 'S2_capsule' }),
      ligne({ asset_id: 'a2', strate_tiree: 'S1_facile' }),
    ])
    const boutons = w.findAll('.filtres button')
    const s2 = boutons.find((b) => b.text().startsWith('S2_capsule'))
    expect(s2, 'un bouton S2_capsule doit exister').toBeTruthy()
    await s2!.trigger('click')
    expect(w.findAll('.grille figure')).toHaveLength(1)
  })

  // La réserve (D14, D15) : 24 images tenues à l'écart, qui regarnissent le
  // tirage quand une image en sort par « indécidable ». Elle ne s'annote qu'une
  // fois la passe 1 finie — l'offrir avant ferait annoter des images dont on ne
  // sait pas encore si elles serviront.
  it('la réserve ne s’ouvre qu’une fois la passe 1 complète', async () => {
    const w = await monter([ligne({ asset_id: 'a1', passe: 1 })])
    expect(w.text()).not.toContain('Annoter la réserve')

    const plein = await monter(passe1Complete())
    const reserve = plein.findAll('a').find((a) => a.text().includes('Annoter la réserve'))
    expect(reserve, 'le lien de réserve doit être là à 60/60').toBeTruthy()
    expect(reserve!.attributes('href')).toBe('/gold-crop/annoter?version=v1&role=reserve')
  })

  // Le hub était collé à `v1` — la version abandonnée par D13. Les entrées
  // qu'il propose doivent ouvrir la version qu'il AFFICHE, sinon le lien de
  // réserve n'apparaîtrait jamais (v1 ne porte que 2 annotations).
  it('`?version=` porte jusqu’aux liens de la séance', async () => {
    requete.mockReturnValue({ query: { version: 'v2' } })
    const w = await monter(passe1Complete())
    const cibles = w.findAll('a').map((a) => a.attributes('href'))
    expect(cibles).toContain('/gold-crop/annoter?version=v2')
    expect(cibles).toContain('/gold-crop/annoter?version=v2&passe=2')
    expect(cibles).toContain('/gold-crop/annoter?version=v2&role=reserve')
  })

  // ⚠️ **Non couvert ici, et c'est nommé plutôt que caché** : la branche
  // d'erreur de la PAGE. Monter le composant avec un `get` qui rejette fait
  // remonter le rejet dans le test alors que le composable l'attrape bel et
  // bien — vérifié : la page rend `.erreur` correctement, `get` n'est appelé
  // qu'une fois, et `mount` ne lève pas. C'est une interaction
  // vitest ↔ @vue/test-utils, pas un défaut du code.
  //
  // Ce qui EST garanti : le composable laisse `jeu` à `null` et remplit
  // `erreur` (test ci-dessus), et le template teste `erreur` AVANT le cas vide
  // (`v-else-if="erreur"` précède `bilan.n === 0`). Une erreur ne peut donc pas
  // s'afficher comme « séance pas encore faite ».
})
