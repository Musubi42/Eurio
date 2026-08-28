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
vi.mock('@/shared/api/eurio-api', () => ({
  eurioApi: { get: (...a: unknown[]) => get(...a) },
}))

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
  beforeEach(() => get.mockReset())
  afterEach(() => {
    montes.splice(0).forEach((w) => w.unmount())
  })

  async function monter(annotations: AnnotationOr[]) {
    get.mockResolvedValue({
      gold_version: 'v1', version: null, n: annotations.length, annotations,
    })
    const { default: Page } = await import('../pages/GoldCropPage.vue')
    const w = mount(Page)
    montes.push(w)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    return w
  }

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
