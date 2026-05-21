<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { Agents, Workflows } from '../composables/api'

const tab = ref('agents')   // agents | workflows
const agents = ref([])
const activity = ref([])
const workflows = ref([])
const runs = ref([])
const selected = ref(null)
const selectedRun = ref(null)
let timer = null

async function tick() {
  agents.value = await Agents.list()
  activity.value = await Agents.activity(100)
  try {
    workflows.value = await Workflows.list()
    runs.value = await Workflows.runs(80)
  } catch (e) {
    // workflow-engine may be down in dev
  }
}
onMounted(() => { tick(); timer = setInterval(tick, 5000) })
onBeforeUnmount(() => clearInterval(timer))

const byAgent = computed(() => {
  const out = {}
  agents.value.forEach((a) => { out[a.name] = { ...a, count: 0, last: null, tokens: 0, cost: 0 } })
  activity.value.forEach((a) => {
    const k = a.agent_name
    if (!out[k]) out[k] = { name: k, count: 0, last: null, tokens: 0, cost: 0 }
    out[k].count++
    out[k].tokens += (a.tokens_in || 0) + (a.tokens_out || 0)
    out[k].cost += a.cost_usd || 0
    if (!out[k].last || new Date(a.started_at) > new Date(out[k].last)) out[k].last = a.started_at
  })
  return Object.values(out)
})

