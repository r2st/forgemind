<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { Incidents, Machines, Predictions } from '../composables/api'
import SeverityPill from '../components/SeverityPill.vue'
import LineChart from '../components/LineChart.vue'

const incidents = ref([])
const machines = ref([])
const snapshots = ref([])
const predictions = ref([])
const series = ref([])    // sliding window of average vibration

let timer = null

async function tick() {
  try {
    incidents.value = await Incidents.list({ limit: 100 })
    machines.value = await Machines.list()
    snapshots.value = await Machines.snapshot()
    predictions.value = await Predictions.list()

    const avgVib = snapshots.value.reduce((s, x) => s + (x.vibration_mm_s || 0), 0) / Math.max(1, snapshots.value.length)
    series.value.push({ t: new Date().toLocaleTimeString(), v: +avgVib.toFixed(3) })
    if (series.value.length > 30) series.value.shift()
  } catch (e) {
    console.error(e)
  }
}

onMounted(() => {
  tick()
  timer = setInterval(tick, 5000)
})
onBeforeUnmount(() => clearInterval(timer))

const totals = computed(() => {
  const bySev = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, INFO: 0 }
  incidents.value.forEach((i) => bySev[i.severity]++)
  return bySev
})
const topRisk = computed(() => predictions.value.slice(0, 5))
const labels = computed(() => series.value.map((p) => p.t))
const datasets = computed(() => [
  {
    label: 'Avg vibration mm/s',
    data: series.value.map((p) => p.v),
    borderColor: '#5eead4',
    backgroundColor: 'rgba(94,234,212,0.10)',
    fill: true,
  },
])

async function triggerDemo() {
  try { await Machines.replayHistorical() } catch {}
  await tick()
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-slate-100">Operations Dashboard</h1>
        <p class="text-sm text-slate-400">
          Real-time plant intelligence — orchestrated by Hermes and the configured LLM API.
        </p>
      </div>
      <button class="btn-primary" @click="triggerDemo">Inject Demo Anomalies</button>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
      <div class="stat"><div class="stat-label">Critical</div><div class="stat-value text-crit-500">{{ totals.CRITICAL }}</div></div>
      <div class="stat"><div class="stat-label">High</div><div class="stat-value text-orange-400">{{ totals.HIGH }}</div></div>
      <div class="stat"><div class="stat-label">Medium</div><div class="stat-value text-warn-500">{{ totals.MEDIUM }}</div></div>
      <div class="stat"><div class="stat-label">Machines online</div><div class="stat-value">{{ machines.filter((m) => m.state !== 'DOWN').length }}/{{ machines.length }}</div></div>
      <div class="stat"><div class="stat-label">Avg vibration</div><div class="stat-value">{{ series.length ? series[series.length-1].v : '—' }}<span class="text-sm text-slate-400 ml-1">mm/s</span></div></div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="card lg:col-span-2">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider">Plant Vibration — Last 5 min</h2>
          <span class="text-xs text-slate-500">live · 5s</span>
        </div>
        <LineChart :labels="labels" :datasets="datasets" :height="220" />
      </div>

      <div class="card">
        <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">Top Failure Risk (72h)</h2>
        <ul class="divide-y divide-ink-600 text-sm">
          <li v-for="p in topRisk" :key="p.machine_id" class="py-2 flex items-center justify-between">
            <div>
              <div class="font-medium text-slate-100">{{ p.machine_id }}</div>
              <div class="text-xs text-slate-500">{{ p.machine_type }} · ETA {{ p.estimated_failure_in_hours }} h</div>
            </div>
            <div class="font-mono text-warn-500">{{ (p.risk_72h * 100).toFixed(0) }}%</div>
          </li>
        </ul>
      </div>
    </div>

    <div class="card">
      <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">Recent Incidents</h2>
      <table class="w-full text-sm">
        <thead class="text-xs text-slate-400 uppercase tracking-wider border-b border-ink-600">
          <tr><th class="text-left py-2">Detected</th><th class="text-left">Machine</th><th class="text-left">Metric</th><th class="text-left">Title</th><th class="text-left">Severity</th></tr>
        </thead>
        <tbody>
          <tr v-for="i in incidents.slice(0, 12)" :key="i.incident_id" class="border-b border-ink-700/40">
            <td class="py-2 font-mono text-xs text-slate-400">{{ new Date(i.detected_at).toLocaleTimeString() }}</td>
            <td class="font-mono text-slate-100">{{ i.machine_id }}</td>
            <td class="text-slate-300">{{ i.metric }}</td>
            <td class="text-slate-200">{{ i.title }}</td>
            <td><SeverityPill :severity="i.severity" /></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
