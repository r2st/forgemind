<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { Notifications, Machines } from '../composables/api'

const notifCount = ref(0)
const onlineMachines = ref(0)
const totalMachines = ref(0)
const lastSync = ref(new Date())

let timer = null

async function tick() {
  try {
    const notifs = await Notifications.recent()
    notifCount.value = notifs.length
  } catch {}
  try {
    const m = await Machines.list()
    totalMachines.value = m.length
    onlineMachines.value = m.filter((x) => x.state !== 'DOWN').length
  } catch {}
  lastSync.value = new Date()
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 10000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <header class="h-14 shrink-0 flex items-center justify-between px-6 border-b border-ink-600 bg-ink-800/80 backdrop-blur">
    <div class="flex items-center gap-3">
      <span class="inline-flex h-2 w-2 rounded-full bg-accent-500 animate-pulse"></span>
      <span class="text-sm text-slate-300 font-medium">plant-01 / line-A · line-B · line-C</span>
    </div>

    <div class="flex items-center gap-5 text-xs text-slate-400">
      <div>
        <span class="text-slate-500">Machines </span>
        <span class="font-mono text-slate-100">{{ onlineMachines }}/{{ totalMachines }}</span>
      </div>
      <div>
        <span class="text-slate-500">Alerts </span>
        <span class="font-mono text-warn-500">{{ notifCount }}</span>
      </div>
      <div>
        <span class="text-slate-500">Synced </span>
        <span class="font-mono">{{ lastSync.toLocaleTimeString() }}</span>
      </div>
      <div class="h-6 w-px bg-ink-600"></div>
      <div class="flex items-center gap-2">
        <div class="h-7 w-7 rounded-full bg-accent-700 flex items-center justify-center text-ink-900 font-semibold text-xs">FM</div>
        <span>Subhendu · admin</span>
      </div>
    </div>
  </header>
</template>
