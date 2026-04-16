<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Eye, Monitor, Smartphone, ChevronRight, ChevronDown } from 'lucide-vue-next'

interface SceneEntry {
  id: string
  label: string
  group: string
  phase: number | null
  protoRoute: string | null
  captures: string[]
  status: 'captured' | 'partial' | 'pending'
  state: string | null
}

const scenes = ref<SceneEntry[]>([])
const selectedId = ref<string | null>(null)
const selectedCapture = ref<string | null>(null)
const expandedScenes = ref<Set<string>>(new Set())
const loading = ref(true)
const protoReady = ref(false)
const iframeRef = ref<HTMLIFrameElement | null>(null)

const groups = computed(() => {
  const map = new Map<string, SceneEntry[]>()
  for (const s of scenes.value) {
    const list = map.get(s.group) ?? []
    list.push(s)
    map.set(s.group, list)
  }
  return map
})

const selected = computed(() =>
  scenes.value.find(s => s.id === selectedId.value) ?? null,
)

const screenshotUrl = computed(() => {
  if (!selectedCapture.value) return null
  return `/screenshots/${selectedCapture.value}.png`
})

const statusColors: Record<string, string> = {
  captured: 'var(--success)',
  partial: 'var(--warning)',
  pending: 'var(--ink-400)',
}

const statusIcons: Record<string, string> = {
  captured: '\u{1F7E2}',
  partial: '\u{1F7E1}',
  pending: '\u{23F3}',
}

function selectScene(scene: SceneEntry) {
  selectedId.value = scene.id
  selectedCapture.value = scene.captures[0] ?? null
  if (scene.captures.length > 1) {
    expandedScenes.value.add(scene.id)
  }
}

function selectCapture(sceneId: string, capture: string) {
  selectedId.value = sceneId
  selectedCapture.value = capture
}

function toggleExpanded(sceneId: string) {
  if (expandedScenes.value.has(sceneId)) {
    expandedScenes.value.delete(sceneId)
  } else {
    expandedScenes.value.add(sceneId)
  }
}

function navigateProto(scene: SceneEntry) {
  if (!iframeRef.value?.contentWindow || !scene.protoRoute) return
  iframeRef.value.contentWindow.postMessage({
    type: 'parity:navigate',
    route: scene.protoRoute,
    preset: scene.state ?? null,
  }, '*')
}

function onMessage(ev: MessageEvent) {
  if (!ev.data?.type) return
  if (ev.data.type === 'parity:ready') {
    protoReady.value = true
  }
}

// When selected scene changes and proto is ready, navigate via postMessage
watch([selected, protoReady], ([scene, ready]) => {
  if (scene && ready) {
    navigateProto(scene)
  }
})

