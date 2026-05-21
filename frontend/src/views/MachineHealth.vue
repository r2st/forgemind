<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { Machines } from '../composables/api'

const list = ref([])
const snap = ref([])
let timer = null

async function tick() {
  list.value = await Machines.list()
  snap.value = await Machines.snapshot()
}
onMounted(() => { tick(); timer = setInterval(tick, 5000) })
onBeforeUnmount(() => clearInterval(timer))

const ANOMALIES = [
  'vibration_spike', 'thermal_runaway', 'pressure_drop',
  'motor_stall', 'quality_spike', 'power_surge',
]
async function inject(machine_id, kind) {
  await Machines.inject({ machine_id, kind, duration_ticks: 60 })
  await tick()
}

function snapFor(id) { return snap.value.find((s) => s.machine_id === id) || {} }
function badge(state) {
  return state === 'RUNNING' ? 'bg-emerald-700/30 text-emerald-300'
    : state === 'IDLE' ? 'bg-slate-700 text-slate-200'
    : state === 'MAINTENANCE' ? 'bg-blue-900 text-blue-200'
    : 'bg-crit-600/30 text-crit-500'
}
</script>

<template>
  <div class="space-y-4">
    <div>
      <h1 class="text-2xl font-semibold text-slate-100">Machine Health</h1>
      <p class="text-sm text-slate-400">Live telemetry · inject anomalies to drive the demo flow.</p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div v-for="m in list" :key="m.machine_id" class="card space-y-3">
        <div class="flex items-center justify-between">
          <div>
            <div class="font-mono text-slate-100 font-semibold">{{ m.machine_id }}</div>
            <div class="text-xs text-slate-400">{{ m.machine_type }} · {{ m.line_id }}</div>
          </div>
          <span class="pill" :class="badge(snapFor(m.machine_id).state || m.state)">
            {{ snapFor(m.machine_id).state || m.state }}
          </span>
        </div>

        <div class="grid grid-cols-3 gap-2 text-xs">
          <div class="bg-ink-700/60 rounded-md p-2">
            <div class="text-slate-500">Temp</div>
            <div class="font-mono text-slate-100">{{ snapFor(m.machine_id).temperature_c?.toFixed(1) ?? '—' }} °C</div>
          </div>
          <div class="bg-ink-700/60 rounded-md p-2">
            <div class="text-slate-500">Vibration</div>
            <div class="font-mono text-slate-100">{{ snapFor(m.machine_id).vibration_mm_s?.toFixed(2) ?? '—' }} mm/s</div>
          </div>
          <div class="bg-ink-700/60 rounded-md p-2">
            <div class="text-slate-500">Pressure</div>
            <div class="font-mono text-slate-100">{{ snapFor(m.machine_id).pressure_bar?.toFixed(2) ?? '—' }} bar</div>
          </div>
          <div class="bg-ink-700/60 rounded-md p-2">
            <div class="text-slate-500">RPM</div>
            <div class="font-mono text-slate-100">{{ snapFor(m.machine_id).rpm?.toFixed(0) ?? '—' }}</div>
          </div>
          <div class="bg-ink-700/60 rounded-md p-2">
            <div class="text-slate-500">Power</div>
            <div class="font-mono text-slate-100">{{ snapFor(m.machine_id).power_kw?.toFixed(1) ?? '—' }} kW</div>
          </div>
          <div class="bg-ink-700/60 rounded-md p-2">
            <div class="text-slate-500">Defects</div>
            <div class="font-mono text-slate-100">{{ snapFor(m.machine_id).defects ?? 0 }}</div>
          </div>
        </div>

        <div>
          <div class="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Inject anomaly</div>
          <div class="flex flex-wrap gap-1">
            <button
              v-for="a in ANOMALIES" :key="a"
              class="text-[10px] px-2 py-1 rounded bg-ink-700 hover:bg-accent-700 hover:text-ink-900 transition"
              @click="inject(m.machine_id, a)"
            >{{ a.replace('_', ' ') }}</button>
          </div>
          <div v-if="m.active_anomalies?.length" class="mt-1 text-[10px] text-warn-500">
            Active: {{ m.active_anomalies.join(', ') }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
