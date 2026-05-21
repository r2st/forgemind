<script setup>
import { computed, onMounted, ref } from 'vue'
import { Admin, LLMGateway } from '../composables/api'

// ----------------------------------------------------------------------
// Tabs
// ----------------------------------------------------------------------
const TABS = [
  { key: 'providers', label: 'Providers' },
  { key: 'models',    label: 'Models' },
  { key: 'routing',   label: 'Agent Routing' },
  { key: 'usage',     label: 'Usage' },
  { key: 'cost',      label: 'Cost' },
  { key: 'health',    label: 'Health' },
  { key: 'audit',     label: 'Audit' },
]
const activeTab = ref('providers')

// ----------------------------------------------------------------------
// State
// ----------------------------------------------------------------------
const providers = ref([])
const models    = ref([])
const agents    = ref([])      // [{name, role, service, ...}]
const routings  = ref({})      // agent_name -> routing config

const usage  = ref(null)       // {total_requests, total_tokens, total_cost_usd, by_agent, by_model, by_provider}
const cost   = ref(null)       // {current_month_total, projected_month_end, by_provider, by_agent, by_model}
const health = ref([])
const audit  = ref([])

const loading = ref(false)
const error   = ref('')
const banner  = ref('')

// ----------------------------------------------------------------------
// Reference data
// ----------------------------------------------------------------------
const PROVIDER_KINDS = [
  { value: 'cloud',       label: 'Cloud' },
  { value: 'self_hosted', label: 'Self-Hosted' },
]

const PROVIDER_TYPES = [
  // Cloud
  { value: 'openai',                    label: 'OpenAI',              kind: 'cloud' },
  { value: 'anthropic',                 label: 'Anthropic Claude',    kind: 'cloud' },
  { value: 'gemini',                    label: 'Google Gemini',       kind: 'cloud' },
  { value: 'azure_openai',              label: 'Azure OpenAI',        kind: 'cloud' },
  { value: 'bedrock',                   label: 'AWS Bedrock',         kind: 'cloud' },
  { value: 'openrouter',                label: 'OpenRouter',          kind: 'cloud' },
  { value: 'groq',                      label: 'Groq',                kind: 'cloud' },
  { value: 'together',                  label: 'Together AI',         kind: 'cloud' },
  { value: 'fireworks',                 label: 'Fireworks AI',        kind: 'cloud' },
  { value: 'deepinfra',                 label: 'DeepInfra',           kind: 'cloud' },
  { value: 'replicate',                 label: 'Replicate',           kind: 'cloud' },
  // Self-hosted
  { value: 'ollama',                    label: 'Ollama',              kind: 'self_hosted' },
  { value: 'vllm',                      label: 'vLLM',                kind: 'self_hosted' },
  { value: 'tgi',                       label: 'TGI',                 kind: 'self_hosted' },
  { value: 'llamacpp',                  label: 'llama.cpp',           kind: 'self_hosted' },
  { value: 'sglang',                    label: 'SGLang',              kind: 'self_hosted' },
  { value: 'localai',                   label: 'LocalAI',             kind: 'self_hosted' },
  { value: 'custom_openai_compatible',  label: 'Custom OpenAI-Compatible' },
]

const ROUTING_STRATEGIES = [
  { value: '',                  label: 'Default (primary then fallback)' },
  { value: 'cheapest',          label: 'Cheapest' },
  { value: 'lowest_latency',    label: 'Lowest latency' },
  { value: 'highest_quality',   label: 'Highest reasoning quality' },
  { value: 'local_only',        label: 'Local only' },
  { value: 'gpu_aware',         label: 'GPU-aware' },
  { value: 'compliance_aware',  label: 'Compliance-aware' },
  { value: 'round_robin',       label: 'Round-robin' },
]

const RETRY_POLICIES = [
  'exponential_backoff',
  'linear_backoff',
  'none',
]

// ----------------------------------------------------------------------
// Provider form
// ----------------------------------------------------------------------
const showProviderForm = ref(false)
const blankProvider = () => ({
  id: null,
  name: '',
  kind: 'cloud',
  provider_type: 'openai',
  base_url: '',
  api_key: '',
  clear_api_key: false,
  auth_header: '',
  enabled: true,
  provider_metadata: {},
  metadata_text: '{}',
})
const providerForm = ref(blankProvider())

// ----------------------------------------------------------------------
// Model form
// ----------------------------------------------------------------------
const showModelForm = ref(false)
const blankModel = () => ({
  id: null,
  provider_id: null,
  model_name: '',
  display_name: '',
  context_window: 4096,
  max_output_tokens: 2048,
  cost_per_input_token: 0,
  cost_per_output_token: 0,
  capabilities: { reasoning: false, vision: false, tools: false, streaming: true },
  enabled: true,
})
const modelForm = ref(blankModel())

// ----------------------------------------------------------------------
// Agent routing form
// ----------------------------------------------------------------------
const showRoutingForm = ref(false)
const blankRouting = (agentName = '') => ({
  agent_name: agentName,
  primary_model_id: null,
  fallback_model_ids: [],
  temperature: 0.2,
  max_tokens: 1024,
  reasoning_mode: false,
  timeout_s: 90.0,
  retry_policy: 'exponential_backoff',
  routing_strategy: '',
  quota_requests_per_hour: null,
  quota_tokens_per_hour: null,
})
const routingForm = ref(blankRouting())

