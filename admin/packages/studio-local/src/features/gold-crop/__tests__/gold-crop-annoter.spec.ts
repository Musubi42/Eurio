// La séance d'annotation dans le front — ce qui doit rester vrai du portage.
//
// Chacun de ces tests garde un comportement PAYÉ dans l'outil local, et qu'un
// portage « en gros » perdrait sans bruit :
//
//   · la reprise se fait sur « annotée », pas sur « touchée » — confirmer une
//     strate crée une entrée, et reprendre après elle saute une image en
//     silence (vécu le 2026-08-28) ;
//   · le sous-ensemble de la 2ᵉ passe se tire du MÊME hachage que `serve.py`,
//     sinon les deux instruments ne mesurent pas la même reproductibilité ;
//   · le corps du PUT porte `theta` (et non `theta_deg`) et
//     `editor_version: 'gold_web_v1'` — une ellipse sans angle est fausse sans
//     que rien ne l'affiche comme fausse, et deux instruments confondus font
//     lire une divergence de tracé comme du bruit d'annotateur ;
//   · un échec d'écriture se DIT. C'est la seule panne qui coûte la séance.

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AnnotationOr, EtatAnnotation, ImageTirage } from '../composables/useGoldCropApi'
import {
  EDITEUR_WEB,
  ellipseDepuisPrefill,
  etatDepuisAnnotation,
  normaliserEllipse,
  premiereAFaire,
} from '../composables/useGoldCropApi'
import { sha256Hex, sousEnsemblePasse2 } from '../composables/sha256'
import { JEU_DEMO, TIRAGE_DEMO } from '../fixtures'

const get = vi.fn()
const put = vi.fn()
vi.mock('@/shared/api/eurio-api', async () => {
  const reel =
    await vi.importActual<typeof import('@/shared/api/eurio-api')>('@/shared/api/eurio-api')
  return {
    ...reel,
    eurioApi: {
      get: (...a: unknown[]) => get(...a),
      put: (...a: unknown[]) => put(...a),
    },
  }
})

const requete = vi.fn(() => ({ query: {} as Record<string, string> }))
vi.mock('vue-router', () => ({ useRoute: () => requete() }))

/* ════════════════════════════════════════════════════════════════════════ */

describe('SHA-256 et le sous-ensemble de la 2ᵉ passe', () => {
  it('rend les vecteurs de référence', () => {
    expect(sha256Hex('')).toBe(
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    )
    expect(sha256Hex('abc')).toBe(
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    )
    // > 55 octets : force un second bloc de compression
    expect(sha256Hex('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')).toBe(
      '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1',
    )
  })

  it('garde les n premiers par ordre d’empreinte, comme `serve.py`', () => {
    const ids = ['a', 'b', 'c', 'd', 'e']
    // ordre attendu, calculé à part : sha256("a")=ca978112…, "b"=3e23e816…,
    // "c"=2e7d2c03…, "d"=18ac3e73…, "e"=3f79bb7b…
    const attendu = [...ids].sort((x, y) => (sha256Hex(x) < sha256Hex(y) ? -1 : 1))
    expect(attendu).toEqual(['d', 'c', 'b', 'e', 'a'])
    expect(sousEnsemblePasse2(ids, 3)).toEqual(['d', 'c', 'b'])
    // l'ordre d'arrivée n'entre pas dans le tirage : il est déterministe
    expect(sousEnsemblePasse2(['e', 'c', 'a', 'd', 'b'], 3)).toEqual(['d', 'c', 'b'])
  })
})

describe('les grandeurs de l’ellipse', () => {
  it('a ≥ b : on échange les axes et on ajoute 90°', () => {
    const n = normaliserEllipse({ cx: 10, cy: 20, a: 30, b: 50, theta: 10 })
    expect(n.a).toBe(50)
    expect(n.b).toBe(30)
    expect(n.theta).toBe(100)
  })

  it('ramène θ dans [0, 180) — une ellipse est invariante par demi-tour', () => {
    expect(normaliserEllipse({ cx: 0, cy: 0, a: 5, b: 4, theta: -170 }).theta).toBe(10)
    expect(normaliserEllipse({ cx: 0, cy: 0, a: 5, b: 4, theta: 190 }).theta).toBe(10)
    // …et une ellipse déjà bien formée n'est pas touchée
    expect(normaliserEllipse({ cx: 1, cy: 2, a: 5, b: 4, theta: 33 })).toEqual({
      cx: 1, cy: 2, a: 5, b: 4, theta: 33,
    })
  })

  it('sans pré-remplissage, le départ est le cercle de l’indice', () => {
    const sans = TIRAGE_DEMO.images.find((i) => i.asset_id === 'a2')!
    expect(ellipseDepuisPrefill(sans)).toEqual({ cx: 450, cy: 450, a: 380, b: 380, theta: 0 })
    const avec = TIRAGE_DEMO.images.find((i) => i.asset_id === 'a1')!
    expect(ellipseDepuisPrefill(avec)).toEqual({ cx: 452, cy: 448, a: 372, b: 361, theta: 12 })
  })
})

