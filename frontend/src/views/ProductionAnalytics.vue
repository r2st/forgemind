<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { Machines } from '../composables/api'
import LineChart from '../components/LineChart.vue'

const snap = ref([])
const history = ref([])
let timer = null

async function tick() {
  snap.value = await Machines.snapshot()
  const total = snap.value.reduce((s, x) => s + (x.units_produced || 0), 0)
  history.value.push({ t: new Date().toLocaleTimeString(), v: total })
  if (history.value.length > 40) history.value.shift()
}
onMounted(() => { tick(); timer = setInterval(tick, 5000) })
onBeforeUnmount(() => clearInterval(timer))

const byLine = computed(() => {
  const lines = {}
  snap.value.forEach((m) => {
    if (!lines[m.line_id]) lines[m.line_id] = { units: 0, defects: 0, machines: 0 }
    lines[m.line_id].units   += m.units_produced || 0
    lines[m.line_id].defects += m.defects || 0
    lines[m.line_id].machines++
  })
  return Object.entries(lines).map(([line_id, v]) => ({ line_id, ...v }))
})

const labels = computed(() => history.value.map((p) => p.t))
const datasets = computed(() => [{
  label: 'Cumulative units (plant)',
  data: history.value.map((p) => p.v),
  borderColor: '#fbbf24',
  backgroundColor: 'rgba(251,191,36,0.10)',
  fill: true,
}])
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold text-slate-100">Production Analytics</h1>
      <p class="text-sm text-slate-400">Throughput, defect rate, line balance.</p>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="stat"><div class="stat-label">Plant units</div><div class="stat-value">{{ snap.reduce((s,x) => s + (x.units_produced||0), 0) }}</div></div>
      <div class="stat"><div class="stat-label">Plant defects</div><div class="stat-value text-warn-500">{{ snap.reduce((s,x) => s + (x.defects||0), 0) }}</div></div>
      <div class="stat"><div class="stat-label">Lines active</div><div class="stat-value">{{ byLine.length }}</div></div>
      <div class="stat">
        <div class="stat-label">Defect rate</div>
        <div class="stat-value">
          {{ (() => { const u = snap.reduce((s,x) => s + (x.units_produced||0), 0); const d = snap.reduce((s,x) => s + (x.defects||0), 0); return u ? ((d/u)*100).toFixed(2) : '0.00'; })() }}%
        </div>
      </div>
    </div>

    <div class="card">
      <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">Cumulative throughput</h2>
      <LineChart :labels="labels" :datasets="datasets" :height="240" />
    </div>

    <div class="card">
      <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider mb-3">By line</h2>
      <table class="w-full text-sm">
        <thead class="text-xs text-slate-400 uppercase tracking-wider border-b border-ink-600">
          <tr><th class="text-left py-2">Line</th><th class="text-right">Machines</th><th class="text-right">Units</th><th class="text-right">Defects</th><th class="text-right">Defect %</th></tr>
        </thead>
        <tbody>
          <tr v-for="l in byLine" :key="l.line_id" class="border-b border-ink-700/40">
            <td class="py-2 font-mono text-slate-100">{{ l.line_id }}</td>
            <td class="text-right font-mono">{{ l.machines }}</td>
            <td class="text-right font-mono">{{ l.units }}</td>
            <td class="text-right font-mono text-warn-500">{{ l.defects }}</td>
            <td class="text-right font-mono">{{ l.units ? ((l.defects / l.units) * 100).toFixed(2) : '0.00' }}%</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
