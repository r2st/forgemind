<script setup>
const nav = [
  { to: '/',                       label: 'Operations',          icon: '◆' },
  { to: '/machines',               label: 'Machine Health',      icon: '⚙' },
  { to: '/incidents',              label: 'Incident Explorer',   icon: '⚠' },
  { to: '/predictive-maintenance', label: 'Predictive Maint.',   icon: '⏱' },
  { to: '/production',             label: 'Production',          icon: '▤' },
  { to: '/rca',                    label: 'AI RCA Reports',      icon: '∴' },
  { to: '/chatops',                label: 'ChatOps Console',     icon: '✎' },
  { to: '/executive',              label: 'Executive Reports',   icon: '∎' },
  { to: '/agents',                 label: 'AI Agent Activity',   icon: '☉' },
  { to: '/admin',                  label: 'Admin Panel',         icon: '◉' },
  { to: '/llm-admin',              label: 'LLM Gateway',         icon: '⌬' },
  { to: '/settings',               label: 'Settings',            icon: '✱' },
]
</script>

<template>
  <aside class="w-60 shrink-0 bg-ink-800 border-r border-ink-600 flex flex-col">
    <div class="px-5 py-5 border-b border-ink-600">
      <div class="text-accent-500 text-xl font-bold tracking-tight">ForgeMind AI</div>
      <div class="text-[10px] text-slate-400 uppercase tracking-widest">
        Autonomous MFG Copilot
      </div>
    </div>

    <nav class="flex-1 px-2 py-3 space-y-0.5 text-sm">
      <router-link
        v-for="item in nav"
        :key="item.to"
        :to="item.to"
        class="flex items-center gap-2.5 px-3 py-2 rounded-md text-slate-300 hover:bg-ink-700 hover:text-white"
        active-class="bg-ink-700 text-accent-500 font-medium"
        :exact-active-class="item.to === '/' ? 'bg-ink-700 text-accent-500 font-medium' : ''"
      >
        <span class="w-4 text-center text-accent-500 opacity-80">{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="px-3 py-3 border-t border-ink-600">
      <div class="card-tight text-[11px] text-slate-400 leading-relaxed">
        <div class="text-accent-500 font-semibold mb-0.5">Hermes Runtime</div>
        <div>Multi-agent orchestration on configurable AI infra.</div>
      </div>
    </div>
  </aside>
</template>