// ----------------------------------------------------------------------
// Lookups
// ----------------------------------------------------------------------
const providerById = computed(() => Object.fromEntries(providers.value.map((p) => [p.id, p])))
const modelById    = computed(() => Object.fromEntries(models.value.map((m) => [m.id, m])))

function providerLabel(id) {
  const p = providerById.value[id]
  return p ? p.name : `#${id}`
}
function modelLabel(id) {
  const m = modelById.value[id]
  return m ? `${m.display_name} (${m.model_name})` : `#${id}`
}

// ----------------------------------------------------------------------
// Loaders
// ----------------------------------------------------------------------
async function loadProviders() {
  loading.value = true
  try {
    error.value = ''
    providers.value = (await LLMGateway.providers()) || []
  } catch (e) {
    error.value = readError(e, 'Failed to load providers')
  } finally {
    loading.value = false
  }
}

async function loadModels() {
  loading.value = true
  try {
    error.value = ''
    models.value = (await LLMGateway.models()) || []
  } catch (e) {
    error.value = readError(e, 'Failed to load models')
  } finally {
    loading.value = false
  }
}

async function loadAgentsAndRouting() {
  loading.value = true
  try {
    error.value = ''
    if (!models.value.length)    await loadModels()
    if (!providers.value.length) await loadProviders()
    const overview = await Admin.overview()
    agents.value = overview.agents || []
    const next = {}
    await Promise.all(agents.value.map(async (a) => {
      try {
        next[a.name] = await LLMGateway.agentRouting(a.name)
      } catch (_) {
        next[a.name] = { agent_name: a.name, primary_model_id: null, fallback_model_ids: [] }
      }
    }))
    routings.value = next
  } catch (e) {
    error.value = readError(e, 'Failed to load agent routing')
  } finally {
    loading.value = false
  }
}

async function loadUsage() {
  loading.value = true
  try {
    error.value = ''
    usage.value = await LLMGateway.usage({})
  } catch (e) {
    error.value = readError(e, 'Failed to load usage')
  } finally {
    loading.value = false
  }
}

async function loadCost() {
  loading.value = true
  try {
    error.value = ''
    cost.value = await LLMGateway.cost({})
  } catch (e) {
    error.value = readError(e, 'Failed to load cost')
  } finally {
    loading.value = false
  }
}

async function loadHealth() {
  loading.value = true
  try {
    error.value = ''
    const data = await LLMGateway.health()
    health.value = data.providers || []
  } catch (e) {
    error.value = readError(e, 'Failed to load health')
  } finally {
    loading.value = false
  }
}

async function loadAudit() {
  loading.value = true
  try {
    error.value = ''
    const data = await LLMGateway.audit({ limit: 100 })
    audit.value = Array.isArray(data) ? data : data.entries || data.audit || []
  } catch (e) {
    error.value = readError(e, 'Failed to load audit log')
  } finally {
    loading.value = false
  }
}

function selectTab(tab) {
  activeTab.value = tab
  banner.value = ''
  if (tab === 'providers') loadProviders()
  else if (tab === 'models') loadModels()
  else if (tab === 'routing') loadAgentsAndRouting()
  else if (tab === 'usage') loadUsage()
  else if (tab === 'cost') loadCost()
  else if (tab === 'health') loadHealth()
  else if (tab === 'audit') loadAudit()
}

// ----------------------------------------------------------------------
// Provider CRUD
// ----------------------------------------------------------------------
function newProvider() {
  providerForm.value = blankProvider()
  showProviderForm.value = true
}

function editProvider(provider) {
  providerForm.value = {
    id: provider.id,
    name: provider.name,
    kind: provider.kind,
    provider_type: provider.provider_type,
    base_url: provider.base_url || '',
    api_key: '',
    clear_api_key: false,
    auth_header: provider.auth_header || '',
    enabled: provider.enabled,
    provider_metadata: provider.provider_metadata || {},
    metadata_text: JSON.stringify(provider.provider_metadata || {}, null, 2),
  }
  showProviderForm.value = true
}

async function saveProvider() {
  try {
    error.value = ''
    // Parse metadata JSON
    let metadata = {}
    try {
      metadata = providerForm.value.metadata_text
        ? JSON.parse(providerForm.value.metadata_text)
        : {}
    } catch (_) {
      error.value = 'Metadata must be valid JSON'
      return
    }
    const payload = {
      name: providerForm.value.name,
      kind: providerForm.value.kind,
      provider_type: providerForm.value.provider_type,
      base_url: providerForm.value.base_url,
      auth_header: providerForm.value.auth_header,
      enabled: providerForm.value.enabled,
      provider_metadata: metadata,
    }
    if (providerForm.value.api_key) {
      payload.api_key = providerForm.value.api_key
    }
    if (providerForm.value.clear_api_key) {
      payload.clear_api_key = true
    }
    if (providerForm.value.id) {
      await LLMGateway.updateProvider(providerForm.value.id, payload)
    } else {
      await LLMGateway.createProvider(payload)
    }
    showProviderForm.value = false
    banner.value = 'Provider saved.'
    await loadProviders()
  } catch (e) {
    error.value = readError(e, 'Failed to save provider')
  }
}

async function deleteProvider(id) {
  if (!confirm('Delete this provider? Models that reference it will be orphaned.')) return
  try {
    error.value = ''
    await LLMGateway.deleteProvider(id)
    banner.value = 'Provider deleted.'
    await loadProviders()
  } catch (e) {
    error.value = readError(e, 'Failed to delete provider')
  }
}

