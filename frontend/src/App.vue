<script setup>
import Sidebar from './components/Sidebar.vue'
import Topbar from './components/Topbar.vue'
</script>

<template>
  <div class="flex h-screen w-screen overflow-hidden bg-ink-900">
    <Sidebar />
    <main class="flex-1 flex flex-col min-w-0">
      <Topbar />
      <div class="flex-1 overflow-y-auto p-6">
        <router-view />
      </div>
    </main>
  </div>
</template>
