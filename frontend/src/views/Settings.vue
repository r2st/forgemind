<script setup>
import { ref } from 'vue'

const tier = ref('powerful')
const tfyKey = ref('')
const saved = ref(false)

function save() {
  localStorage.setItem('fm_tier', tier.value)
  if (tfyKey.value) localStorage.setItem('fm_tfy_key', tfyKey.value)
  saved.value = true
  setTimeout(() => { saved.value = false }, 2000)
}
</script>

<template>
  <div class="space-y-6 max-w-3xl">
    <h1 class="text-2xl font-semibold text-slate-100">Settings</h1>

    <div class="card space-y-3">
      <h2 class="text-sm uppercase tracking-wider text-slate-200">Identity</h2>
      <div class="text-sm text-slate-400">Logged in as <span class="text-slate-100 font-mono">admin</span> · role <span class="text-accent-500">admin</span></div>
    </div>

    <div class="card space-y-3">
      <h2 class="text-sm uppercase tracking-wider text-slate-200">TrueFoundry AI Gateway</h2>
      <div class="text-sm text-slate-400">Default model tier for agent runs. Overridden per-agent in code.</div>
      <select v-model="tier" class="bg-ink-700 border border-ink-600 rounded-md px-2 py-1 text-sm">
        <option value="fast">fast — cheap, high-volume (summaries, classification)</option>
        <option value="powerful">powerful — RCA, reasoning, executive reports</option>
        <option value="fallback">fallback — local Ollama backstop</option>
      </select>

      <label class="block text-sm text-slate-300 mt-3">Personal access token</label>
      <input v-model="tfyKey" type="password" placeholder="Stored locally only" class="w-full bg-ink-700 border border-ink-600 rounded-md px-2 py-1 text-sm font-mono" />

      <button class="btn-primary mt-2" @click="save">Save</button>
      <span v-if="saved" class="ml-3 text-emerald-400 text-sm">Saved.</span>
    </div>

    <div class="card space-y-3">
      <h2 class="text-sm uppercase tracking-wider text-slate-200">About</h2>
      <div class="text-sm text-slate-300 leading-relaxed">
        ForgeMind AI v0.1.0 — autonomous manufacturing operations copilot.
        Built on Hermes Agent (multi-agent orchestration) and TrueFoundry
        (AI Gateway, observability, autoscaling).
      </div>
    </div>
  </div>
</template>
