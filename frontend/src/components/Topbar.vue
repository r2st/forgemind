<script setup>
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Notifications, Machines } from '../composables/api'
import { useAuth } from '../composables/auth'

const router = useRouter()
const { user, isAuthenticated, clearSession } = useAuth()

const notifCount = ref(0)
const onlineMachines = ref(0)
const totalMachines = ref(0)
const lastSync = ref(new Date())

const username = computed(() => user.value?.username || '—')
const role = computed(() => user.value?.role || '')
const initials = computed(() => (user.value?.username
  ? user.value.username.slice(0, 2).toUpperCase()
  : 'FM'))

function logout() {
  clearSession()
  // Hard-clear the polled values so the next viewer doesn't see
  // stale numbers if they sign in as a different user.
  notifCount.value = 0
  onlineMachines.value = 0
  totalMachines.value = 0
  router.push({ name: 'login' })
}

let timer = null

async function tick() {
  // Skip polling when nobody's signed in — the api-gateway will
  // 401 on every request and the response interceptor would
  // bounce us to /login in a loop.
  if (!isAuthenticated.value) return
  try {
    const notifs = await Notifications.recent()
    notifCount.value = notifs.length
  } catch {}
  try {
    const m = await Machines.list()
    totalMachines.value = m.length
    onlineMachines.value = m.filter((x) => x.state !== 'DOWN').length
  } catch {}
  lastSync.value = new Date()
}

// React to login/logout — start polling on sign-in, stop on
// sign-out. (Without this, the interval would keep firing tick()
// which now no-ops, but we still want fresh data immediately
// after sign-in.)
watch(isAuthenticated, (v) => {
  if (v) tick()
})

onMounted(() => {
  tick()
  timer = setInterval(tick, 10000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <header class="h-14 shrink-0 flex items-center justify-between px-6 border-b border-ink-600 bg-ink-800/80 backdrop-blur">
    <div class="flex items-center gap-3">
      <span class="inline-flex h-2 w-2 rounded-full bg-accent-500 animate-pulse"></span>
      <span class="text-sm text-slate-300 font-medium">plant-01 / line-A · line-B · line-C</span>
    </div>

    <div class="flex items-center gap-5 text-xs text-slate-400">
      <div>
        <span class="text-slate-500">Machines </span>
        <span class="font-mono text-slate-100">{{ onlineMachines }}/{{ totalMachines }}</span>
      </div>
      <div>
        <span class="text-slate-500">Alerts </span>
        <span class="font-mono text-warn-500">{{ notifCount }}</span>
      </div>
      <div>
        <span class="text-slate-500">Synced </span>
        <span class="font-mono">{{ lastSync.toLocaleTimeString() }}</span>
      </div>
      <div class="h-6 w-px bg-ink-600"></div>
      <div v-if="isAuthenticated" class="flex items-center gap-2">
        <div class="h-7 w-7 rounded-full bg-accent-700 flex items-center justify-center text-ink-900 font-semibold text-xs">{{ initials }}</div>
        <span>{{ username }}<span v-if="role" class="text-slate-500"> · </span><span v-if="role" class="text-slate-400">{{ role }}</span></span>
        <button
          @click="logout"
          class="ml-2 text-slate-500 hover:text-slate-200 underline-offset-2 hover:underline"
          title="Sign out"
        >sign out</button>
      </div>
      <div v-else>
        <router-link to="/login" class="text-slate-300 hover:text-slate-100">Sign in</router-link>
      </div>
    </div>
  </header>
</template>
