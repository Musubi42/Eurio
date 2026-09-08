// SHA-256 pur, synchrone — et pourquoi il ne s'agit pas d'une roue réinventée.
//
// La 2ᵉ passe re-annote un sous-ensemble DÉTERMINISTE des images de la passe 1 :
// `serve.py` trie les `asset_id` par leur empreinte SHA-256 et garde les
// `n_double` premiers. Le front doit tirer le MÊME sous-ensemble, sinon les deux
// instruments ne mesurent pas la même reproductibilité et le plafond du banc ne
// veut plus rien dire.
//
// `crypto.subtle.digest` ferait le calcul, mais il est *asynchrone* et absent
// hors contexte sécurisé comme sous certains runners de test — ce qui obligerait
// à rendre asynchrone toute la chaîne de sélection pour une empreinte de 20
// octets. Une implémentation pure, vérifiée contre les vecteurs de référence de
// la FIPS 180-4, coûte moins cher et se teste sans environnement.

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
  0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
  0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
  0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
  0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
  0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n))

/** L'empreinte SHA-256 d'une chaîne UTF-8, en hexadécimal minuscule. */
export function sha256Hex(message: string): string {
  const octets = new TextEncoder().encode(message)
  const longueurBits = octets.length * 8
  // padding : 0x80, des zéros, puis la longueur sur 64 bits big-endian
  const taille = (((octets.length + 9) >> 6) + 1) << 6
  const bloc = new Uint8Array(taille)
  bloc.set(octets)
  bloc[octets.length] = 0x80
  const vue = new DataView(bloc.buffer)
  vue.setUint32(taille - 4, longueurBits >>> 0, false)
  vue.setUint32(taille - 8, Math.floor(longueurBits / 2 ** 32), false)

  const h = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ])
  const w = new Uint32Array(64)

  for (let debut = 0; debut < taille; debut += 64) {
    for (let i = 0; i < 16; i++) w[i] = vue.getUint32(debut + i * 4, false)
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3)
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0
    }
    let [a, b, c, d, e, f, g, hh] = h
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
      const ch = (e & f) ^ (~e & g)
      const t1 = (hh + S1 + ch + K[i] + w[i]) >>> 0
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
      const maj = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (S0 + maj) >>> 0
      hh = g; g = f; f = e
      e = (d + t1) >>> 0
      d = c; c = b; b = a
      a = (t1 + t2) >>> 0
    }
    const ajout = [a, b, c, d, e, f, g, hh]
    for (let i = 0; i < 8; i++) h[i] = (h[i] + ajout[i]) >>> 0
  }

  return Array.from(h, (x) => x.toString(16).padStart(8, '0')).join('')
}

/** Le nombre d'images re-annotées en 2ᵉ passe — `--n-double` de `serve.py`. */
export const N_DOUBLE = 10

/**
 * Le sous-ensemble de la 2ᵉ passe : les `n` premiers `asset_id` par ordre
 * d'empreinte. Même règle, au caractère près, que `Handler._session` :
 * `sorted(faits, key=lambda k: sha256(k).hexdigest())[:n_double]`.
 */
export function sousEnsemblePasse2(assetIds: string[], n = N_DOUBLE): string[] {
  const ordre = [...new Set(assetIds)].sort((x, y) => {
    const hx = sha256Hex(x)
    const hy = sha256Hex(y)
    return hx < hy ? -1 : hx > hy ? 1 : 0
  })
  return ordre.slice(0, n)
}
