import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../composables/auth'

const routes = [
  // Public — no auth required.
  { path: '/login',                  name: 'login',      component: () => import('../views/Login.vue'),
    meta: { public: true } },

  // Authenticated app.
  { path: '/',                       name: 'dashboard',  component: () => import('../views/Dashboard.vue') },
  { path: '/machines',               name: 'machines',   component: () => import('../views/MachineHealth.vue') },
  { path: '/incidents',              name: 'incidents',  component: () => import('../views/IncidentExplorer.vue') },
  { path: '/predictive-maintenance', name: 'pdm',        component: () => import('../views/PredictiveMaintenance.vue') },
  { path: '/production',             name: 'production', component: () => import('../views/ProductionAnalytics.vue') },
  { path: '/rca',                    name: 'rca',        component: () => import('../views/RCAReports.vue') },
  { path: '/chatops',                name: 'chatops',    component: () => import('../views/ChatOpsConsole.vue') },
  { path: '/executive',              name: 'executive',  component: () => import('../views/ExecutiveReports.vue') },
  { path: '/agents',                 name: 'agents',     component: () => import('../views/AgentActivity.vue') },
  { path: '/admin',                  name: 'admin',      component: () => import('../views/AdminPanel.vue') },
  { path: '/llm-admin',              name: 'llm-admin',  component: () => import('../views/LLMAdmin.vue') },
  { path: '/settings',               name: 'settings',   component: () => import('../views/Settings.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Global navigation guard. Routes default to authenticated;
// only routes marked `meta.public: true` are accessible without
// a bearer token. Unauthenticated requests are redirected to
// /login with the original path captured as ?redirect= so the
// user lands back where they started after sign-in.
router.beforeEach((to) => {
  const isPublic = to.matched.some((r) => r.meta?.public)
  const { isAuthenticated } = useAuth()
  const hasToken = isAuthenticated.value

  if (!isPublic && !hasToken) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  // If the user is already authenticated, don't let them sit on
  // /login — bounce them home (or to wherever ?redirect= says).
  if (to.name === 'login' && hasToken) {
    const redirect = (to.query.redirect && String(to.query.redirect)) || '/'
    return redirect
  }
})

export default router
