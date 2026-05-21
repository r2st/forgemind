<script setup>
import { ref, onMounted } from 'vue'
import { Predictions } from '../composables/api'

const rows = ref([])
const loading = ref(true)

onMounted(async () => {
  try { rows.value = await Predictions.list() }
  finally { loading.value = false }
})

function riskClass(r) {
  if (r > 0.75) return 'text-crit-500'
  if (r > 0.5)  return 'text-warn-500'
  if (r > 0.25) return 'text-orange-300'
  return 'text-emerald-300'
}
</script>

<template>
  <div class="space-y-4">
    <h1 class="text-2xl font-semibold text-slate-100">Predictive Maintenance</h1>
    <p class="text-sm text-slate-400">Risk-decayed forecasting + Hermes PdM agent narratives.</p>

    <div v-if="loading" class="text-slate-400">Loading predictions…</div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div v-for="r in rows" :key="r.machine_id" class="card space-y-2">
        <div class="flex items-center justify-between">
          <div>
            <div class="font-mono text-slate-100 font-semibold">{{ r.machine_id }}</div>
            <div class="text-xs text-slate-400">{{ r.machine_type }}</div>
          </div>
          <div class="text-right">
            <div class="text-[10px] uppercase tracking-wider text-slate-500">Risk 72h</div>
            <div class="font-mono text-2xl" :class="riskClass(r.risk_72h)">{{ (r.risk_72h * 100).toFixed(0) }}%</div>
          </div>
        </div>

        <div class="grid grid-cols-3 gap-2 text-xs">
          <div class="bg-ink-700/60 rounded-md p-2">
            <div class="text-slate-500">24h risk</div>
            <div class="font-mono">{{ (r.risk_24h * 100).toFixed(0) }}%</div>
          </div>
          <div class="bg-ink-700/60 rounded-md p-2">
            <div class="text-slate-500">ETA</div>
            <div class="font-mono">{{ r.estimated_failure_in_hours }} h</div>
          </div>
          <div class="bg-ink-700/60 rounded-md p-2">
            <div class="text-slate-500">Signals</div>
            <div class="font-mono text-[10px] truncate" :title="r.contributing_signals.join(', ')">
              {{ r.contributing_signals.length ? r.contributing_signals.join(', ') : '—' }}
            </div>
          </div>
        </div>

        <div class="text-xs text-slate-400 italic">{{ r.rationale }}</div>

        <div class="text-[11px] text-slate-500 font-mono">
          Window: {{ new Date(r.recommended_window_start).toLocaleString() }}
          → {{ new Date(r.recommended_window_end).toLocaleString() }}
        </div>
      </div>
    </div>
  </div>
</template>
