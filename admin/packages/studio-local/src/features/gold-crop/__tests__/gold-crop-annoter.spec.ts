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

  it('tout tracé : on rouvre la première image TRACÉE sans familles (D16)', () => {
    const [a1, a2, a3] = TIRAGE_DEMO.images.map((im) => im.asset_id)
    const base = JEU_DEMO.annotations[0]
    const i = premiereAFaire(TIRAGE_DEMO.images, etats([
      { ...base, asset_id: a1, familles: [] },
      // un indécidable sort du jeu : l'étiqueter ne servirait à rien
      { ...base, asset_id: a2, indecidable: 1, familles: null },
      { ...base, asset_id: a3, familles: null },
    ]))
    expect(i).toBe(2)
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

  // Vécu le 2026-09-11 : `?version=v2.` (un point de trop) rend un tirage vide,
  // et la page réclamait `publier_tirage` — que le PO a lancé depuis la racine
  // du dépôt, où il échoue. Le canonique ne distingue pas une version mal tapée
  // d'une version neuve : la page doit NOMMER la version et dire OÙ lancer.
  it('sans tirage sous cette version, elle la nomme et dit où lancer — ce n’est pas une panne', async () => {
    requete.mockReturnValue({ query: { version: 'v2.' } })
    servir([], [])
    const w = await monter()
    expect(w.text()).toContain('Aucun tirage sous la version « v2. »')
    expect(w.text()).toContain(
      'cd ml && python -m bench.gold_crop.publier_tirage --out state/gold_crop/v2.',
    )
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

  // Les trois tests qui suivent verrouillent la panne du 2026-09-09 : menu
  // replié après le chargement → viewBox en retard sur la taille réelle du SVG
  // → bandes en haut et en bas, et 3 px de souris faisaient 63 px de demi-axe.
  const pointeurNatif = (type: string, x: number, y: number) =>
    new MouseEvent(type, { clientX: x, clientY: y, bubbles: true })

  it('la scène change de taille sans que la fenêtre bouge : le viewBox suit, le contenu reste centré', async () => {
    const rappels: Array<() => void> = []
    class Observateur {
      constructor(cb: () => void) {
        rappels.push(cb)
      }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', Observateur)
    try {
      servir(TIRAGE_DEMO.images, [])
      const w = await monter()
      const scene = w.find('.scene').element as HTMLElement
      // jsdom ne mesure rien : sans observateur, le viewBox garde sa valeur de repli
      expect(w.find('svg.toile').attributes('viewBox')).toBe('0 0 900 700')
      const avant = Number(w.find('ellipse').attributes('cy'))
      Object.defineProperty(scene, 'clientWidth', { value: 890, configurable: true })
      Object.defineProperty(scene, 'clientHeight', { value: 844, configurable: true })
      rappels.forEach((cb) => cb())
      await w.vm.$nextTick()
      expect(w.find('svg.toile').attributes('viewBox')).toBe('0 0 890 844')
      // 144 px de plus en hauteur : le centre descend de 72, il ne reste pas collé en haut
      expect(Number(w.find('ellipse').attributes('cy')) - avant).toBeCloseTo(72, 6)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('le pointeur est projeté par la matrice réelle du SVG, pas par « 1 px = 1 unité »', async () => {
    servir(TIRAGE_DEMO.images, [])
    const w = await monter()
    const toile = w.find('svg.toile').element as unknown as { getScreenCTM: () => unknown } & Element
    // le SVG est rendu à moitié de son viewBox (le menu vient de s'ouvrir)
    toile.getScreenCTM = () => ({ a: 0.5, b: 0, c: 0, d: 0.5, e: 0, f: 0 })
    const centre = w.find('[data-poignee="C"]')
    const avant = Number(w.find('ellipse').attributes('cx'))
    const x = Number(centre.attributes('cx')) * 0.5
    const y = Number(centre.attributes('cy')) * 0.5
    centre.element.dispatchEvent(pointeurNatif('pointerdown', x, y))
    toile.dispatchEvent(pointeurNatif('pointermove', x + 10, y))
    toile.dispatchEvent(pointeurNatif('pointerup', x + 10, y))
    await w.vm.$nextTick()
    // 10 px client à l'échelle ½ = 20 unités du viewBox — pas 10
    expect(Number(w.find('ellipse').attributes('cx')) - avant).toBeCloseTo(20, 6)
  })

  it('saisir une poignée à côté de son centre ne fait pas sauter l’ellipse', async () => {
    servir(TIRAGE_DEMO.images, [])
    const w = await monter()
    const toile = w.find('svg.toile').element
    const bordE = w.find('[data-poignee="E"]')
    const rxAvant = Number(w.find('ellipse').attributes('rx'))
    // la cible du doigt fait 14 px de rayon : on la tient par son bord, à 12 px
    // du centre — l'ellipse ne doit pas sauter de cet écart
    const x = Number(bordE.attributes('cx')) + 12
    const y = Number(bordE.attributes('cy'))
    bordE.element.dispatchEvent(pointeurNatif('pointerdown', x, y))
    toile.dispatchEvent(pointeurNatif('pointermove', x, y))
    toile.dispatchEvent(pointeurNatif('pointerup', x, y))
    await w.vm.$nextTick()
    expect(Number(w.find('ellipse').attributes('rx'))).toBeCloseTo(rxAvant, 6)
  })

  /* ── le geste refondu du 2026-09-09 : on tire un BORD ─────────────────── */
  //
  // `a1` part du pré-remplissage cx=452 cy=448 a=372 b=361 θ=12. L'échelle `k`
  // ne se devine pas en jsdom : on la relit sur le tracé (`rx = a·k`).
  const T12 = (12 * Math.PI) / 180
  const U: [number, number] = [Math.cos(T12), Math.sin(T12)] // le long du grand axe
  const SORTANTE_N: [number, number] = [Math.sin(T12), -Math.cos(T12)] // vers le haut

  const echelle = (w: ReturnType<typeof mount>) =>
    Number(w.find('ellipse').attributes('rx')) / 372

  function tirer(
    w: ReturnType<typeof mount>,
    id: string,
    dir: [number, number],
    dEcran: number,
  ) {
    const toile = w.find('svg.toile').element
    const p = w.find(`[data-poignee="${id}"]`)
    const x = Number(p.attributes('cx'))
    const y = Number(p.attributes('cy'))
    p.element.dispatchEvent(pointeurNatif('pointerdown', x, y))
    toile.dispatchEvent(pointeurNatif('pointermove', x + dir[0] * dEcran, y + dir[1] * dEcran))
    toile.dispatchEvent(pointeurNatif('pointerup', x + dir[0] * dEcran, y + dir[1] * dEcran))
  }

  it('tirer le bord E cloue le bord W et ne déplace le centre que de la moitié', async () => {
    servir(TIRAGE_DEMO.images, [])
    const w = await monter()
    const W = w.find('[data-poignee="W"]')
    const wx = Number(W.attributes('cx'))
    const wy = Number(W.attributes('cy'))
    const cxAvant = Number(w.find('ellipse').attributes('cx'))
    const cyAvant = Number(w.find('ellipse').attributes('cy'))
    const rxAvant = Number(w.find('ellipse').attributes('rx'))

    tirer(w, 'E', U, 40)
    await w.vm.$nextTick()

    // le bord d'en face n'a pas bougé d'un pixel — c'est TOUT le geste
    expect(Number(w.find('[data-poignee="W"]').attributes('cx'))).toBeCloseTo(wx, 6)
    expect(Number(w.find('[data-poignee="W"]').attributes('cy'))).toBeCloseTo(wy, 6)
    // …donc le demi-axe et le centre prennent chacun la moitié des 40 px
    expect(Number(w.find('ellipse').attributes('rx')) - rxAvant).toBeCloseTo(20, 6)
    expect(Number(w.find('ellipse').attributes('cx')) - cxAvant).toBeCloseTo(20 * U[0], 6)
    expect(Number(w.find('ellipse').attributes('cy')) - cyAvant).toBeCloseTo(20 * U[1], 6)
  })

  it('tirer N au-delà de a est permis : c’est la VALIDATION qui échange les axes', async () => {
    servir(TIRAGE_DEMO.images, [])
    put.mockResolvedValue({ n: 1 })
    const w = await monter()
    // 100 px image vers le haut : b passe de 361 à 411, donc au-dessus de a=372.
    // Rien ne doit brider le glisser — sinon le bord décroche du pointeur.
    tirer(w, 'N', SORTANTE_N, 100 * echelle(w))
    await w.vm.$nextTick()
    expect(w.find('.incrust.gauche').text()).toContain('b=411.0')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    await dodo()
    const a = (put.mock.calls[0][1] as { annotations: Record<string, unknown>[] }).annotations[0]
    const e = a.ellipse as { a: number; b: number; theta: number }
    expect(e.a).toBeCloseTo(411, 6)
    expect(e.b).toBeCloseTo(372, 6)
    expect(e.a).toBeGreaterThanOrEqual(e.b)
    expect(e.theta).toBeCloseTo(102, 6) // 12 + 90 : θ reste l'angle du GRAND axe
  })

  it('la loupe est une surface d’édition : 8 px de souris = 2 px image', async () => {
    servir(TIRAGE_DEMO.images, [])
    const w = await monter()
    const S = w.find('[data-poignee="S"]')
    const sx = Number(S.attributes('cx'))
    const sy = Number(S.attributes('cy'))
    const loupe = w.find('[data-loupe="haut"]')
    loupe.element.dispatchEvent(pointeurNatif('pointerdown', 0, 0))
    loupe.element.dispatchEvent(
      pointeurNatif('pointermove', 8 * SORTANTE_N[0], 8 * SORTANTE_N[1]),
    )
    loupe.element.dispatchEvent(pointeurNatif('pointerup', 8 * SORTANTE_N[0], 8 * SORTANTE_N[1]))
    await w.vm.$nextTick()
    // ×4 : le bord monte de 2 px image, donc b prend 1 et le centre l'autre
    expect(w.find('.incrust.gauche').text()).toContain('b=362.0')
    expect(w.find('.incrust.gauche').text()).toContain('a=372.0')
    // le bord opposé reste cloué, comme dans la scène
    expect(Number(w.find('[data-poignee="S"]').attributes('cx'))).toBeCloseTo(sx, 6)
    expect(Number(w.find('[data-poignee="S"]').attributes('cy'))).toBeCloseTo(sy, 6)
  })

  it('une loupe choisie confisque les flèches ; Échap les rend à la navigation', async () => {
    servir(TIRAGE_DEMO.images, [])
    put.mockResolvedValue({ n: 1 })
    const w = await monter()
    const k = echelle(w)
    const ry = () => Number(w.find('ellipse').attributes('ry'))

    w.find('[data-loupe="haut"]').element.dispatchEvent(pointeurNatif('pointerdown', 0, 0))
    await w.vm.$nextTick()
    expect(w.find('.loupes figure').classes()).toContain('actif')

    const avant = ry()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp' }))
    await w.vm.$nextTick()
    // 0,5 px de bord = 0,25 px de demi-axe (l'opposé ne bouge pas)
    expect((ry() - avant) / k).toBeCloseTo(0.25, 6)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', shiftKey: true }))
    await w.vm.$nextTick()
    expect((ry() - avant) / k).toBeCloseTo(1.25, 6) // 0,25 + 2/2
    // et surtout : on n'a PAS changé d'image
    expect(w.text()).toContain('a1')

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await w.vm.$nextTick()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await dodo()
    expect(w.text()).toContain('a2')
  })

  it('la molette sur une loupe pousse le bord DEHORS, et ne fait pas défiler la page', async () => {
    servir(TIRAGE_DEMO.images, [])
    const w = await monter()
    const k = echelle(w)
    const ry = () => Number(w.find('ellipse').attributes('ry'))
    const avant = ry()
    const loupe = w.find('[data-loupe="haut"]').element

    // vers le haut = vers l'extérieur. Le sens n'est pas indifférent : une
    // sortante retournée ferait rentrer le bord quand on croit l'élargir.
    const dehors = new WheelEvent('wheel', { deltaY: -100, bubbles: true, cancelable: true })
    loupe.dispatchEvent(dehors)
    await w.vm.$nextTick()
    expect((ry() - avant) / k).toBeCloseTo(0.125, 6) // 0,25 px de bord
    expect(dehors.defaultPrevented).toBe(true) // sinon la page défile sous la loupe

    loupe.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, bubbles: true, cancelable: true }))
    await w.vm.$nextTick()
    expect((ry() - avant) / k).toBeCloseTo(0, 6)
  })

  it('les loupes ne sont PAS dans la scène — elles masquaient la pièce', async () => {
    servir(TIRAGE_DEMO.images, [])
    const w = await monter()
    expect(w.find('.loupes').exists()).toBe(true)
    expect(w.find('.scene').findAll('.loupes')).toHaveLength(0)
    expect(w.find('.colonne > .loupes').exists()).toBe(true)
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

  it('poser des familles seules n’écrit rien — mais l’image reste à faire', async () => {
    servir(TIRAGE_DEMO.images, [])
    put.mockResolvedValue({ n: 0 })
    const w = await monter()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '3' }))
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

/* ════════════════════════════════════════════════════════════════════════ */

// La réserve (D14, D15). Le tirage porte DEUX lots dans la même table :
// 60 images `role='tirage'` et 24 `role='reserve'`, qui regarnissent le tirage
// quand une image en sort par « indécidable » — 16 des 28 rejets de v2.
//
// La page servait le lot `tirage` en dur, à deux endroits : l'appel réseau
// (`?role=`) ET le filtre client. Les deux devaient bouger ensemble — ne
// corriger que l'appel aurait rendu une liste VIDE, sans erreur ni message,
// exactement la panne muette que le projet paie le plus cher.
describe('la page d’annotation, sur la réserve', () => {
  const montes: ReturnType<typeof mount>[] = []
  const dodo = (ms = 0) => new Promise((r) => setTimeout(r, ms))

  beforeEach(() => {
    get.mockReset()
    put.mockReset()
    requete.mockReturnValue({ query: {} })
  })
  afterEach(() => {
    montes.splice(0).forEach((w) => w.unmount())
  })

  /** Un tirage mixte : ce que rend vraiment `GET /crop-gold/{v}/tirage`. */
  const mixte = (): ImageTirage[] => [
    { ...TIRAGE_DEMO.images[0], asset_id: 't1', role: 'tirage' },
    { ...TIRAGE_DEMO.images[1], asset_id: 't2', role: 'tirage' },
    { ...TIRAGE_DEMO.images[0], asset_id: 'r1', role: 'reserve' },
    { ...TIRAGE_DEMO.images[2], asset_id: 'r2', role: 'reserve' },
  ]

  function servir(annotations: AnnotationOr[] = []) {
    get.mockImplementation(async (chemin: string) => {
      if (chemin.includes('/tirage')) {
        const images = mixte()
        return { gold_version: 'v2', n: images.length, images }
      }
      return { gold_version: 'v2', version: null, n: annotations.length, annotations }
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

  it('`?role=reserve` demande la réserve au canonique ET filtre dessus', async () => {
    requete.mockReturnValue({ query: { version: 'v2', role: 'reserve' } })
    servir()
    const w = await monter()

    const chemins = get.mock.calls.map((c) => String(c[0]))
    expect(chemins).toContain('/crop-gold/v2/tirage?role=reserve')
    // le filtre client a suivi : « n / N » compte le lot SERVI, pas les 60
    expect(w.text()).toContain('2 images')
    expect(w.text()).toContain('1 / 2')
    // le bandeau le DIT : annoter la réserve en croyant faire le tirage est
    // une confusion qu'aucun message ne rattraperait ensuite
    expect(w.find('.soustitre').text()).toContain('réserve')
    expect(w.text()).toContain('r1')
    expect(w.text()).not.toContain('t1')
  })

  it('sans `?role=`, rien ne change : c’est le tirage', async () => {
    requete.mockReturnValue({ query: { version: 'v2' } })
    servir()
    const w = await monter()

    expect(get.mock.calls.map((c) => String(c[0]))).toContain('/crop-gold/v2/tirage?role=tirage')
    expect(w.text()).toContain('t1')
    expect(w.text()).not.toContain('r1')
    expect(w.find('.soustitre').text()).not.toContain('réserve')
  })

  it('la reprise « première sans ellipse » se fait DANS la réserve', async () => {
    requete.mockReturnValue({ query: { version: 'v2', role: 'reserve' } })
    // `r1` est annotée ; `t1`/`t2` du tirage aussi, et elles ne doivent pas
    // décaler le rang — la reprise se calcule sur le lot servi.
    servir([
      { ...JEU_DEMO.annotations[0], asset_id: 't1', passe: 1 },
      { ...JEU_DEMO.annotations[0], asset_id: 'r1', passe: 1 },
    ])
    const w = await monter()
    expect(w.text()).toContain('2 / 2')
    expect(w.text()).toContain('r2')
  })
})

/* ════════════════════════════════════════════════════════════════════════ */

// La navigation n'écrit que ce qu'on a MODIFIÉ (D16). Avant le 2026-09-11, ← →
// validaient en passant : les 16 indécidables de v2 portent le pré-remplissage
// comme ellipse, et `7a072305` / `986ada7d` ont été réécrites en les revoyant.
// Sur une image pas encore tracée, → aurait fait entrer `measure_tilt` dans l'or.
describe('la navigation n’écrit que ce qu’on a modifié', () => {
  const montes: ReturnType<typeof mount>[] = []
  const dodo = (ms = 200) => new Promise((r) => setTimeout(r, ms))
  const touche = (key: string) => window.dispatchEvent(new KeyboardEvent('keydown', { key }))

  beforeEach(() => {
    get.mockReset()
    put.mockReset()
    put.mockResolvedValue({ n: 1 })
    requete.mockReturnValue({ query: {} })
  })
  afterEach(() => {
    montes.splice(0).forEach((w) => w.unmount())
  })

  function servir(annotations: AnnotationOr[]) {
    get.mockImplementation(async (chemin: string) =>
      chemin.includes('/tirage')
        ? { gold_version: 'v1', n: 3, images: TIRAGE_DEMO.images }
        : { gold_version: 'v1', version: null, n: annotations.length, annotations },
    )
  }

  async function monter() {
    const { default: Page } = await import('../pages/GoldCropAnnotatePage.vue')
    const w = mount(Page)
    montes.push(w)
    await dodo(0)
    await w.vm.$nextTick()
    return w
  }

  const tracee = (asset_id: string, over: Partial<AnnotationOr> = {}) =>
    ({ ...JEU_DEMO.annotations[0], asset_id, ...over }) as AnnotationOr
  const indecidable = (asset_id: string) =>
    tracee(asset_id, { indecidable: 1, cx: undefined, cy: undefined, a: undefined, b: undefined })

  it('→ sur une image pas encore tracée ne l’écrit pas', async () => {
    servir([])
    const w = await monter()
    expect(w.text()).toContain('1 / 3')
    touche('ArrowRight')
    await dodo()
    expect(put).not.toHaveBeenCalled()
    await w.vm.$nextTick()
    expect(w.text()).toContain('2 / 3')
  })

  it('revoir un indécidable et une image tracée, aux flèches ET à Entrée, n’écrit rien', async () => {
    servir([tracee('a1'), indecidable('a2'), tracee('a3')])
    const w = await monter()
    expect(w.text()).toContain('1 / 3')
    touche('ArrowRight') // a2, indécidable
    touche('ArrowRight') // a3
    touche('ArrowLeft') // a2
    touche('Enter') // a2 est faite et intacte : on passe, on ne réécrit pas
    touche('ArrowLeft')
    touche('ArrowLeft') // a1
    touche('Enter')
    await dodo()
    expect(put).not.toHaveBeenCalled()
  })

  it('une ellipse BOUGÉE s’écrit en quittant par la flèche', async () => {
    servir([])
    const w = await monter()
    const pointeur = (type: string, x: number, y: number) =>
      new MouseEvent(type, { clientX: x, clientY: y, bubbles: true })
    const toile = w.find('svg.toile').element
    w.find('[data-poignee="C"]').element.dispatchEvent(pointeur('pointerdown', 5, 5))
    toile.dispatchEvent(pointeur('pointermove', 140, 160))
    toile.dispatchEvent(pointeur('pointerup', 140, 160))
    await w.vm.$nextTick()
    touche('ArrowRight')
    await dodo()
    expect(put).toHaveBeenCalledTimes(1)
    const a = (put.mock.calls[0][1] as { annotations: Record<string, unknown>[] }).annotations[0]
    expect(a.asset_id).toBe('a1')
    expect(a.prefill_modifie).toBe(true)
  })

  it('les familles se cumulent, 1 remet à facile, et chaque geste s’écrit sur une image tracée', async () => {
    servir([tracee('a1'), tracee('a2'), tracee('a3')])
    const w = await monter()
    const dernier = () =>
      (put.mock.calls.at(-1)![1] as { annotations: Record<string, unknown>[] }).annotations[0]

    touche('2')
    await dodo()
    expect(dernier().familles).toEqual(['capsule'])
    touche('3')
    await dodo()
    expect(dernier().familles).toEqual(['capsule', 'multi'])
    touche('2')
    await dodo()
    expect(dernier().familles).toEqual(['multi'])
    touche('1')
    await dodo()
    expect(dernier().familles).toEqual([])
    // le ré-étiquetage ne retouche PAS l'ellipse tracée
    expect(dernier().ellipse).toEqual({ cx: 450, cy: 450, a: 370, b: 360, theta: 12 })
    await w.vm.$nextTick()
    expect(w.find('.strate.actif').text()).toContain('facile')
  })
})
