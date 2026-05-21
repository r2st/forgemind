import { createRouter, createWebHistory } from 'vue-router'

const routes = [
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

export default createRouter({
  history: createWebHistory(),
  routes,
})