describe('la reprise', () => {
  const etats = (a: AnnotationOr[]): Record<string, EtatAnnotation> =>
    Object.fromEntries(a.map((x) => [x.asset_id, etatDepuisAnnotation(x)]))

  it('rouvre la première image sans ellipse ET sans indécidable', () => {
    // `a1` est tracée, `a2` porte une strate confirmée mais RIEN d'autre :
    // c'est `a2` qu'il faut rouvrir, pas `a3`.
    const i = premiereAFaire(TIRAGE_DEMO.images, etats(JEU_DEMO.annotations))
    expect(TIRAGE_DEMO.images[i].asset_id).toBe('a2')
  })

  it('un indécidable compte comme faite — c’est une décision', () => {
    const avec = JEU_DEMO.annotations.map((a) =>
      a.asset_id === 'a2' ? ({ ...a, indecidable: 1 } as AnnotationOr) : a,
    )
    const i = premiereAFaire(TIRAGE_DEMO.images, etats(avec))
    expect(TIRAGE_DEMO.images[i].asset_id).toBe('a3')
  })

  it('tout fait : on rouvre la première, on ne sort pas du tableau', () => {
    const tout = TIRAGE_DEMO.images.map(
      (im) => ({ ...JEU_DEMO.annotations[0], asset_id: im.asset_id }) as AnnotationOr,
    )
    expect(premiereAFaire(TIRAGE_DEMO.images, etats(tout))).toBe(0)
  })
})

/* ════════════════════════════════════════════════════════════════════════ */