async function loadMapping() {
  loading.value = true
  try {
    const res = await fetch('/scene-mapping.json')
    scenes.value = await res.json()
    if (scenes.value.length > 0 && !selectedId.value) {
      selectScene(scenes.value[0])
    }
  } catch (e) {
    console.error('[parity] Failed to load scene-mapping.json', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadMapping()
  window.addEventListener('message', onMessage)
})

onUnmounted(() => {
  window.removeEventListener('message', onMessage)
})
</script>

<template>
  <div class="flex h-full">
    <!-- Sidebar: scene list -->
    <aside class="w-64 flex-shrink-0 overflow-y-auto border-r"
           style="border-color: var(--surface-3); background: var(--surface-1);">
      <div class="px-4 py-4 border-b" style="border-color: var(--surface-3);">
        <h1 class="font-display text-lg italic font-semibold" style="color: var(--indigo-700);">
          Parity Viewer
        </h1>
        <p class="mt-0.5 text-xs" style="color: var(--ink-400);">
          {{ scenes.length }} scenes · Maestro flows
        </p>
      </div>

      <div v-if="loading" class="p-4 space-y-2">
        <div v-for="i in 8" :key="i" class="h-8 animate-pulse rounded-md"
             style="background: var(--surface-2);" />
      </div>

      <nav v-else class="py-2">
        <div v-for="[group, items] in groups" :key="group" class="mb-1">
          <p class="px-4 pt-3 pb-1 text-xs font-medium uppercase tracking-wider"
             style="color: var(--ink-400);">
            {{ group }}
          </p>

          <div v-for="scene in items" :key="scene.id">
            <button
              @click="selectScene(scene)"
              class="flex w-full items-center gap-2 px-4 py-1.5 text-left text-sm transition-colors"
              :class="selectedId === scene.id ? 'font-medium' : 'hover:bg-black/[0.03]'"
              :style="selectedId === scene.id
                ? 'background: var(--indigo-50); color: var(--indigo-700); border-right: 2px solid var(--indigo-600);'
                : 'color: var(--ink-600);'"
            >
              <span class="text-xs flex-shrink-0" :style="`color: ${statusColors[scene.status]}`">
                {{ statusIcons[scene.status] }}
              </span>
              <span class="truncate flex-1">{{ scene.label }}</span>
              <button
                v-if="scene.captures.length > 1"
                @click.stop="toggleExpanded(scene.id)"
                class="flex-shrink-0 p-0.5 rounded hover:bg-black/[0.05]"
              >
                <ChevronDown
                  class="h-3 w-3 transition-transform"
                  :class="expandedScenes.has(scene.id) ? '' : '-rotate-90'"
                  style="color: var(--ink-400);"
                />
              </button>
              <span v-if="scene.phase != null"
                    class="flex-shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-mono"
                    style="background: var(--surface-2); color: var(--ink-400);">
                P{{ scene.phase }}
              </span>
            </button>

            <div v-if="scene.captures.length > 1 && expandedScenes.has(scene.id)" class="ml-7">
              <button
                v-for="capture in scene.captures"
                :key="capture"
                @click="selectCapture(scene.id, capture)"
                class="flex w-full items-center gap-2 pl-3 pr-4 py-1 text-left text-xs transition-colors"
                :class="selectedCapture === capture ? 'font-medium' : 'hover:bg-black/[0.03]'"
                :style="selectedCapture === capture
                  ? 'color: var(--indigo-700);'
                  : 'color: var(--ink-500);'"
              >
                <span class="w-1 h-1 rounded-full flex-shrink-0"
                      :style="selectedCapture === capture
                        ? 'background: var(--indigo-600);'
                        : 'background: var(--ink-300);'" />
                <span class="truncate font-mono">{{ capture }}</span>
              </button>
            </div>
          </div>
        </div>
      </nav>
    </aside>

    <!-- Main: split panes -->
    <div class="flex flex-1 flex-col overflow-hidden">
      <!-- Toolbar -->
      <div class="flex items-center gap-4 border-b px-5 py-3"
           style="border-color: var(--surface-3); background: white;">
        <div v-if="selected" class="flex items-center gap-2 text-sm">
          <span class="font-mono text-xs px-2 py-0.5 rounded"
                style="background: var(--surface-1); color: var(--ink-500);">
            {{ selected.id }}
          </span>
          <ChevronRight class="h-3 w-3" style="color: var(--ink-300);" />
          <span style="color: var(--ink-600);">{{ selected.label }}</span>
          <span v-if="selected.state"
                class="font-mono text-xs px-2 py-0.5 rounded"
                style="background: var(--indigo-50); color: var(--indigo-600);">
            {{ selected.state }}
          </span>
          <span v-if="selectedCapture && selectedCapture !== selected.id"
                class="font-mono text-xs px-2 py-0.5 rounded"
                style="background: var(--surface-2); color: var(--ink-500);">
            {{ selectedCapture }}
          </span>
        </div>
      </div>

      <!-- Split view -->
      <div v-if="!selected" class="flex flex-1 items-center justify-center"
           style="background: var(--surface-1);">
        <div class="text-center">
          <Eye class="mx-auto h-12 w-12 mb-3" style="color: var(--ink-300);" />
          <p class="font-display italic text-lg" style="color: var(--ink-400);">
            Sélectionne une scène
          </p>
        </div>
      </div>

      <div v-else class="flex flex-1 overflow-hidden">
        <!-- Proto pane -->
        <div class="flex-1 flex flex-col border-r" style="border-color: var(--surface-3);">
          <div class="flex items-center gap-2 px-4 py-2 text-xs font-medium uppercase tracking-wider"
               style="background: var(--surface-1); color: var(--ink-400); border-bottom: 1px solid var(--surface-3);">
            <Monitor class="h-3.5 w-3.5" />
            Proto HTML
            <span v-if="!protoReady" class="ml-auto text-[10px] font-normal normal-case"
                  style="color: var(--ink-300);">chargement...</span>
          </div>
          <div class="flex-1 flex items-start justify-center overflow-auto p-4"
               style="background: var(--surface-1);">
            <div class="relative flex-shrink-0 rounded-[2rem] border-[3px] overflow-hidden shadow-lg"
                 style="width: 390px; height: 844px; border-color: var(--ink-200); background: black;">
              <iframe
                ref="iframeRef"
                src="/proto/index.html#/?chrome=embed"
                class="block h-full w-full"
                style="border: none;"
              />
              <!-- Click overlay prevents iframe interaction -->
              <div class="absolute inset-0" style="z-index: 2;" />
            </div>
          </div>
        </div>

        <!-- Screenshot pane -->
        <div class="flex-1 flex flex-col">
          <div class="flex items-center gap-2 px-4 py-2 text-xs font-medium uppercase tracking-wider"
               style="background: var(--surface-1); color: var(--ink-400); border-bottom: 1px solid var(--surface-3);">
            <Smartphone class="h-3.5 w-3.5" />
            Screenshot Android
          </div>
          <div class="flex-1 flex items-start justify-center overflow-auto p-4"
               style="background: var(--surface-1);">
            <div class="relative flex-shrink-0 rounded-[2rem] border-[3px] overflow-hidden shadow-lg"
                 style="width: 390px; height: 844px; border-color: var(--ink-200); background: black;">
              <img
                v-if="screenshotUrl"
                :key="selectedCapture ?? undefined"
                :src="screenshotUrl"
                :alt="`Screenshot ${selectedCapture}`"
                class="absolute inset-0 block h-full w-full object-contain"
                style="z-index: 1;"
                @error="($event.target as HTMLImageElement).style.display = 'none'"
              />
              <div class="absolute inset-0 flex flex-col items-center justify-center gap-3"
                   style="background: var(--surface-2);">
                <Smartphone class="h-10 w-10" style="color: var(--ink-300);" />
                <p class="text-sm text-center px-4" style="color: var(--ink-400);">
                  Pas de screenshot<br />
                  <code class="text-xs font-mono mt-1 block" style="color: var(--ink-500);">
                    go-task android:parity:capture-scene -- {{ selected.id }}
                  </code>
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
