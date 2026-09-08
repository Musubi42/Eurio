// La planche comparative : ce qu'elle refuse d'afficher compte plus que ce
// qu'elle affiche.
//
//   · **RE-7** — deux bras à moins de 5 points d'amputation d'écart ne sont pas
//     départagés. Une planche qui les ordonnerait fabriquerait un vainqueur que
//     60 images ne soutiennent pas, et c'est exactement l'erreur que les sept
//     chantiers crop ont commise avant celui-ci ;
//   · **les bornes ne se classent pas.** `gold_replay` rejoue l'or contre
//     lui-même : le mettre au classement le ferait « gagner » contre des
//     méthodes ;
//   · **un banc qui n'a pas tourné n'est pas une panne** — c'est une commande à
//     lancer, et la page la donne.

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RUNS_DEMO } from '../fixtures'
import {
  type RunBras,
  type RunsBanc,
  classerBras,
  ordonnerBras,
  urlRaw,
} from '../composables/useGoldCropApi'

const get = vi.fn()
vi.mock('@/shared/api/eurio-api', async () => {
  const reel =
    await vi.importActual<typeof import('@/shared/api/eurio-api')>('@/shared/api/eurio-api')
  return { ...reel, eurioApi: { get: (...a: unknown[]) => get(...a) } }
})

let query: Record<string, string> = {}
vi.mock('vue-router', () => ({ useRoute: () => ({ query }) }))

function bras(nom: string, amputation: number | undefined, over: Partial<RunBras> = {}): RunBras {
  return {
    bras: nom, borne: false, juge_version: 1, execute_le: '2026-09-08T08:30:24+00:00',
    params: { m: 0, d_frac: 0.08, arc_min: 11 / 12, region: 'retenu', c2_compte: false },
    resume: amputation == null
      ? { n: 0 }
      : { n: 60, amputation_pct: amputation, amp_C1_pct: amputation, amp_C2_pct: 0,
          marge_promise_ko_pct: amputation, biou_med: 0.8, biou_p10: 0.5,
          iou_masque_med: 0.98, hausdorff_p90: 0.02 },
    re4: null, cas: [],
    ...over,
  }
}

describe('RE-7 — ce que 60 images ne départagent pas', () => {
  it('deux bras à 3 points d’écart ne sont PAS ordonnés', () => {
    const rangs = classerBras([bras('a', 20), bras('b', 23)])
    expect(rangs.map((r) => r.rang)).toEqual([1, 1])
    expect(rangs[0].nonDepartages).toEqual(['b'])
    expect(rangs[1].nonDepartages).toEqual(['a'])
  })

  it('un écart de 5 points ou plus, lui, départage', () => {
    const rangs = classerBras([bras('a', 20), bras('b', 25)])
    expect(rangs.map((r) => r.rang)).toEqual([1, 2])
    expect(rangs.flatMap((r) => r.nonDepartages)).toEqual([])
  })

  it('les bornes sont hors classement, et n’en décalent pas les rangs', () => {
    const rangs = classerBras([
      bras('gold_replay', 0, { borne: true }),
      bras('human_2nd_pass', 2, { borne: true }),
      bras('baseline_prod', 40),
      bras('candidat', 10),
    ])
    const par = Object.fromEntries(rangs.map((r) => [r.run.bras, r.rang]))
    expect(par.gold_replay).toBeNull()
    expect(par.human_2nd_pass).toBeNull()
    // Le plafond est à 0 % : s'il comptait, `candidat` serait 2ᵉ.
    expect(par.candidat).toBe(1)
    expect(par.baseline_prod).toBe(2)
  })

  it('un bras sans cas mesuré ne se classe pas non plus', () => {
    const rangs = classerBras([bras('vide', undefined), bras('plein', 10)])
    expect(rangs.find((r) => r.run.bras === 'vide')!.rang).toBeNull()
  })

  it('le tableau met les bornes en tête, comme la console', () => {
    const ordre = ordonnerBras([
      bras('baseline_prod', 40), bras('gold_replay', 0, { borne: true }),
      bras('human_2nd_pass', 2, { borne: true }),
    ]).map((r) => r.bras)
    expect(ordre).toEqual(['human_2nd_pass', 'gold_replay', 'baseline_prod'])
  })
})

