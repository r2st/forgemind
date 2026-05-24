<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './components/Sidebar.vue'
import Topbar from './components/Topbar.vue'
import { useAuth } from './composables/auth'

const route = useRoute()
const { isAuthenticated } = useAuth()

// Show the app chrome (sidebar + topbar) only when the user is
// signed in AND the current route is not marked public. Public
// routes (the login page) render in a minimal full-screen layout
// without any nav, so unauthenticated users can't see protected
// menu items.
const showChrome = computed(() => isAuthenticated.value && !route.meta?.public)
</script>

<template>
  <!-- Authenticated layout: sidebar + topbar + content -->
  <div v-if="showChrome" class="flex h-screen w-screen overflow-hidden bg-ink-900">
    <Sidebar />
    <main class="flex-1 flex flex-col min-w-0">
      <Topbar />
      <div class="flex-1 overflow-y-auto p-6">
        <router-view />
      </div>
    </main>
  </div>

  <!-- Public / unauthenticated layout: bare full-screen view (login). -->
  <div v-else class="h-screen w-screen overflow-hidden bg-ink-900">
    <div class="h-full w-full overflow-y-auto">
      <router-view />
    </div>
  </div>
</template>