function statusClass(s) {
  return s === 'completed' ? 'pill bg-emerald-700/30 text-emerald-300'
    : s === 'running' ? 'pill bg-blue-700/30 text-blue-300 animate-pulse'
    : s === 'blocked_on_approval' ? 'pill bg-warn-600/30 text-warn-500'
    : 'pill bg-crit-600/30 text-crit-500'
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-end justify-between gap-4 flex-wrap">
      <div>
        <h1 class="text-2xl font-semibold text-slate-100">AI Agent Activity</h1>
        <p class="text-sm text-slate-400">
          Hermes agents and LangGraph workflows · all inference via TrueFoundry.
        </p>
      </div>
      <div class="flex gap-1 bg-ink-700/60 p-1 rounded-lg">
        <button class="px-3 py-1 text-sm rounded-md" :class="tab === 'agents' ? 'bg-accent-600 text-ink-900' : 'text-slate-300'" @click="tab = 'agents'">Agents</button>
        <button class="px-3 py-1 text-sm rounded-md" :class="tab === 'workflows' ? 'bg-accent-600 text-ink-900' : 'text-slate-300'" @click="tab = 'workflows'">Workflows (LangGraph)</button>
      </div>
    </div>

    <!-- ================== AGENTS TAB ================== -->
    <template v-if="tab === 'agents'">
      <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <div v-for="a in byAgent" :key="a.name" class="card-tight">
          <div class="text-xs text-slate-400 truncate" :title="a.name">{{ a.name }}</div>
          <div class="font-mono text-2xl text-slate-100">{{ a.count }}</div>
          <div class="text-[10px] text-slate-500 font-mono">{{ a.tokens }} tok</div>
          <div class="text-[10px] text-slate-500 font-mono">${{ a.cost.toFixed(4) }}</div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div class="card lg:col-span-2 max-h-[60vh] overflow-y-auto">
          <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-200 mb-3">Recent runs</h2>
          <table class="w-full text-xs">
            <thead class="text-[10px] text-slate-400 uppercase tracking-wider border-b border-ink-600">
              <tr><th class="text-left py-1">When</th><th class="text-left">Agent</th><th class="text-left">Task</th><th class="text-left">Status</th><th class="text-right">tok</th><th class="text-right">$</th></tr>
            </thead>
            <tbody>
              <tr v-for="a in activity" :key="a.activity_id" class="border-b border-ink-700/40 cursor-pointer hover:bg-ink-700/40" @click="selected = a">
                <td class="py-1.5 font-mono text-[10px] text-slate-400">{{ new Date(a.started_at).toLocaleTimeString() }}</td>
                <td class="font-mono text-slate-200">{{ a.agent_name }}</td>
                <td class="truncate max-w-[280px] text-slate-300" :title="a.task">{{ a.task }}</td>
                <td><span :class="statusClass(a.status)">{{ a.status }}</span></td>
                <td class="text-right font-mono">{{ (a.tokens_in||0) + (a.tokens_out||0) }}</td>
                <td class="text-right font-mono">{{ (a.cost_usd || 0).toFixed(5) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="card lg:col-span-1">
          <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-200 mb-3">Run detail</h2>
          <div v-if="selected" class="space-y-3 text-xs">
            <div><div class="text-slate-500 uppercase tracking-wider text-[10px]">Agent</div><div class="font-mono text-slate-100">{{ selected.agent_name }} · tier {{ selected.tier }}</div></div>
            <div><div class="text-slate-500 uppercase tracking-wider text-[10px]">Task</div><div class="text-slate-100">{{ selected.task }}</div></div>
            <div><div class="text-slate-500 uppercase tracking-wider text-[10px]">Model</div><div class="font-mono text-slate-100">{{ selected.model_used }}</div></div>
            <div><div class="text-slate-500 uppercase tracking-wider text-[10px]">TrueFoundry trace</div><div class="font-mono text-slate-100 truncate">{{ selected.tfy_trace_id || '—' }}</div></div>
            <div>
              <div class="text-slate-500 uppercase tracking-wider text-[10px]">Tool calls</div>
              <ul class="space-y-1 mt-1">
                <li v-for="(t, i) in selected.tool_calls" :key="i" class="bg-ink-700/40 rounded p-2">
                  <span class="font-mono text-accent-500">{{ t.tool }}</span>
                  <div class="text-slate-400 truncate">{{ JSON.stringify(t.args) }}</div>
                </li>
                <li v-if="!selected.tool_calls?.length" class="text-slate-500 italic">No tool calls.</li>
              </ul>
            </div>
            <div><div class="text-slate-500 uppercase tracking-wider text-[10px]">Result</div><div class="text-slate-100 whitespace-pre-wrap">{{ selected.result }}</div></div>
          </div>
          <div v-else class="text-slate-500 italic">Click a run.</div>
        </div>
      </div>
    </template>

    <!-- ================== WORKFLOWS TAB ================== -->
    <template v-else>
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <div v-for="wf in workflows" :key="wf.name" class="card-tight">
          <div class="text-xs uppercase tracking-wider text-accent-500">{{ wf.name }}</div>
          <div class="text-[10px] text-slate-400 mt-1">{{ wf.nodes.length }} nodes</div>
          <div class="text-[10px] text-slate-500 font-mono truncate" :title="wf.nodes.join(' → ')">{{ wf.nodes.join(' → ') }}</div>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div class="card lg:col-span-2 max-h-[60vh] overflow-y-auto">
          <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-200 mb-3">Workflow runs</h2>
          <table class="w-full text-xs">
            <thead class="text-[10px] text-slate-400 uppercase tracking-wider border-b border-ink-600">
              <tr><th class="text-left py-1">When</th><th class="text-left">Workflow</th><th class="text-left">Status</th><th class="text-right">ms</th><th class="text-right">Nodes</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in runs" :key="r.run_id" class="border-b border-ink-700/40 cursor-pointer hover:bg-ink-700/40" @click="selectedRun = r">
                <td class="py-1.5 font-mono text-[10px] text-slate-400">{{ new Date(r.started_at).toLocaleTimeString() }}</td>
                <td class="font-mono text-slate-200">{{ r.workflow }}</td>
                <td><span :class="statusClass(r.status)">{{ r.status }}</span></td>
                <td class="text-right font-mono">{{ r.elapsed_ms }}</td>
                <td class="text-right font-mono">{{ r.state?.trace?.length || 0 }}</td>
              </tr>
              <tr v-if="!runs.length"><td colspan="5" class="text-slate-500 italic py-4 text-center">No workflow runs yet.</td></tr>
            </tbody>
          </table>
        </div>

        <div class="card lg:col-span-1">
          <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-200 mb-3">Run trace</h2>
          <div v-if="selectedRun" class="space-y-2 text-xs">
            <div><div class="text-slate-500 uppercase tracking-wider text-[10px]">Workflow</div><div class="font-mono text-slate-100">{{ selectedRun.workflow }}</div></div>
            <div><div class="text-slate-500 uppercase tracking-wider text-[10px]">Status</div><div><span :class="statusClass(selectedRun.status)">{{ selectedRun.status }}</span></div></div>
            <div>
              <div class="text-slate-500 uppercase tracking-wider text-[10px] mb-1">Node trace</div>
              <ol class="space-y-1">
                <li v-for="(t, i) in (selectedRun.state?.trace || [])" :key="i" class="bg-ink-700/40 rounded p-2">
                  <div class="font-mono text-accent-500">{{ i + 1 }}. {{ t.node }}</div>
                  <div class="text-slate-400 text-[10px]">{{ Object.entries(t).filter(([k]) => k !== 'node').map(([k,v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ') }}</div>
                </li>
              </ol>
            </div>
            <div v-if="selectedRun.state?.severity">
              <div class="text-slate-500 uppercase tracking-wider text-[10px]">Final severity</div>
              <div class="font-mono text-warn-500">{{ selectedRun.state.severity }}</div>
            </div>
            <div v-if="selectedRun.state?.recommendations?.length">
              <div class="text-slate-500 uppercase tracking-wider text-[10px]">Recommendations</div>
              <ul class="list-disc list-inside text-slate-100">
                <li v-for="(r, i) in selectedRun.state.recommendations" :key="i">{{ r }}</li>
              </ul>
            </div>
          </div>
          <div v-else class="text-slate-500 italic">Click a workflow run.</div>
        </div>
      </div>
    </template>
  </div>
</template>
