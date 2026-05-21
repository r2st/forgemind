<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { Incidents, RCA } from '../composables/api'
import SeverityPill from '../components/SeverityPill.vue'

const all = ref([])
const sevFilter = ref('')
const machineFilter = ref('')
const running = ref(null)
let timer = null

async function tick() { all.value = await Incidents.list({ limit: 200 }) }
onMounted(() => { tick(); timer = setInterval(tick, 7000) })
onBeforeUnmount(() => clearInterval(timer))

const filtered = computed(() => all.value.filter((i) =>
  (!sevFilter.value || i.severity === sevFilter.value) &&
  (!machineFilter.value || i.machine_id.toLowerCase().includes(machineFilter.value.toLowerCase()))
))

async function runRCA(id) {
  running.value = id
  try { await RCA.run(id); alert('RCA generated. See RCA Reports page.') }
  catch (e) { alert('RCA failed: ' + e.message) }
  finally { running.value = null }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-end justify-between gap-4 flex-wrap">
      <div>
        <h1 class="text-2xl font-semibold text-slate-100">Incident Explorer</h1>
        <p class="text-sm text-slate-400">Browse anomalies detected by the statistical + Isolation Forest pipeline.</p>
      </div>
      <div class="flex gap-2">
        <select v-model="sevFilter" class="bg-ink-700 border border-ink-600 rounded-md px-2 py-1 text-sm">
          <option value="">All severities</option>
          <option v-for="s in ['CRITICAL','HIGH','MEDIUM','LOW','INFO']" :key="s">{{ s }}</option>
        </select>
        <input v-model="machineFilter" placeholder="Filter machine_id…" class="bg-ink-700 border border-ink-600 rounded-md px-2 py-1 text-sm" />
      </div>
    </div>

    <div class="card overflow-x-auto">
      <table class="w-full text-sm">
        <thead class="text-xs text-slate-400 uppercase tracking-wider border-b border-ink-600">
          <tr>
            <th class="text-left py-2">Detected</th><th class="text-left">Machine</th>
            <th class="text-left">Metric</th><th class="text-left">Title</th>
            <th class="text-left">Sev</th><th class="text-right">Score</th>
            <th class="text-right">z</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="i in filtered.slice(0, 200)" :key="i.incident_id" class="border-b border-ink-700/40">
            <td class="py-2 font-mono text-xs text-slate-400">{{ new Date(i.detected_at).toLocaleString() }}</td>
            <td class="font-mono">{{ i.machine_id }}</td>
            <td class="text-slate-300">{{ i.metric }}</td>
            <td class="text-slate-200">{{ i.title }}</td>
            <td><SeverityPill :severity="i.severity" /></td>
            <td class="text-right font-mono">{{ i.score?.toFixed(2) }}</td>
            <td class="text-right font-mono">{{ i.z_score?.toFixed(2) }}</td>
            <td class="text-right">
              <button
                class="text-xs px-2 py-1 rounded bg-accent-600 text-ink-900 hover:bg-accent-500 disabled:opacity-50"
                :disabled="running === i.incident_id"
                @click="runRCA(i.incident_id)"
              >{{ running === i.incident_id ? 'Running…' : 'Run RCA' }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
