<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Admin, AuthUsers } from '../composables/api'

const overview = ref({ agents: [], services: [], default_config: {} })
const defaultForm = ref(formFromConfig({ provider: 'openai-compatible', enabled: true }))
const agentForms = ref({})
const saving = ref({})
const error = ref('')
let timer = null

const providerOptions = [
  { value: 'default', label: 'default' },
  { value: 'openai-compatible', label: 'OpenAI-compatible' },
  { value: 'disabled', label: 'disabled' },
]

const defaultProviderOptions = providerOptions.filter((p) => p.value !== 'default')

const healthSummary = computed(() => {
  const services = overview.value.services || []
  const ok = services.filter((s) => s.status === 'ok').length
  return { ok, total: services.length, degraded: services.length - ok }
})

async function load() {
  try {
    error.value = ''
    const data = await Admin.overview()
    const next = {}
    ;(data.agents || []).forEach((agent) => {
      next[agent.name] = formFromConfig(agent.llm || {})
    })
    agentForms.value = next
    const defaultConfig = data.default_config || {}
    defaultForm.value = formFromConfig({
      ...defaultConfig,
      provider: defaultConfig.provider === 'default'
        ? (defaultConfig.resolved_provider || 'openai-compatible')
        : defaultConfig.provider,
    })
    overview.value = data
  } catch (e) {
    error.value = e?.response?.data?.detail || e.message || 'Admin API unavailable'
  }
}

function formFromConfig(cfg) {
  return {
    provider: cfg.provider || 'default',
    base_url: cfg.base_url || '',
    model: cfg.model || '',
    enabled: cfg.enabled !== false,
    api_key: '',
    clear_api_key: false,
  }
}

function payloadFromForm(form) {
  const payload = {
    provider: form.provider,
    base_url: form.base_url,
    model: form.model,
    enabled: form.enabled,
  }
  if (form.api_key) payload.api_key = form.api_key
  if (form.clear_api_key) payload.clear_api_key = true
  return payload
}

async function saveDefault() {
  saving.value.default = true
  try {
    await Admin.updateDefault(payloadFromForm(defaultForm.value))
    await load()
  } finally {
    saving.value.default = false
  }
}

async function saveAgent(agentName) {
  saving.value[agentName] = true
  try {
    await Admin.updateAgent(agentName, payloadFromForm(agentForms.value[agentName]))
    await load()
  } finally {
    saving.value[agentName] = false
  }
}

function statusClass(status) {
  return status === 'ok'
    ? 'pill bg-emerald-700/30 text-emerald-300'
    : status === 'disabled'
      ? 'pill bg-slate-700/70 text-slate-300'
      : status === 'needs_config'
        ? 'pill bg-warn-600/30 text-warn-500'
        : 'pill bg-crit-600/30 text-crit-500'
}

function boolText(value) {
  return value ? 'set' : 'missing'
}

// ----------------------------------------------------------------------
// Users tab — bcrypt-hashed auth store + env-var bootstrap fallback
// ----------------------------------------------------------------------
const ROLES = ['viewer', 'operator', 'engineer', 'admin']
const storeUsers = ref([])
const envUsers = ref([])
const userForm = ref(null)         // { username, role, password, isNew }
const userError = ref('')
const userBanner = ref('')
const savingUser = ref(false)

async function loadUsers() {
  try {
    userError.value = ''
    const data = await AuthUsers.list()
    storeUsers.value = data?.users || []
    envUsers.value = (data?.env_users || []).filter(
      (eu) => !storeUsers.value.some((su) => su.username === eu.username),
    )
  } catch (e) {
    userError.value = readUserError(e, 'Failed to load users')
  }
}

function newUserForm() {
  userForm.value = { username: '', role: 'viewer', password: '', isNew: true }
  userBanner.value = ''
  userError.value = ''
}

function editUser(u) {
  userForm.value = { username: u.username, role: u.role, password: '', isNew: false }
  userBanner.value = ''
  userError.value = ''
}

function promoteEnvUser(u) {
  userForm.value = { username: u.username, role: u.role, password: '', isNew: true }
  userBanner.value = 'Set a password to move this bootstrap user into the persistent store.'
  userError.value = ''
}

