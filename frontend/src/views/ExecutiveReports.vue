<script setup>
import { ref, onMounted } from 'vue'
import { Reports } from '../composables/api'

const reports = ref([])
const gen = ref(false)

async function refresh() { reports.value = await Reports.list() }
onMounted(refresh)

async function generate(kind) {
  gen.value = true
  try { await Reports.generate(kind); await refresh() }
  finally { gen.value = false }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex justify-between items-center">
      <div>
        <h1 class="text-2xl font-semibold text-slate-100">Executive Reports</h1>
        <p class="text-sm text-slate-400">Hermes Reporting Agent · concise plant operations summaries.</p>
      </div>
      <div class="space-x-2">
        <button class="btn-secondary" :disabled="gen" @click="generate('shift')">Generate Shift Summary</button>
        <button class="btn-primary" :disabled="gen" @click="generate('executive')">{{ gen ? 'Generating…' : 'Generate Executive' }}</button>
      </div>
    </div>

    <div class="space-y-3">
      <div v-for="r in reports" :key="r.report_id" class="card">
        <div class="flex justify-between items-center mb-2">
          <div>
            <span class="pill bg-accent-700/30 text-accent-500">{{ r.kind }}</span>
            <span class="ml-2 text-slate-100 font-medium">{{ r.title }}</span>
          </div>
          <div class="text-xs text-slate-400 font-mono">{{ new Date(r.generated_at).toLocaleString() }}</div>
        </div>
        <div class="text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">{{ r.body }}</div>
        <div v-if="r.meta?.model_used" class="mt-3 pt-3 border-t border-ink-600 text-[10px] text-slate-500 font-mono">
          model {{ r.meta.model_used }} · cost ${{ (r.meta.cost_usd || 0).toFixed(5) }}
        </div>
      </div>
      <div v-if="!reports.length" class="text-slate-400 italic">No reports yet — generate one above.</div>
    </div>
  </div>
</template>
