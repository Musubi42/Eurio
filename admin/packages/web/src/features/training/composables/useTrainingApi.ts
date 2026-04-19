// Training API composables — thin fetch wrappers around the FastAPI ML server.
//
// The ML server runs locally (go-task ml:api → http://localhost:8042). All
// training state lives there (SQLite). The admin page polls /training/runs/active
// while a run is in-flight and refreshes history/classes on demand.

import { ref, type Ref } from 'vue'

export const ML_API = 'http://localhost:8042'

export type ClassKind = 'eurio_id' | 'design_group_id'

export interface ClassRef {
  class_id: string
  class_kind: ClassKind
}

export interface TrainingRunStep {
  step_index: number
  name: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  started_at: string | null
  finished_at: string | null
  detail: string | null
}

export interface TrainingRunEpoch {
  epoch: number
  train_loss: number | null
  recall_at_1: number | null
  recall_at_3: number | null
  lr: number | null
  duration_sec: number | null
}

export interface PerClassMetric {
  class_id: string
  class_kind: ClassKind
  recall_at_1: number | null
  n_train_images: number | null
  n_val_images: number | null
}

export interface TrainingRun {
  id: string
  version: number
  status: 'queued' | 'running' | 'completed' | 'failed'
  started_at: string | null
  finished_at: string | null
  config: Record<string, unknown>
  classes_before: ClassRef[]
  classes_after: ClassRef[]
  classes_added: ClassRef[]
  classes_removed: ClassRef[]
  loss: number | null
  recall_at_1: number | null
  recall_at_3: number | null
  epoch_duration_median_sec: number | null
  error: string | null
  // only on active or detail fetches
  steps?: TrainingRunStep[]
  epoch?: number
  epochs_total?: number
  epochs?: TrainingRunEpoch[]
  per_class_metrics?: PerClassMetric[]
  // synthesised client-side
  n_added?: number
  n_removed?: number
  n_after?: number
}

export interface TrainingRunsListResponse {
  items: TrainingRun[]
  total: number
}

export interface StagingResponse {
  staged: ClassRef[]
  removal: ClassRef[]
}

export interface ModelClassSummary {
  class_id: string
  class_kind: ClassKind
  last_trained_version: number | null
  recall_at_1: number | null
  n_train_images: number | null
  n_val_images: number | null
}

export interface EstimateResponse {
  estimated_sec: number
  basis: 'historical' | 'default'
  current_classes: number
  new_classes: number
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${ML_API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    const body = await resp.text().catch(() => '')
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`)
  }
  return resp.json() as Promise<T>
}

// ─── Health ────────────────────────────────────────────────────────────

export async function checkMlApi(): Promise<boolean> {
  try {
    const resp = await fetch(`${ML_API}/health`, {
      signal: AbortSignal.timeout(3000),
    })
    return resp.ok
  } catch {
    return false
  }
}

// ─── Staging ───────────────────────────────────────────────────────────

export async function fetchStaging(): Promise<StagingResponse> {
  return json<StagingResponse>('/training/stage')
}

export async function stageClasses(items: ClassRef[]): Promise<StagingResponse> {
  return json<StagingResponse>('/training/stage', {
    method: 'POST',
    body: JSON.stringify({ items }),
  }).then(r => {
    // stage endpoint returns {staged: [...]}; re-read removal list to stay in sync.
    return { staged: (r as unknown as { staged: ClassRef[] }).staged, removal: [] }
  })
}

export async function unstageClass(classId: string): Promise<void> {
  await json(`/training/stage/${encodeURIComponent(classId)}`, {
    method: 'DELETE',
  })
}

export async function stageRemoval(items: ClassRef[]): Promise<void> {
  await json('/training/removal', {
    method: 'POST',
    body: JSON.stringify({ items }),
  })
}

export async function unstageRemoval(classId: string): Promise<void> {
  await json(`/training/removal/${encodeURIComponent(classId)}`, {
    method: 'DELETE',
  })
}

// ─── Runs ──────────────────────────────────────────────────────────────

export async function startRun(config?: {
  epochs?: number
  batch_size?: number
  m_per_class?: number
  target_augmented?: number
}): Promise<TrainingRun> {
  return json<TrainingRun>('/training/run', {
    method: 'POST',
    body: JSON.stringify(config ?? {}),
  })
}

export async function fetchActiveRun(): Promise<TrainingRun | null> {
  return json<TrainingRun | null>('/training/runs/active')
}

export async function fetchRuns(limit = 50, offset = 0): Promise<TrainingRunsListResponse> {
  return json<TrainingRunsListResponse>(
    `/training/runs?limit=${limit}&offset=${offset}`,
  )
}

export async function fetchRunDetail(runId: string): Promise<TrainingRun> {
  return json<TrainingRun>(`/training/runs/${encodeURIComponent(runId)}`)
}

export async function fetchRunLogs(runId: string, tail = 200): Promise<{ run_id: string, status: string, lines: string[] }> {
  return json(`/training/runs/${encodeURIComponent(runId)}/logs?tail=${tail}`)
}

// ─── Classes ───────────────────────────────────────────────────────────

export async function fetchTrainedClasses(): Promise<{ items: ModelClassSummary[], total: number }> {
  return json('/training/classes')
}

export async function fetchClassDetail(classId: string): Promise<{
  class_id: string
  class_kind: ClassKind
  runs: Array<{
    run_id: string
    version: number
    status: string
    started_at: string | null
    finished_at: string | null
    recall_at_1: number | null
    n_train_images: number | null
    n_val_images: number | null
  }>
}> {
  return json(`/training/classes/${encodeURIComponent(classId)}`)
}

// ─── Estimate ──────────────────────────────────────────────────────────

export async function estimateDuration(
  addedCount: number,
  removedCount: number,
): Promise<EstimateResponse> {
  return json('/training/estimate', {
    method: 'POST',
    body: JSON.stringify({ added_count: addedCount, removed_count: removedCount }),
  })
}

// ─── Polling helper ────────────────────────────────────────────────────

/**
 * Poll a fetch fn at `interval` ms. Starts disabled; call `start()` to begin.
 * The handle auto-stops when the page is unmounted (caller uses onUnmounted).
 */
export function usePoller<T>(
  fn: () => Promise<T>,
  interval: number,
  onResult: (value: T) => void,
): { start: () => void, stop: () => void, running: Ref<boolean> } {
  const running = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  async function tick() {
    try {
      const result = await fn()
      onResult(result)
    } catch {
      // swallow — transient failures shouldn't kill the poller
    }
  }

  function start() {
    if (running.value) return
    running.value = true
    void tick()
    timer = setInterval(tick, interval)
  }

  function stop() {
    if (timer) clearInterval(timer)
    timer = null
    running.value = false
  }

  return { start, stop, running }
}