// ----------------------------------------------------------------------
// Model CRUD
// ----------------------------------------------------------------------
function newModel() {
  if (!providers.value.length) {
    error.value = 'Register a provider before adding a model.'
    return
  }
  modelForm.value = blankModel()
  modelForm.value.provider_id = providers.value[0].id
  showModelForm.value = true
}

function editModel(model) {
  modelForm.value = {
    id: model.id,
    provider_id: model.provider_id,
    model_name: model.model_name,
    display_name: model.display_name,
    context_window: model.context_window,
    max_output_tokens: model.max_output_tokens,
    cost_per_input_token: model.cost_per_input_token,
    cost_per_output_token: model.cost_per_output_token,
    capabilities: {
      reasoning: !!model.capabilities?.reasoning,
      vision:    !!model.capabilities?.vision,
      tools:     !!model.capabilities?.tools,
      streaming: model.capabilities?.streaming !== false,
    },
    enabled: model.enabled,
  }
  showModelForm.value = true
}

async function saveModel() {
  try {
    error.value = ''
    const payload = {
      provider_id: modelForm.value.provider_id,
      model_name: modelForm.value.model_name,
      display_name: modelForm.value.display_name,
      context_window: modelForm.value.context_window,
      max_output_tokens: modelForm.value.max_output_tokens,
      cost_per_input_token: modelForm.value.cost_per_input_token,
      cost_per_output_token: modelForm.value.cost_per_output_token,
      capabilities: { ...modelForm.value.capabilities },
      enabled: modelForm.value.enabled,
    }
    if (modelForm.value.id) {
      await LLMGateway.updateModel(modelForm.value.id, payload)
    } else {
      await LLMGateway.createModel(payload)
    }
    showModelForm.value = false
    banner.value = 'Model saved.'
    await loadModels()
  } catch (e) {
    error.value = readError(e, 'Failed to save model')
  }
}

async function deleteModel(id) {
  if (!confirm('Delete this model? Agent routings that reference it will need to be updated.')) return
  try {
    error.value = ''
    await LLMGateway.deleteModel(id)
    banner.value = 'Model deleted.'
    await loadModels()
  } catch (e) {
    error.value = readError(e, 'Failed to delete model')
  }
}

// ----------------------------------------------------------------------
// Routing CRUD
// ----------------------------------------------------------------------
function editRouting(agentName) {
  const r = routings.value[agentName] || {}
  routingForm.value = {
    agent_name: agentName,
    primary_model_id: r.primary_model_id ?? null,
    fallback_model_ids: Array.isArray(r.fallback_model_ids) ? [...r.fallback_model_ids] : [],
    temperature: r.temperature ?? 0.2,
    max_tokens: r.max_tokens ?? 1024,
    reasoning_mode: !!r.reasoning_mode,
    timeout_s: r.timeout_s ?? 90.0,
    retry_policy: r.retry_policy || 'exponential_backoff',
    routing_strategy: r.routing_strategy || '',
    quota_requests_per_hour: r.quota?.max_requests_per_hour ?? null,
    quota_tokens_per_hour:   r.quota?.max_tokens_per_hour ?? null,
  }
  showRoutingForm.value = true
}

async function saveRouting() {
  try {
    error.value = ''
    if (!routingForm.value.primary_model_id) {
      error.value = 'Pick a primary model before saving.'
      return
    }
    const payload = {
      primary_model_id:   Number(routingForm.value.primary_model_id),
      fallback_model_ids: (routingForm.value.fallback_model_ids || []).map(Number),
      temperature:        Number(routingForm.value.temperature),
      max_tokens:         Number(routingForm.value.max_tokens),
      reasoning_mode:     !!routingForm.value.reasoning_mode,
      timeout_s:          Number(routingForm.value.timeout_s),
      retry_policy:       routingForm.value.retry_policy,
    }
    if (routingForm.value.routing_strategy) {
      payload.routing_strategy = routingForm.value.routing_strategy
    }
    const q = {}
    if (routingForm.value.quota_requests_per_hour) {
      q.max_requests_per_hour = Number(routingForm.value.quota_requests_per_hour)
    }
    if (routingForm.value.quota_tokens_per_hour) {
      q.max_tokens_per_hour = Number(routingForm.value.quota_tokens_per_hour)
    }
    if (Object.keys(q).length) {
      payload.quota = q
    }
    const updated = await LLMGateway.updateAgentRouting(routingForm.value.agent_name, payload)
    routings.value = { ...routings.value, [routingForm.value.agent_name]: updated }
    showRoutingForm.value = false
    banner.value = `Routing updated for ${routingForm.value.agent_name}.`
  } catch (e) {
    error.value = readError(e, 'Failed to save routing')
  }
}

function addFallback(modelId) {
  if (!modelId) return
  const id = Number(modelId)
  if (id === Number(routingForm.value.primary_model_id)) return
  if (routingForm.value.fallback_model_ids.includes(id)) return
  routingForm.value.fallback_model_ids.push(id)
}

function removeFallback(idx) {
  routingForm.value.fallback_model_ids.splice(idx, 1)
}

function moveFallback(idx, delta) {
  const arr = routingForm.value.fallback_model_ids
  const j = idx + delta
  if (j < 0 || j >= arr.length) return
  const tmp = arr[idx]
  arr[idx] = arr[j]
  arr[j] = tmp
}

