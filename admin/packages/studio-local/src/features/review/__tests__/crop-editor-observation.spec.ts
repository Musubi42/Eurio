// Défaut : le recadrage manuel ne laissait AUCUNE trace de ce qu'il corrigeait.
//
// Sept chantiers « crop » entre mai et août 2026 ont chacun atteint leur cible
// sur leur PROPRE oracle et produit des crops que l'humain jette. Le dépôt n'a
// aucune vérité terrain sur le cadrage : `crop_edit.py` écrase la géométrie
// proposée EN PLACE, et le payload ne portait que `{cx, cy, r}` — alors que
// l'éditeur connaît l'avant, la suggestion Hough et le fait que l'humain ait
// bougé ou non. Les trois mouraient à la fermeture de la modale.
//
// Ce que ce fichier verrouille, et pourquoi chaque point a coûté quelque chose :
//
// 1. la fermeture SANS geste envoie une observation `touched:false` — c'est
//    l'étiquette POSITIVE « ce cadrage était bon », la moitié du signal, et
//    elle n'existait nulle part ;
// 2. une fermeture APRÈS sauvegarde n'en envoie PAS une seconde (`savedOk`) ;
// 3. la référence du delta est le cercle À L'ÉCRAN (`start_*`), redéfini quand
//    la suggestion Hough s'applique — sinon on attribue à l'humain un
//    déplacement fait par la machine ;
// 4. un échec de l'observation ne retient JAMAIS la fermeture.
//
// ⚠️ C'est le premier test qui monte réellement `CircleCropEditor` : il est
// stubé partout ailleurs (`lot-harness.ts`).
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const cropEditAbandon = vi.fn()
const manualCrop = vi.fn()
const fetchCropEditContext = vi.fn()
const fetchCropSuggestion = vi.fn()

vi.mock('../composables/useReviewApi', () => ({
  fetchCropEditContext: (...a: unknown[]) => fetchCropEditContext(...a),
  fetchCropSuggestion: (...a: unknown[]) => fetchCropSuggestion(...a),
  fetchAssetCropEditContext: vi.fn(),
  fetchAssetCropSuggestion: vi.fn(),
  manualCrop: (...a: unknown[]) => manualCrop(...a),
  manualCropAsset: vi.fn(),
  cropEditAbandon: (...a: unknown[]) => cropEditAbandon(...a),
}))
vi.mock('../composables/useLotReview', () => ({ addLotCrop: vi.fn() }))

const CTX = {
  asset_id: 'A1', source: 'ebay', raw_url: 'http://x/r.jpg', crop_url: '',
  raw_width: 1000, raw_height: 800, hint: { cx: 500, cy: 400, r: 200 },
}

async function mountEditor() {
  const { default: CircleCropEditor } =
    await import('../components/CircleCropEditor.vue')
  const w = mount(CircleCropEditor, { props: { reviewId: 'R1' } })
  await flush()
  return w
}

const flush = () => new Promise((r) => setTimeout(r, 0))

describe('observation du recadrage', () => {
  beforeEach(() => {
    cropEditAbandon.mockReset().mockResolvedValue(undefined)
    manualCrop.mockReset().mockResolvedValue({ asset_id: 'A1' })
    fetchCropEditContext.mockReset().mockResolvedValue({ ...CTX })
    fetchCropSuggestion.mockReset().mockResolvedValue(
      { asset_id: 'A1', circle: null, reason: 'lot' })
  })

  it("fermer sans rien toucher enregistre l'étiquette POSITIVE", async () => {
    const w = await mountEditor()
    ;(w.vm as unknown as { requestClose: () => void }).requestClose()
    await flush()

    expect(cropEditAbandon).toHaveBeenCalledTimes(1)
    const [reviewId, body] = cropEditAbandon.mock.calls[0]
    expect(reviewId).toBe('R1')
    expect(body.touched).toBe(false)
    // La référence du delta est le cercle à l'écran, pas la bbox stockée.
    expect(body.start_origin).toBe('hint')
    expect(body).toMatchObject({ start_cx: 500, start_cy: 400, start_r: 200 })
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('une sauvegarde ne produit PAS une observation de fermeture en plus',
    async () => {
      const w = await mountEditor()
      await (w.vm as unknown as { save: () => Promise<void> }).save()
      await flush()
      w.unmount()          // le parent fait tomber le v-if
      await flush()

      expect(manualCrop).toHaveBeenCalledTimes(1)
      expect(cropEditAbandon).not.toHaveBeenCalled()
      // Le contexte voyage AVEC le recadrage, en 3e argument.
      expect(manualCrop.mock.calls[0][2]).toMatchObject({
        start_origin: 'hint', touched: false, editor_version: 'v1',
      })
    })

  it("la suggestion Hough redéfinit le point de départ du geste", async () => {
    // Sans ça, le delta attribuerait à l'humain le déplacement de la machine.
    fetchCropSuggestion.mockResolvedValue(
      { asset_id: 'A1', circle: { cx: 520, cy: 380, r: 260 }, reason: null })
    const w = await mountEditor()
    ;(w.vm as unknown as { requestClose: () => void }).requestClose()
    await flush()

    const body = cropEditAbandon.mock.calls[0][1]
    expect(body.start_origin).toBe('suggestion')
    expect(body).toMatchObject({ start_cx: 520, start_cy: 380, start_r: 260 })
    expect(body.suggestion_r).toBe(260)
  })

  it("le démontage sans emit('close') est rattrapé — c'est le 5e chemin",
    async () => {
      // `SingleReviewView.resetForCurrent` fait tomber le v-if au changement
      // d'item, sans jamais émettre 'close'.
      const w = await mountEditor()
      w.unmount()
      await flush()
      expect(cropEditAbandon).toHaveBeenCalledTimes(1)
    })

  it("un échec de l'observation ne retient jamais la fermeture", async () => {
    cropEditAbandon.mockRejectedValue(new Error('canonique injoignable'))
    const w = await mountEditor()
    ;(w.vm as unknown as { requestClose: () => void }).requestClose()
    await flush()
    expect(w.emitted('close')).toHaveLength(1)
  })
})