describe('l’URL du raw', () => {
  it('un chemin relatif vise l’API ML, jamais le front', () => {
    const c = { raw_url: '/crop-gold/v1/raws/a1' } as never
    expect(urlRaw(c)).toBe('http://127.0.0.1:8042/crop-gold/v1/raws/a1')
  })
})

describe('la page', () => {
  const montes: ReturnType<typeof mount>[] = []
  beforeEach(() => {
    query = {}
    get.mockReset()
    get.mockResolvedValue({ gold_version: 'v1', version: null, n: 0, annotations: [] })
  })
  afterEach(() => {
    montes.splice(0).forEach((w) => w.unmount())
    vi.unstubAllGlobals()
  })

  async function monter(reponse?: RunsBanc | { statut: number }) {
    if (reponse) {
      const statut = 'statut' in reponse ? reponse.statut : 200
      vi.stubGlobal('fetch', vi.fn(async () => ({
        ok: statut === 200, status: statut, statusText: 'x',
        json: async () => reponse,
      })))
    }
    const { default: Page } = await import('../pages/GoldCropPlanchePage.vue')
    const w = mount(Page, { global: { stubs: { RouterLink: true } } })
    montes.push(w)
    await new Promise((r) => setTimeout(r, 0))
    await w.vm.$nextTick()
    return w
  }

  it('sans run, elle donne la commande au lieu de crier à la panne', async () => {
    const w = await monter({ statut: 404 })
    expect(w.text()).toContain("Le banc n'a pas encore tourné")
    expect(w.text()).toContain('bench.gold_crop.harness')
    expect(w.find('.erreur').exists()).toBe(false)
  })

  it('la démo monte la planche sur les fixtures, sans réseau', async () => {
    query = { demo: '1' }
    const reseau = vi.fn()
    vi.stubGlobal('fetch', reseau)
    const w = await monter()
    expect(reseau).not.toHaveBeenCalled()
    expect(w.findAll('.grille .cas')).toHaveLength(RUNS_DEMO.runs[1].cas.length)
    expect(w.findAll('tbody tr')).toHaveLength(RUNS_DEMO.runs.length)
  })

  it('la borne est marquée et son rang reste vide', async () => {
    query = { demo: '1' }
    const w = await monter()
    const ligneBorne = w.findAll('tbody tr').find((t) => t.text().includes('gold_replay'))!
    expect(ligneBorne.text()).toContain('borne · plafond')
    expect(ligneBorne.find('.rang').text()).toBe('—')
  })

  it('deux bras à égalité sont dits « non départagés »', async () => {
    query = { demo: '1' }
    const w = await monter()
    expect(w.text()).toContain('non départagé avec')
  })

  it('le bloc RE-4 est rendu verbatim, pas reformulé', async () => {
    query = { demo: '1' }
    const w = await monter()
    const re4 = w.find('.re4')
    expect(re4.exists()).toBe(true)
    expect(re4.text()).toContain('impossible')
    expect(re4.text()).toContain('un des deux groupes est vide')
  })

  it('le filtre de strate suit la strate RETENUE', async () => {
    query = { demo: '1' }
    const w = await monter()
    const s2 = w.findAll('.filtres button').find((b) => b.text() === 'S2_capsule')
    expect(s2, 'un bouton S2_capsule doit exister').toBeTruthy()
    await s2!.trigger('click')
    expect(w.findAll('.grille .cas')).toHaveLength(1)
    expect(w.find('.grille .cas').text()).toContain('S2_capsule')
  })

  it('« seulement les amputés » ne garde que ce que le juge a recalé', async () => {
    query = { demo: '1' }
    const w = await monter()
    const cases = w.findAll('.filtres input[type="checkbox"]')
    await cases[0].setValue(true)
    const cas = w.findAll('.grille .cas')
    expect(cas).toHaveLength(1)
    expect(cas[0].text()).toContain('amputé')
  })

  it('un clic sur un cas superpose TOUS les bras, avec leur légende', async () => {
    query = { demo: '1' }
    const w = await monter()
    await w.find('.grille .cas').trigger('click')
    const legende = w.find('.loupe .legende')
    expect(legende.exists()).toBe(true)
    // l'or + un poste par bras
    expect(legende.findAll('li')).toHaveLength(RUNS_DEMO.runs.length + 1)
    expect(w.findAll('.loupe circle')).toHaveLength(RUNS_DEMO.runs.length)
  })
})
