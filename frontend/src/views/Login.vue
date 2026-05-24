<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import axios from 'axios'
import { useAuth } from '../composables/auth'

const router = useRouter()
const route = useRoute()
const { setSession } = useAuth()

const username = ref('')
const password = ref('')
const submitting = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  if (!username.value || !password.value) {
    error.value = 'Username and password are required.'
    return
  }
  submitting.value = true
  try {
    // Use a fresh axios instance so the request interceptor (which
    // would otherwise attach a stale/missing token) stays out of it.
    const base = import.meta.env.VITE_API_BASE || '/api/v1'
    const r = await axios.post(`${base}/auth/login`, {
      username: username.value,
      password: password.value,
    })
    const { access_token, role, username: u } = r.data || {}
    if (!access_token) {
      error.value = 'Login response missing access_token.'
      return
    }
    // setSession writes to localStorage AND updates the reactive
    // auth state so App.vue immediately shows the sidebar/topbar.
    setSession({ token: access_token, username: u || username.value, role })
    const redirect = (route.query.redirect && String(route.query.redirect)) || '/'
    router.replace(redirect)
  } catch (e) {
    const detail = e?.response?.data?.detail
    if (e?.response?.status === 401) {
      error.value = detail || 'Invalid username or password.'
    } else if (e?.code === 'ERR_NETWORK') {
      error.value = 'Cannot reach api-gateway. Is the backend running?'
    } else {
      error.value = detail || e?.message || 'Login failed.'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="min-h-[80vh] flex items-center justify-center">
    <form @submit.prevent="submit" class="card w-full max-w-sm space-y-4">
      <div class="flex items-center gap-3">
        <div class="h-9 w-9 rounded-md bg-accent-700 flex items-center justify-center text-ink-900 font-bold">FM</div>
        <div>
          <h1 class="text-lg font-semibold text-slate-100">Sign in</h1>
          <p class="text-xs text-slate-400">ForgeMind AI control plane</p>
        </div>
      </div>

      <div class="space-y-1">
        <label class="block text-xs uppercase tracking-wider text-slate-400">Username</label>
        <input
          v-model="username"
          autocomplete="username"
          autofocus
          class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 text-sm font-mono text-slate-100 focus:outline-none focus:border-accent-500"
          placeholder="admin"
        />
      </div>

      <div class="space-y-1">
        <label class="block text-xs uppercase tracking-wider text-slate-400">Password</label>
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-2 text-sm font-mono text-slate-100 focus:outline-none focus:border-accent-500"
          placeholder="••••••••"
        />
      </div>

      <button
        type="submit"
        :disabled="submitting"
        class="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {{ submitting ? 'Signing in…' : 'Sign in' }}
      </button>

      <div v-if="error" class="text-sm text-red-400 bg-red-900/30 border border-red-800 rounded-md px-3 py-2">
        {{ error }}
      </div>

      <p class="text-xs text-slate-500 leading-relaxed">
        Use credentials from the Admin Panel, or the env-var bootstrap user (defaults to <span class="font-mono text-slate-300">admin</span>/<span class="font-mono text-slate-300">admin</span> for fresh installs).
      </p>
    </form>
  </div>
</template>