// ----------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------
function readError(e, fallback) {
  return e?.response?.data?.detail || e?.response?.data?.error || e?.message || fallback
}

function healthClass(status) {
  switch (status) {
    case 'healthy':   return 'text-emerald-300'
    case 'degraded':  return 'text-amber-300'
    case 'down':
    case 'unhealthy': return 'text-red-400'
    default:          return 'text-slate-400'
  }
}

function capList(caps) {
  if (!caps) return []
  return Object.entries(caps).filter(([, v]) => v).map(([k]) => k)
}

function money(n) {
  if (n == null) return '$0.0000'
  return `$${Number(n).toFixed(4)}`
}

function formatRecord(rec) {
  // by_agent / by_model / by_provider entries may be {requests, tokens, cost_usd}
  if (rec == null) return { requests: 0, tokens: 0, cost: 0 }
  return {
    requests: rec.requests ?? 0,
    tokens:   rec.tokens   ?? 0,
    cost:     rec.cost_usd ?? 0,
  }
}

onMounted(() => selectTab('providers'))
</script>

<template>
  <div class="p-6 space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-3xl font-bold text-slate-200">LLM Gateway</h1>
        <p class="text-sm text-slate-400">
          Providers, models, per-agent routing, fallback chains, usage, cost &amp; audit.
        </p>
      </div>
      <span v-if="loading" class="pill bg-indigo-700/30 text-indigo-300">loading…</span>
    </div>

    <div v-if="error" class="px-4 py-3 bg-red-900/30 border border-red-700 rounded-lg text-red-300">
      {{ error }}
    </div>
    <div v-if="banner" class="px-4 py-3 bg-emerald-900/30 border border-emerald-700 rounded-lg text-emerald-300">
      {{ banner }}
    </div>

    <!-- Tabs -->
    <div class="flex flex-wrap gap-1 bg-slate-800 rounded-lg p-1">
      <button
        v-for="tab in TABS"
        :key="tab.key"
        @click="selectTab(tab.key)"
        :class="[
          'px-4 py-2 rounded-md font-medium transition-colors text-sm',
          activeTab === tab.key
            ? 'bg-indigo-600 text-white'
            : 'text-slate-400 hover:text-slate-200',
        ]"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- =================== Providers =================== -->
    <div v-if="activeTab === 'providers'" class="space-y-4">
      <div class="flex justify-between items-center">
        <p class="text-sm text-slate-400">
          Register cloud or self-hosted LLM providers. Agents never talk to providers directly — only through the gateway.
        </p>
        <button @click="newProvider" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg">
          + Add Provider
        </button>
      </div>

      <div v-if="!providers.length" class="text-slate-500 italic">No providers registered yet.</div>

      <div class="grid gap-4">
        <div
          v-for="provider in providers"
          :key="provider.id"
          class="p-4 bg-slate-800 rounded-lg border border-slate-700"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="space-y-2 min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="text-lg font-semibold text-slate-200">{{ provider.name }}</h3>
                <span :class="provider.enabled ? 'pill bg-emerald-700/30 text-emerald-300' : 'pill bg-slate-700/70 text-slate-300'">
                  {{ provider.enabled ? 'enabled' : 'disabled' }}
                </span>
                <span class="pill bg-indigo-700/30 text-indigo-300">{{ provider.kind }}</span>
                <span class="pill bg-slate-700/60 text-slate-300">{{ provider.provider_type }}</span>
                <span v-if="provider.health_status" :class="['pill', healthClass(provider.health_status), 'bg-slate-700/40']">
                  {{ provider.health_status }}
                </span>
              </div>
              <div class="text-sm text-slate-400 space-y-1 font-mono">
                <div>base_url: {{ provider.base_url || '—' }}</div>
                <div>api_key: {{ provider.api_key_set ? (provider.api_key_preview || '••••••') : 'not set' }}</div>
                <div v-if="provider.auth_header">auth_header: {{ provider.auth_header }}</div>
              </div>
            </div>
            <div class="flex space-x-2 shrink-0">
              <button @click="editProvider(provider)" class="px-3 py-1 text-sm bg-slate-700 hover:bg-slate-600 text-slate-200 rounded">
                Edit
              </button>
              <button @click="deleteProvider(provider.id)" class="px-3 py-1 text-sm bg-red-900/50 hover:bg-red-900/70 text-red-300 rounded">
                Delete
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- =================== Models =================== -->
    <div v-if="activeTab === 'models'" class="space-y-4">
      <div class="flex justify-between items-center">
        <p class="text-sm text-slate-400">
          Register the specific models exposed by each provider, with cost &amp; capability metadata used by the routing engine.
        </p>
        <button @click="newModel" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg">
          + Add Model
        </button>
      </div>

      <div v-if="!models.length" class="text-slate-500 italic">No models registered yet.</div>

      <div class="grid gap-4">
        <div
          v-for="model in models"
          :key="model.id"
          class="p-4 bg-slate-800 rounded-lg border border-slate-700"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="space-y-2 min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="text-lg font-semibold text-slate-200">{{ model.display_name }}</h3>
                <span :class="model.enabled ? 'pill bg-emerald-700/30 text-emerald-300' : 'pill bg-slate-700/70 text-slate-300'">
                  {{ model.enabled ? 'enabled' : 'disabled' }}
                </span>
                <span class="pill bg-slate-700/60 text-slate-300">{{ providerLabel(model.provider_id) }}</span>
                <span v-for="cap in capList(model.capabilities)" :key="cap" class="pill bg-indigo-700/30 text-indigo-300">{{ cap }}</span>
              </div>
              <div class="text-sm text-slate-400 space-y-1 font-mono">
                <div>model_name: {{ model.model_name }}</div>
                <div>context: {{ model.context_window?.toLocaleString() }} tok · max_output: {{ model.max_output_tokens?.toLocaleString() }} tok</div>
                <div>
                  cost in:  ${{ Number(model.cost_per_input_token  || 0).toFixed(6) }}/tok ·
                  cost out: ${{ Number(model.cost_per_output_token || 0).toFixed(6) }}/tok
                </div>
              </div>
            </div>
            <div class="flex space-x-2 shrink-0">
              <button @click="editModel(model)" class="px-3 py-1 text-sm bg-slate-700 hover:bg-slate-600 text-slate-200 rounded">
                Edit
              </button>
              <button @click="deleteModel(model.id)" class="px-3 py-1 text-sm bg-red-900/50 hover:bg-red-900/70 text-red-300 rounded">
                Delete
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- =================== Agent Routing =================== -->
    <div v-if="activeTab === 'routing'" class="space-y-4">
      <p class="text-sm text-slate-400">
        Assign a primary model and ordered fallback chain to each Hermes agent. The routing strategy controls how the
        gateway selects among them.
      </p>

      <div v-if="!agents.length" class="text-slate-500 italic">No agents discovered.</div>

      <div class="grid gap-4">
        <div
          v-for="agent in agents"
          :key="agent.name"
          class="p-4 bg-slate-800 rounded-lg border border-slate-700"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="space-y-2 min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="text-lg font-semibold text-slate-200">{{ agent.name }}</h3>
                <span class="pill bg-slate-700/60 text-slate-300">{{ agent.service }}</span>
                <span v-if="routings[agent.name]?.routing_strategy" class="pill bg-indigo-700/30 text-indigo-300">
                  {{ routings[agent.name].routing_strategy }}
                </span>
              </div>
              <div class="text-sm text-slate-400 font-mono space-y-1">
                <div>
                  primary:
                  <span class="text-slate-200">
                    {{ routings[agent.name]?.primary_model_id
                       ? modelLabel(routings[agent.name].primary_model_id)
                       : '— not configured —' }}
                  </span>
                </div>
                <div>
                  fallback:
                  <span v-if="(routings[agent.name]?.fallback_model_ids || []).length" class="text-slate-300">
                    <span v-for="(id, idx) in routings[agent.name].fallback_model_ids" :key="id">
                      {{ modelLabel(id) }}<span v-if="idx < routings[agent.name].fallback_model_ids.length - 1"> → </span>
                    </span>
                  </span>
                  <span v-else class="text-slate-500">none</span>
                </div>
                <div>
                  temp: {{ routings[agent.name]?.temperature ?? '—' }} ·
                  max_tokens: {{ routings[agent.name]?.max_tokens ?? '—' }} ·
                  timeout: {{ routings[agent.name]?.timeout_s ?? '—' }}s ·
                  retry: {{ routings[agent.name]?.retry_policy ?? '—' }} ·
                  reasoning: {{ routings[agent.name]?.reasoning_mode ? 'on' : 'off' }}
                </div>
              </div>
            </div>
            <div class="flex space-x-2 shrink-0">
              <button @click="editRouting(agent.name)" class="px-3 py-1 text-sm bg-indigo-700 hover:bg-indigo-600 text-white rounded">
                Configure
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- =================== Usage =================== -->
    <div v-if="activeTab === 'usage'" class="space-y-4">
      <div v-if="!usage" class="text-slate-500 italic">No usage recorded yet.</div>

      <div v-else class="space-y-4">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <div class="text-sm text-slate-400">Total Requests</div>
            <div class="text-2xl font-bold text-slate-200">{{ (usage.total_requests || 0).toLocaleString() }}</div>
          </div>
          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <div class="text-sm text-slate-400">Total Tokens</div>
            <div class="text-2xl font-bold text-slate-200">{{ (usage.total_tokens || 0).toLocaleString() }}</div>
          </div>
          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <div class="text-sm text-slate-400">Total Cost</div>
            <div class="text-2xl font-bold text-slate-200">{{ money(usage.total_cost_usd) }}</div>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <h4 class="text-sm uppercase tracking-wider text-slate-400 mb-3">By Agent</h4>
            <table class="w-full text-sm">
              <thead><tr class="text-xs text-slate-500"><th class="text-left">Agent</th><th class="text-right">Req</th><th class="text-right">Tokens</th><th class="text-right">Cost</th></tr></thead>
              <tbody>
                <tr v-for="(rec, key) in usage.by_agent" :key="key" class="border-t border-slate-700/50">
                  <td class="py-1 text-slate-200 font-mono">{{ key }}</td>
                  <td class="py-1 text-right text-slate-300">{{ formatRecord(rec).requests.toLocaleString() }}</td>
                  <td class="py-1 text-right text-slate-300">{{ formatRecord(rec).tokens.toLocaleString() }}</td>
                  <td class="py-1 text-right text-slate-300">{{ money(formatRecord(rec).cost) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <h4 class="text-sm uppercase tracking-wider text-slate-400 mb-3">By Model</h4>
            <table class="w-full text-sm">
              <thead><tr class="text-xs text-slate-500"><th class="text-left">Model</th><th class="text-right">Req</th><th class="text-right">Tokens</th><th class="text-right">Cost</th></tr></thead>
              <tbody>
                <tr v-for="(rec, key) in usage.by_model" :key="key" class="border-t border-slate-700/50">
                  <td class="py-1 text-slate-200 font-mono">{{ modelLabel(Number(key)) }}</td>
                  <td class="py-1 text-right text-slate-300">{{ formatRecord(rec).requests.toLocaleString() }}</td>
                  <td class="py-1 text-right text-slate-300">{{ formatRecord(rec).tokens.toLocaleString() }}</td>
                  <td class="py-1 text-right text-slate-300">{{ money(formatRecord(rec).cost) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <h4 class="text-sm uppercase tracking-wider text-slate-400 mb-3">By Provider</h4>
            <table class="w-full text-sm">
              <thead><tr class="text-xs text-slate-500"><th class="text-left">Provider</th><th class="text-right">Req</th><th class="text-right">Tokens</th><th class="text-right">Cost</th></tr></thead>
              <tbody>
                <tr v-for="(rec, key) in usage.by_provider" :key="key" class="border-t border-slate-700/50">
                  <td class="py-1 text-slate-200 font-mono">{{ providerLabel(Number(key)) }}</td>
                  <td class="py-1 text-right text-slate-300">{{ formatRecord(rec).requests.toLocaleString() }}</td>
                  <td class="py-1 text-right text-slate-300">{{ formatRecord(rec).tokens.toLocaleString() }}</td>
                  <td class="py-1 text-right text-slate-300">{{ money(formatRecord(rec).cost) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- =================== Cost =================== -->
    <div v-if="activeTab === 'cost'" class="space-y-4">
      <div v-if="!cost" class="text-slate-500 italic">No cost data available yet.</div>

      <div v-else class="space-y-4">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <div class="text-sm text-slate-400">Current month total</div>
            <div class="text-2xl font-bold text-slate-200">{{ money(cost.current_month_total) }}</div>
          </div>
          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <div class="text-sm text-slate-400">Projected month-end</div>
            <div class="text-2xl font-bold text-slate-200">{{ money(cost.projected_month_end) }}</div>
          </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <h4 class="text-sm uppercase tracking-wider text-slate-400 mb-3">By Provider</h4>
            <table class="w-full text-sm">
              <tbody>
                <tr v-for="(amount, key) in cost.by_provider" :key="key" class="border-t border-slate-700/50">
                  <td class="py-1 text-slate-200 font-mono">{{ providerLabel(Number(key)) }}</td>
                  <td class="py-1 text-right text-slate-300">{{ money(amount) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <h4 class="text-sm uppercase tracking-wider text-slate-400 mb-3">By Agent</h4>
            <table class="w-full text-sm">
              <tbody>
                <tr v-for="(amount, key) in cost.by_agent" :key="key" class="border-t border-slate-700/50">
                  <td class="py-1 text-slate-200 font-mono">{{ key }}</td>
                  <td class="py-1 text-right text-slate-300">{{ money(amount) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="p-4 bg-slate-800 rounded-lg border border-slate-700">
            <h4 class="text-sm uppercase tracking-wider text-slate-400 mb-3">By Model</h4>
            <table class="w-full text-sm">
              <tbody>
                <tr v-for="(amount, key) in cost.by_model" :key="key" class="border-t border-slate-700/50">
                  <td class="py-1 text-slate-200 font-mono">{{ modelLabel(Number(key)) }}</td>
                  <td class="py-1 text-right text-slate-300">{{ money(amount) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <!-- =================== Health =================== -->
    <div v-if="activeTab === 'health'" class="space-y-4">
      <div v-if="!health.length" class="text-slate-500 italic">No providers to probe.</div>
      <div v-else class="grid gap-4">
        <div
          v-for="(ph, idx) in health"
          :key="ph.provider_id ?? idx"
          class="p-4 bg-slate-800 rounded-lg border border-slate-700"
        >
          <div class="flex items-center justify-between gap-4">
            <div class="space-y-1 min-w-0">
              <h3 class="text-lg font-semibold text-slate-200">{{ ph.provider_name }}</h3>
              <div :class="['text-sm font-medium', healthClass(ph.status)]">{{ ph.status }}</div>
            </div>
            <div class="text-right text-sm text-slate-400 font-mono">
              <div v-if="ph.latency_ms != null">latency: {{ Math.round(ph.latency_ms) }}ms</div>
              <div v-if="ph.error_rate != null">error rate: {{ (ph.error_rate * 100).toFixed(1) }}%</div>
              <div v-if="ph.last_check">checked: {{ new Date(ph.last_check).toLocaleString() }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- =================== Audit =================== -->
    <div v-if="activeTab === 'audit'" class="space-y-4">
      <div v-if="!audit.length" class="text-slate-500 italic">No audit log entries.</div>
      <div v-else class="bg-slate-800 rounded-lg border border-slate-700 overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-slate-900 text-xs uppercase text-slate-400">
            <tr>
              <th class="px-3 py-2 text-left">Time</th>
              <th class="px-3 py-2 text-left">Agent</th>
              <th class="px-3 py-2 text-left">Provider</th>
              <th class="px-3 py-2 text-left">Model</th>
              <th class="px-3 py-2 text-right">In tok</th>
              <th class="px-3 py-2 text-right">Out tok</th>
              <th class="px-3 py-2 text-right">Cost</th>
              <th class="px-3 py-2 text-right">Latency</th>
              <th class="px-3 py-2 text-left">Status</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-700">
            <tr v-for="entry in audit" :key="entry.id" class="hover:bg-slate-700/40">
              <td class="px-3 py-2 text-slate-400 font-mono">{{ new Date(entry.timestamp).toLocaleString() }}</td>
              <td class="px-3 py-2 text-slate-200 font-mono">{{ entry.agent_name || entry.agent }}</td>
              <td class="px-3 py-2 text-slate-300 font-mono">{{ entry.provider_name }}</td>
              <td class="px-3 py-2 text-slate-300 font-mono">{{ entry.model_name }}</td>
              <td class="px-3 py-2 text-right text-slate-300">{{ (entry.prompt_tokens || 0).toLocaleString() }}</td>
              <td class="px-3 py-2 text-right text-slate-300">{{ (entry.completion_tokens || 0).toLocaleString() }}</td>
              <td class="px-3 py-2 text-right text-slate-300">{{ money(entry.cost_usd) }}</td>
              <td class="px-3 py-2 text-right text-slate-300">{{ Math.round(entry.latency_ms || 0) }}ms</td>
              <td class="px-3 py-2">
                <span :class="entry.status === 'error' ? 'pill bg-red-700/30 text-red-300' : 'pill bg-emerald-700/30 text-emerald-300'">
                  {{ entry.status }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- =================== Provider Modal =================== -->
    <div v-if="showProviderForm" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50" @click.self="showProviderForm = false">
      <div class="bg-slate-800 rounded-lg p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <h2 class="text-2xl font-bold text-slate-200 mb-4">{{ providerForm.id ? 'Edit' : 'New' }} Provider</h2>
        <form @submit.prevent="saveProvider" class="space-y-4">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Display name</label>
              <input v-model="providerForm.name" required class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200" placeholder="e.g. OpenAI Prod" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Kind</label>
              <select v-model="providerForm.kind" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200">
                <option v-for="k in PROVIDER_KINDS" :key="k.value" :value="k.value">{{ k.label }}</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Provider type</label>
              <select v-model="providerForm.provider_type" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200">
                <option v-for="t in PROVIDER_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Base URL</label>
              <input v-model="providerForm.base_url" type="url" required class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200 font-mono" placeholder="https://api.openai.com/v1" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">
                API key <span class="text-slate-500 text-xs">(leave blank to keep existing)</span>
              </label>
              <input v-model="providerForm.api_key" type="password" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200 font-mono" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Auth header</label>
              <input v-model="providerForm.auth_header" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200 font-mono" placeholder="Authorization (default)" />
            </div>
          </div>
          <div>
            <label class="block text-sm font-medium text-slate-300 mb-1">Provider metadata (JSON)</label>
            <textarea
              v-model="providerForm.metadata_text"
              rows="4"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200 font-mono text-sm"
              placeholder='{"region": "us-east-1"}'
            ></textarea>
          </div>
          <div class="flex items-center gap-6">
            <label class="flex items-center space-x-2">
              <input v-model="providerForm.enabled" type="checkbox" class="rounded" />
              <span class="text-sm text-slate-300">Enabled</span>
            </label>
            <label v-if="providerForm.id" class="flex items-center space-x-2">
              <input v-model="providerForm.clear_api_key" type="checkbox" class="rounded" />
              <span class="text-sm text-slate-300">Clear stored API key</span>
            </label>
          </div>
          <div class="flex justify-end space-x-3 pt-2">
            <button type="button" @click="showProviderForm = false" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg">
              Cancel
            </button>
            <button type="submit" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg">
              Save
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- =================== Model Modal =================== -->
    <div v-if="showModelForm" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50" @click.self="showModelForm = false">
      <div class="bg-slate-800 rounded-lg p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <h2 class="text-2xl font-bold text-slate-200 mb-4">{{ modelForm.id ? 'Edit' : 'New' }} Model</h2>
        <form @submit.prevent="saveModel" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-slate-300 mb-1">Provider</label>
            <select v-model.number="modelForm.provider_id" required class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200">
              <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }} ({{ p.provider_type }})</option>
            </select>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Model name (provider id)</label>
              <input v-model="modelForm.model_name" required class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200 font-mono" placeholder="gpt-4o-mini" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Display name</label>
              <input v-model="modelForm.display_name" required class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200" placeholder="GPT-4o mini" />
            </div>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Context window (tokens)</label>
              <input v-model.number="modelForm.context_window" type="number" min="1" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Max output tokens</label>
              <input v-model.number="modelForm.max_output_tokens" type="number" min="1" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200" />
            </div>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Cost per input token ($)</label>
              <input v-model.number="modelForm.cost_per_input_token" type="number" step="0.000001" min="0" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200 font-mono" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Cost per output token ($)</label>
              <input v-model.number="modelForm.cost_per_output_token" type="number" step="0.000001" min="0" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200 font-mono" />
            </div>
          </div>
          <div>
            <label class="block text-sm font-medium text-slate-300 mb-2">Capabilities</label>
            <div class="flex flex-wrap gap-4">
              <label class="flex items-center space-x-2">
                <input v-model="modelForm.capabilities.reasoning" type="checkbox" class="rounded" />
                <span class="text-sm text-slate-300">Reasoning</span>
              </label>
              <label class="flex items-center space-x-2">
                <input v-model="modelForm.capabilities.vision" type="checkbox" class="rounded" />
                <span class="text-sm text-slate-300">Vision</span>
              </label>
              <label class="flex items-center space-x-2">
                <input v-model="modelForm.capabilities.tools" type="checkbox" class="rounded" />
                <span class="text-sm text-slate-300">Tools</span>
              </label>
              <label class="flex items-center space-x-2">
                <input v-model="modelForm.capabilities.streaming" type="checkbox" class="rounded" />
                <span class="text-sm text-slate-300">Streaming</span>
              </label>
            </div>
          </div>
          <label class="flex items-center space-x-2">
            <input v-model="modelForm.enabled" type="checkbox" class="rounded" />
            <span class="text-sm text-slate-300">Enabled</span>
          </label>
          <div class="flex justify-end space-x-3 pt-2">
            <button type="button" @click="showModelForm = false" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg">
              Cancel
            </button>
            <button type="submit" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg">
              Save
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- =================== Routing Modal =================== -->
    <div v-if="showRoutingForm" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50" @click.self="showRoutingForm = false">
      <div class="bg-slate-800 rounded-lg p-6 max-w-3xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <h2 class="text-2xl font-bold text-slate-200 mb-1">Routing for <span class="font-mono text-indigo-300">{{ routingForm.agent_name }}</span></h2>
        <p class="text-sm text-slate-400 mb-4">Primary model, ordered fallback chain, and runtime parameters.</p>

        <form @submit.prevent="saveRouting" class="space-y-4">
          <div>
            <label class="block text-sm font-medium text-slate-300 mb-1">Primary model</label>
            <select v-model.number="routingForm.primary_model_id" required class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200">
              <option :value="null" disabled>— select a model —</option>
              <option v-for="m in models" :key="m.id" :value="m.id">
                {{ m.display_name }} ({{ providerLabel(m.provider_id) }} / {{ m.model_name }})
              </option>
            </select>
          </div>

          <div>
            <label class="block text-sm font-medium text-slate-300 mb-1">Fallback chain (ordered)</label>
            <div v-if="routingForm.fallback_model_ids.length === 0" class="text-sm text-slate-500 italic mb-2">
              No fallbacks. Add models below.
            </div>
            <ol v-else class="space-y-1 mb-2">
              <li
                v-for="(id, idx) in routingForm.fallback_model_ids"
                :key="id"
                class="flex items-center gap-2 px-3 py-2 bg-slate-900 border border-slate-700 rounded-md"
              >
                <span class="text-slate-500 text-xs w-6">#{{ idx + 1 }}</span>
                <span class="text-slate-200 font-mono flex-1">{{ modelLabel(id) }}</span>
                <button type="button" @click="moveFallback(idx, -1)" :disabled="idx === 0" class="px-2 py-0.5 text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-30 text-slate-200 rounded">↑</button>
                <button type="button" @click="moveFallback(idx, 1)" :disabled="idx === routingForm.fallback_model_ids.length - 1" class="px-2 py-0.5 text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-30 text-slate-200 rounded">↓</button>
                <button type="button" @click="removeFallback(idx)" class="px-2 py-0.5 text-xs bg-red-900/50 hover:bg-red-900/70 text-red-300 rounded">remove</button>
              </li>
            </ol>
            <select
              :value="''"
              @change="(e) => { addFallback(e.target.value); e.target.value = '' }"
              class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200"
            >
              <option value="">+ Add fallback model</option>
              <option
                v-for="m in models"
                :key="m.id"
                :value="m.id"
                :disabled="m.id === routingForm.primary_model_id || routingForm.fallback_model_ids.includes(m.id)"
              >
                {{ m.display_name }} ({{ providerLabel(m.provider_id) }} / {{ m.model_name }})
              </option>
            </select>
          </div>

          <div class="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Temperature</label>
              <input v-model.number="routingForm.temperature" type="number" min="0" max="2" step="0.05" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Max tokens</label>
              <input v-model.number="routingForm.max_tokens" type="number" min="1" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Timeout (s)</label>
              <input v-model.number="routingForm.timeout_s" type="number" min="1" step="0.5" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Retry policy</label>
              <select v-model="routingForm.retry_policy" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200">
                <option v-for="r in RETRY_POLICIES" :key="r" :value="r">{{ r }}</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Routing strategy</label>
              <select v-model="routingForm.routing_strategy" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200">
                <option v-for="s in ROUTING_STRATEGIES" :key="s.value" :value="s.value">{{ s.label }}</option>
              </select>
            </div>
            <div class="flex items-end">
              <label class="flex items-center space-x-2">
                <input v-model="routingForm.reasoning_mode" type="checkbox" class="rounded" />
                <span class="text-sm text-slate-300">Reasoning mode</span>
              </label>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Quota: max requests / hour</label>
              <input v-model.number="routingForm.quota_requests_per_hour" type="number" min="0" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200" placeholder="unlimited" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Quota: max tokens / hour</label>
              <input v-model.number="routingForm.quota_tokens_per_hour" type="number" min="0" class="w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-md text-slate-200" placeholder="unlimited" />
            </div>
          </div>

          <div class="flex justify-end space-x-3 pt-2">
            <button type="button" @click="showRoutingForm = false" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg">
              Cancel
            </button>
            <button type="submit" class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg">
              Save routing
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pill {
  @apply inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium;
}
</style>
