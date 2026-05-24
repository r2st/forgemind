<script setup>
import { ref, computed } from 'vue'
import { useAuth } from '../composables/auth'
import { Auth } from '../composables/api'

const { user } = useAuth()
const username = computed(() => user.value?.username || '—')
const role = computed(() => user.value?.role || '—')

const tier = ref('powerful')
const apiKey = ref('')
const saved = ref(false)

function save() {
  localStorage.setItem('fm_tier', tier.value)
  if (apiKey.value) localStorage.setItem('fm_api_key', apiKey.value)
  saved.value = true
  setTimeout(() => { saved.value = false }, 2000)
}

// ----- Change password ----------------------------------------------
const pwOld = ref('')
const pwNew = ref('')
const pwConfirm = ref('')
const pwSubmitting = ref(false)
const pwError = ref('')
const pwSuccess = ref('')

async function changePassword() {
  pwError.value = ''
  pwSuccess.value = ''
  if (!pwOld.value || !pwNew.value || !pwConfirm.value) {
    pwError.value = 'All three fields are required.'
    return
  }
  if (pwNew.value.length < 8) {
    pwError.value = 'New password must be at least 8 characters.'
    return
  }
  if (pwNew.value !== pwConfirm.value) {
    pwError.value = 'New password and confirmation do not match.'
    return
  }
  if (pwNew.value === pwOld.value) {
    pwError.value = 'New password must differ from old password.'
    return
  }
  pwSubmitting.value = true
  try {
    const r = await Auth.changePassword(pwOld.value, pwNew.value)
    const msg = r?.source === 'env_promoted'
      ? 'Password changed. Your user has been migrated from the env-var bootstrap into the persistent store.'
      : 'Password changed.'
    pwSuccess.value = msg
    pwOld.value = ''
    pwNew.value = ''
    pwConfirm.value = ''
  } catch (e) {
    const detail = e?.response?.data?.detail
    if (e?.response?.status === 401) {
      pwError.value = detail || 'Old password is incorrect.'
    } else if (e?.response?.status === 400) {
      pwError.value = detail || 'Invalid request.'
    } else {
      pwError.value = detail || e?.message || 'Failed to change password.'
    }
  } finally {
    pwSubmitting.value = false
  }
}
</script>

<template>
  <div class="space-y-6 max-w-3xl">
    <h1 class="text-2xl font-semibold text-slate-100">Settings</h1>

    <div class="card space-y-3">
      <h2 class="text-sm uppercase tracking-wider text-slate-200">Identity</h2>
      <div class="text-sm text-slate-400">Logged in as <span class="text-slate-100 font-mono">{{ username }}</span> · role <span class="text-accent-500">{{ role }}</span></div>
    </div>

    <div class="card space-y-3">
      <h2 class="text-sm uppercase tracking-wider text-slate-200">Change Password</h2>
      <p class="text-xs text-slate-400 leading-relaxed">
        Change the password for <span class="font-mono text-slate-200">{{ username }}</span>.
        Minimum 8 characters. If you signed in via an env-var bootstrap user, your account will
        be migrated into the persistent store on first password change.
      </p>

      <form @submit.prevent="changePassword" class="space-y-3" autocomplete="off">
        <div class="space-y-1">
          <label class="block text-xs uppercase tracking-wider text-slate-400">Current password</label>
          <input
            v-model="pwOld"
            type="password"
            autocomplete="current-password"
            class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 text-sm font-mono text-slate-100 focus:outline-none focus:border-accent-500"
          />
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div class="space-y-1">
            <label class="block text-xs uppercase tracking-wider text-slate-400">New password</label>
            <input
              v-model="pwNew"
              type="password"
              autocomplete="new-password"
              class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 text-sm font-mono text-slate-100 focus:outline-none focus:border-accent-500"
            />
          </div>
          <div class="space-y-1">
            <label class="block text-xs uppercase tracking-wider text-slate-400">Confirm new password</label>
            <input
              v-model="pwConfirm"
              type="password"
              autocomplete="new-password"
              class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 text-sm font-mono text-slate-100 focus:outline-none focus:border-accent-500"
            />
          </div>
        </div>

        <button
          type="submit"
          :disabled="pwSubmitting"
          class="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ pwSubmitting ? 'Changing…' : 'Change password' }}
        </button>

        <div v-if="pwError" class="text-sm text-red-400 bg-red-900/30 border border-red-800 rounded-md px-3 py-2">
          {{ pwError }}
        </div>
        <div v-if="pwSuccess" class="text-sm text-emerald-300 bg-emerald-900/20 border border-emerald-800 rounded-md px-3 py-2">
          {{ pwSuccess }}
        </div>
      </form>
    </div>

    <div class="card space-y-3">
      <h2 class="text-sm uppercase tracking-wider text-slate-200">LLM Runtime</h2>
      <div class="text-sm text-slate-400">Default model tier for agent runs.</div>
      <select v-model="tier" class="bg-ink-700 border border-ink-600 rounded-md px-2 py-1 text-sm">
        <option value="fast">fast — cheap, high-volume (summaries, classification)</option>
        <option value="powerful">powerful — RCA, reasoning, executive reports</option>
        <option value="fallback">fallback — local Ollama backstop</option>
      </select>

      <label class="block text-sm text-slate-300 mt-3">Personal access token</label>
      <input v-model="apiKey" type="password" placeholder="Use Admin Panel for backend keys" class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-1 text-sm font-mono" />

      <button class="btn-primary mt-2" @click="save">Save</button>
      <span v-if="saved" class="ml-3 text-emerald-400 text-sm">Saved.</span>
    </div>

    <div class="card space-y-3">
      <h2 class="text-sm uppercase tracking-wider text-slate-200">About</h2>
      <div class="text-sm text-slate-300 leading-relaxed">
        ForgeMind AI v0.1.0 — autonomous manufacturing operations copilot.
        Built on Hermes Agent orchestration with configurable AI gateway providers.
      </div>
    </div>
  </div>
</template>
