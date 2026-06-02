/* Types pour coin3d.js (moteur Three.js, copié verbatim du proto). */
import type * as THREE from 'three'

export const R_OUT: number
export const DEFAULT_NORMAL_STRENGTH: number
export const DEFAULT_METALNESS: number
export const DEFAULT_ROUGHNESS: number
export const DEFAULT_EXPOSURE: number
export const REVERSE_RELIEF_BOOST: number

export interface Stage {
  renderer: THREE.WebGLRenderer
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  pmrem: THREE.PMREMGenerator
  onFrame(cb: (dt: number, now: number) => void): () => void
  start(): void
  stop(): void
  resize(): void
  setExposure(v: number): void
  dispose(): void
}

export interface Coin {
  group: THREE.Group
  matSilver?: THREE.MeshStandardMaterial
  matGold?: THREE.MeshStandardMaterial
  [k: string]: unknown
}

export function createStage(canvasWrap: HTMLElement, opts?: { exposure?: number }): Stage
export function buildCoinFromUrls(
  urls: { obverse: string; reverse: string },
  opts?: { edgeTex?: THREE.Texture },
): Promise<Coin>
export function disposeCoin(coin: Coin): void
export function buildProceduralEdgeTexture(): THREE.Texture