async function saveUser() {
  if (!userForm.value) return
  const { username, role, password, isNew } = userForm.value
  if (!username.trim()) {
    userError.value = 'Username cannot be empty'
    return
  }
  if (isNew && !password) {
    userError.value = 'A password is required when creating a new user'
    return
  }
  savingUser.value = true
  try {
    userError.value = ''
    const payload = { role }
    if (password) payload.password = password
    await AuthUsers.upsert(username.trim(), payload)
    userBanner.value = isNew ? `Created ${username}` : `Updated ${username}`
    userForm.value = null
    await loadUsers()
  } catch (e) {
    userError.value = readUserError(e, 'Failed to save user')
  } finally {
    savingUser.value = false
  }
}

async function deleteUserConfirm(username) {
  if (!window.confirm(`Delete user "${username}"? This cannot be undone.`)) return
  try {
    userError.value = ''
    await AuthUsers.remove(username)
    userBanner.value = `Deleted ${username}`
    await loadUsers()
  } catch (e) {
    userError.value = readUserError(e, 'Failed to delete user')
  }
}

function readUserError(e, fallback) {
  return e?.response?.data?.detail || e?.message || fallback
}

onMounted(() => {
  load()
  loadUsers()
  timer = setInterval(load, 10000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-end justify-between gap-4 flex-wrap">
      <div>
        <h1 class="text-2xl font-semibold text-slate-100">Admin Panel</h1>
        <p class="text-sm text-slate-400">Agent health, service readiness, and LLM credentials.</p>
      </div>
      <button class="btn-secondary" @click="load">Refresh</button>
    </div>

    <div v-if="error" class="border border-crit-600/50 bg-crit-600/10 text-crit-500 rounded-lg px-4 py-3 text-sm">
      {{ error }}
    </div>

    <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
      <div class="stat">
        <div class="stat-label">Services OK</div>
        <div class="stat-value">{{ healthSummary.ok }}/{{ healthSummary.total }}</div>
        <div class="stat-delta">{{ healthSummary.degraded }} degraded</div>
      </div>
      <div class="stat">
        <div class="stat-label">Agents</div>
        <div class="stat-value">{{ overview.agents?.length || 0 }}</div>
        <div class="stat-delta">configured runtimes</div>
      </div>
      <div class="stat">
        <div class="stat-label">Default API</div>
        <div class="text-lg font-semibold text-slate-100 font-mono truncate">{{ overview.default_config?.resolved_provider || '-' }}</div>
        <div class="stat-delta truncate">{{ overview.default_config?.resolved_model || '-' }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Default Key</div>
        <div class="text-lg font-semibold text-slate-100 font-mono">{{ boolText(overview.default_config?.resolved_api_key_set) }}</div>
        <div class="stat-delta">{{ overview.default_config?.resolved_api_key_source || '-' }}</div>
      </div>
    </div>

    <div class="card space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-sm uppercase tracking-wider text-slate-200">Default LLM</h2>
        <span :class="statusClass(overview.default_config?.resolved_enabled ? 'ok' : 'disabled')">
          {{ overview.default_config?.resolved_enabled ? 'enabled' : 'disabled' }}
        </span>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-5 gap-3 text-sm">
        <label class="space-y-1">
          <span class="text-xs uppercase tracking-wider text-slate-400">API Type</span>
          <select v-model="defaultForm.provider" class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2">
            <option v-for="option in defaultProviderOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label class="space-y-1 md:col-span-2">
          <span class="text-xs uppercase tracking-wider text-slate-400">Base URL</span>
          <input v-model="defaultForm.base_url" class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 font-mono" placeholder="provider default" />
        </label>
        <label class="space-y-1">
          <span class="text-xs uppercase tracking-wider text-slate-400">Model</span>
          <input v-model="defaultForm.model" class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 font-mono" placeholder="tier default" />
        </label>
        <label class="space-y-1">
          <span class="text-xs uppercase tracking-wider text-slate-400">API Key</span>
          <input v-model="defaultForm.api_key" type="password" class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 font-mono" :placeholder="overview.default_config?.api_key_preview || 'unchanged'" />
        </label>
      </div>
      <div class="flex items-center justify-between gap-3 text-sm">
        <label class="inline-flex items-center gap-2 text-slate-300">
          <input v-model="defaultForm.enabled" type="checkbox" class="accent-emerald-500" />
          <span>Enabled</span>
        </label>
        <div class="flex items-center gap-3">
          <label class="inline-flex items-center gap-2 text-slate-400">
            <input v-model="defaultForm.clear_api_key" type="checkbox" class="accent-crit-600" />
            <span>Clear key</span>
          </label>
          <button class="btn-primary" :disabled="saving.default" @click="saveDefault">
            {{ saving.default ? 'Saving' : 'Save Default' }}
          </button>
        </div>
      </div>
    </div>

    <div class="card overflow-x-auto">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm uppercase tracking-wider text-slate-200">Agents</h2>
        <span class="text-xs text-slate-500 font-mono">{{ new Date().toLocaleTimeString() }}</span>
      </div>
      <table class="w-full min-w-[1500px] text-xs">
        <thead class="text-[10px] text-slate-400 uppercase tracking-wider border-b border-ink-600">
          <tr>
            <th class="text-left py-2 pr-4">Agent</th>
            <th class="text-left pr-4">Service</th>
            <th class="text-left pr-4">Health</th>
            <th class="text-left pr-4">API Type</th>
            <th class="text-left pr-4">Base URL</th>
            <th class="text-left pr-4">Model</th>
            <th class="text-left pr-4">API Key</th>
            <th class="text-left pr-4">Run</th>
            <th class="text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="agent in overview.agents" :key="agent.name" class="border-b border-ink-700/50 align-top">
            <td class="py-3 pr-3">
              <div class="font-mono text-slate-100">{{ agent.name }}</div>
              <div class="text-slate-500 max-w-[220px]">{{ agent.role }}</div>
            </td>
            <td class="py-3 pr-3">
              <div class="font-mono text-slate-300">{{ agent.service }}</div>
              <div class="text-slate-500">{{ agent.health?.latency_ms ?? '-' }} ms</div>
            </td>
            <td class="py-3 pr-3">
              <span :class="statusClass(agent.status)">{{ agent.status }}</span>
              <div class="text-slate-500 mt-1">{{ agent.health?.status_code || '-' }}</div>
            </td>
            <td class="py-3 pr-3">
              <select v-model="agentForms[agent.name].provider" class="w-36 bg-ink-700 border border-ink-600 rounded-md px-2 py-1.5">
                <option v-for="option in providerOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
              <div class="text-slate-500 mt-1 font-mono">{{ agent.llm?.resolved_provider }}</div>
            </td>
            <td class="py-3 pr-3">
              <input v-model="agentForms[agent.name].base_url" class="w-64 bg-ink-700 border border-ink-600 rounded-md px-2 py-1.5 font-mono" placeholder="default" />
              <div class="text-slate-500 mt-1 font-mono truncate max-w-64" :title="agent.llm?.resolved_base_url">{{ agent.llm?.resolved_base_url || '-' }}</div>
            </td>
            <td class="py-3 pr-3">
              <input v-model="agentForms[agent.name].model" class="w-48 bg-ink-700 border border-ink-600 rounded-md px-2 py-1.5 font-mono" placeholder="tier default" />
              <div class="text-slate-500 mt-1 font-mono">{{ agent.llm?.resolved_model || '-' }}</div>
            </td>
            <td class="py-3 pr-3">
              <input v-model="agentForms[agent.name].api_key" type="password" class="w-44 bg-ink-700 border border-ink-600 rounded-md px-2 py-1.5 font-mono" :placeholder="agent.llm?.api_key_preview || 'unchanged'" />
              <div class="flex items-center gap-2 mt-1 text-slate-500">
                <span>{{ boolText(agent.llm?.resolved_api_key_set) }}</span>
                <label class="inline-flex items-center gap-1">
                  <input v-model="agentForms[agent.name].clear_api_key" type="checkbox" class="accent-crit-600" />
                  <span>clear</span>
                </label>
              </div>
            </td>
            <td class="py-3 pr-3">
              <label class="inline-flex items-center gap-2 text-slate-300">
                <input v-model="agentForms[agent.name].enabled" type="checkbox" class="accent-emerald-500" />
                <span>{{ agentForms[agent.name].enabled ? 'enabled' : 'off' }}</span>
              </label>
            </td>
            <td class="py-3 text-right">
              <button class="btn-primary py-1.5" :disabled="saving[agent.name]" @click="saveAgent(agent.name)">
                {{ saving[agent.name] ? 'Saving' : 'Save' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="card overflow-x-auto">
      <h2 class="text-sm uppercase tracking-wider text-slate-200 mb-3">Service Health</h2>
      <table class="w-full text-xs">
        <thead class="text-[10px] text-slate-400 uppercase tracking-wider border-b border-ink-600">
          <tr><th class="text-left py-2">Service</th><th class="text-left">Status</th><th class="text-right">HTTP</th><th class="text-right">ms</th><th class="text-left pl-4">Detail</th></tr>
        </thead>
        <tbody>
          <tr v-for="svc in overview.services" :key="svc.name" class="border-b border-ink-700/50">
            <td class="py-2 font-mono text-slate-100">{{ svc.name }}</td>
            <td><span :class="statusClass(svc.status)">{{ svc.status }}</span></td>
            <td class="text-right font-mono text-slate-300">{{ svc.status_code || '-' }}</td>
            <td class="text-right font-mono text-slate-300">{{ svc.latency_ms }}</td>
            <td class="pl-4 text-slate-500 truncate max-w-[520px]" :title="svc.detail">{{ svc.detail }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ============================================================
         Users: bcrypt-hashed, admin-managed credentials
         ============================================================ -->
    <div class="card space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-sm uppercase tracking-wider text-slate-200">Users</h2>
          <p class="text-xs text-slate-500 mt-1">
            Credentials are bcrypt-hashed and persisted on the agent-config
            volume. Bootstrap users from AUTH_*_USER / AUTH_*_PASS env vars
            still work until you add or override them here.
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button class="btn-secondary text-xs" @click="loadUsers">Refresh</button>
          <button class="btn-primary text-xs" @click="newUserForm">+ Add User</button>
        </div>
      </div>

      <p v-if="userError" class="text-xs text-red-400">{{ userError }}</p>
      <p v-if="userBanner" class="text-xs text-emerald-300">{{ userBanner }}</p>

      <table class="w-full text-xs">
        <thead class="text-[10px] text-slate-400 uppercase tracking-wider border-b border-ink-600">
          <tr>
            <th class="text-left py-2">Username</th>
            <th class="text-left">Role</th>
            <th class="text-left">Source</th>
            <th class="text-left">Updated</th>
            <th class="text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in storeUsers" :key="`store-${u.username}`" class="border-b border-ink-700/50">
            <td class="py-2 font-mono text-slate-100">{{ u.username }}</td>
            <td><span class="text-slate-300">{{ u.role }}</span></td>
            <td class="text-slate-500">store</td>
            <td class="text-slate-500 font-mono">{{ u.updated_at }}</td>
            <td class="text-right space-x-2">
              <button class="btn-secondary text-[10px]" @click="editUser(u)">Edit / Reset password</button>
              <button class="btn-secondary text-[10px]" @click="deleteUserConfirm(u.username)">Delete</button>
            </td>
          </tr>
          <tr v-for="u in envUsers" :key="`env-${u.username}`" class="border-b border-ink-700/50">
            <td class="py-2 font-mono text-slate-100">{{ u.username }}</td>
            <td><span class="text-slate-300">{{ u.role }}</span></td>
            <td class="text-amber-300">env (bootstrap)</td>
            <td class="text-slate-500">—</td>
            <td class="text-right">
              <button class="btn-secondary text-[10px]" @click="promoteEnvUser(u)">Move to store</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Form -->
      <div v-if="userForm" class="mt-4 border-t border-ink-700/60 pt-4 space-y-3">
        <h3 class="text-xs uppercase tracking-wider text-slate-300">
          {{ userForm.isNew ? 'Add user' : `Edit ${userForm.username}` }}
        </h3>
        <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label class="space-y-1">
            <span class="text-[10px] uppercase tracking-wider text-slate-400">Username</span>
            <input v-model="userForm.username" :disabled="!userForm.isNew"
              class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 font-mono disabled:opacity-50" />
          </label>
          <label class="space-y-1">
            <span class="text-[10px] uppercase tracking-wider text-slate-400">Role</span>
            <select v-model="userForm.role"
              class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2">
              <option v-for="r in ROLES" :key="r" :value="r">{{ r }}</option>
            </select>
          </label>
          <label class="space-y-1 md:col-span-2">
            <span class="text-[10px] uppercase tracking-wider text-slate-400">
              Password {{ userForm.isNew ? '(required)' : '(blank = keep existing)' }}
            </span>
            <input v-model="userForm.password" type="password"
              class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 font-mono" />
          </label>
        </div>
        <div class="flex items-center justify-end gap-2 text-sm">
          <button class="btn-secondary" @click="userForm = null">Cancel</button>
          <button class="btn-primary" :disabled="savingUser" @click="saveUser">
            {{ savingUser ? 'Saving' : 'Save' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