describe('la page d’annotation', () => {
  const montes: ReturnType<typeof mount>[] = []
  const dodo = (ms = 200) => new Promise((r) => setTimeout(r, ms))

  beforeEach(() => {
    get.mockReset()
    put.mockReset()
    requete.mockReturnValue({ query: {} })
  })
  afterEach(() => {
    montes.splice(0).forEach((w) => w.unmount())
  })

  function servir(images: ImageTirage[], annotations: AnnotationOr[], jeu = {}) {
    get.mockImplementation(async (chemin: string) => {
      if (chemin.includes('/tirage')) {
        return { gold_version: 'v1', n: images.length, images }
      }
      return { gold_version: 'v1', version: null, n: annotations.length, annotations, ...jeu }
    })
  }

  async function monter() {
    const { default: Page } = await import('../pages/GoldCropAnnotatePage.vue')
    const w = mount(Page)
    montes.push(w)
    await dodo(0)
    await w.vm.$nextTick()
    return w
  }

  it('sans tirage publié, elle dit quoi lancer — ce n’est pas une panne', async () => {
    servir([], [])
    const w = await monter()
    expect(w.text()).toContain("Le tirage n'est pas encore publié")
    expect(w.text()).toContain('publier_tirage')
  })

  it('le PUT porte `theta`, `editor_version` et pas de `prefill_modifie` inventé', async () => {
    servir(TIRAGE_DEMO.images, [])
    put.mockResolvedValue({ n: 1 })
    const w = await monter()
    // rien n'a été touché : Entrée valide l'ellipse telle que proposée
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await dodo()

    expect(put).toHaveBeenCalledTimes(1)
    const [chemin, corps] = put.mock.calls[0] as [string, { annotations: unknown[] }]
    expect(chemin).toBe('/crop-gold/v1/annotations')
    const a = corps.annotations[0] as Record<string, unknown>
    expect(a.asset_id).toBe('a1')
    expect(a.editor_version).toBe(EDITEUR_WEB)
    expect(a.editor_version).toBe('gold_web_v1')
    expect(a.passe).toBe(1)
    expect(a.indecidable).toBe(false)
    expect(a.strate_tiree).toBe('S1_facile')
    // le champ s'appelle `theta` à l'ENVOI, `theta_deg` en lecture
    expect(a.ellipse).toEqual({ cx: 452, cy: 448, a: 372, b: 361, theta: 12 })
    expect(a.prefill_modifie).toBe(false)
    await w.vm.$nextTick()
    expect(w.find('.ecrit').classes()).toContain('ok')
    expect(w.find('.ecrit').text()).toContain('canonique · 1')
  })

  it('une ellipse déplacée se déclare modifiée', async () => {
    servir(TIRAGE_DEMO.images, [])
    put.mockResolvedValue({ n: 1 })
    const w = await monter()
    // on saisit la poignée elle-même : l'évènement remonte au SVG, et c'est
    // `event.target.dataset.poignee` qui dit laquelle est tenue
    // évènements natifs, pas `trigger` : jsdom n'a pas `PointerEvent`, et VTU
    // essaie alors d'écrire `clientX` sur un `MouseEvent` en lecture seule
    const pointeur = (type: string, x: number, y: number) =>
      new MouseEvent(type, { clientX: x, clientY: y, bubbles: true })
    const toile = w.find('svg.toile').element
    w.find('[data-poignee="C"]').element.dispatchEvent(pointeur('pointerdown', 5, 5))
    toile.dispatchEvent(pointeur('pointermove', 140, 160))
    toile.dispatchEvent(pointeur('pointerup', 140, 160))
    await w.vm.$nextTick()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await dodo()
    const a = (put.mock.calls[0][1] as { annotations: Record<string, unknown>[] }).annotations[0]
    expect(a.prefill_modifie).toBe(true)
  })

  it('un PUT refusé passe la ligne « écrit » au rouge, avec la raison', async () => {
    const { EurioApiError } = await import('@/shared/api/eurio-api')
    servir(TIRAGE_DEMO.images, [])
    put.mockRejectedValue(new EurioApiError(409, { detail: 'frozen' }, 'PUT: 409 frozen'))
    const w = await monter()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await dodo()
    await w.vm.$nextTick()
    const ligne = w.find('.ecrit')
    expect(ligne.classes()).toContain('ko')
    // jamais un code nu : la conduite à tenir est dans la phrase
    expect(ligne.text()).toContain('GELÉE')
    expect(ligne.text()).not.toBe('409')
  })

  it('confirmer une strate seule n’écrit rien — mais l’image reste à faire', async () => {
    servir(TIRAGE_DEMO.images, [])
    put.mockResolvedValue({ n: 0 })
    const w = await monter()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '2' }))
    await dodo()
    expect(put).not.toHaveBeenCalled()
    expect(w.text()).toContain('à faire')
  })

  it('une version gelée n’accepte plus une écriture, et le dit', async () => {
    servir(TIRAGE_DEMO.images, [], {
      version: { gold_version: 'v1', created_at: '', requete_sha256: null,
                 frozen_at: '2026-09-01T08:00:00Z', snapshot_sha256: 'ab',
                 snapshot_key: 'k', note: null },
    })
    const w = await monter()
    expect(w.text()).toContain('Version gelée le 2026-09-01')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await dodo()
    expect(put).not.toHaveBeenCalled()
  })

  it('la 2ᵉ passe ne présente que le sous-ensemble haché, pré-rempli comme au départ', async () => {
    requete.mockReturnValue({ query: { passe: '2' } })
    const p1: AnnotationOr[] = TIRAGE_DEMO.images.map(
      (im) => ({ ...JEU_DEMO.annotations[0], asset_id: im.asset_id, passe: 1 }) as AnnotationOr,
    )
    get.mockImplementation(async (chemin: string) => {
      if (chemin.includes('/tirage')) {
        return { gold_version: 'v1', n: 3, images: TIRAGE_DEMO.images }
      }
      // le même corps pour les deux passes : on simule un canonique qui rend
      // TOUT, pour vérifier que la page ne laisse pas la passe 1 déteindre sur
      // la 2 — c'est ce filtre qui protège la mesure
      return { gold_version: 'v1', version: null, n: 3, annotations: p1 }
    })
    put.mockResolvedValue({ n: 1 })
    const w = await monter()
    // `sousEnsemblePasse2(['a1','a2','a3'], 10)` garde les trois, mais dans
    // l'ordre du tirage — ce qui compte est qu'elles soient bien filtrées par
    // le hachage et pas par l'ordre d'arrivée.
    expect(sousEnsemblePasse2(['a1', 'a2', 'a3'], 2)).toEqual(['a2', 'a3'])
    expect(w.text()).toContain('passe 2')

    // …et surtout : le tracé de la passe 1 n'est PAS montré. Le départ reste le
    // pré-remplissage, sinon on mesure la mémoire et non la main.
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await dodo()
    const a = (put.mock.calls[0][1] as { annotations: Record<string, unknown>[] }).annotations[0]
    expect(a.passe).toBe(2)
    expect(a.ellipse).toEqual({ cx: 452, cy: 448, a: 372, b: 361, theta: 12 })
  })

  it('les quatre loupes cadrent les points cardinaux du contour', async () => {
    servir(TIRAGE_DEMO.images, [])
    const w = await monter()
    const figures = w.findAll('.loupes figure')
    expect(figures).toHaveLength(4)
    expect(figures.map((f) => f.text())).toEqual(['haut', 'droite', 'bas', 'gauche'])
  })
})
