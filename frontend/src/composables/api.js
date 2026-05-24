import axios from 'axios'
import { useAuth } from './auth'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 60000,
})

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('fm_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// On 401 from the api-gateway, the token is missing or expired.
// Clear the session (reactive — App.vue and Topbar immediately
// flip to the signed-out state) and bounce the user to /login
// with a `redirect` query param so they land back where they
// were after re-authenticating.
//
// We use a hard navigation rather than vue-router here because
// importing the router from a composable creates a cycle; the
// hard nav also resets any half-loaded component state.
api.interceptors.response.use(
  (r) => r,
  (err) => {
    const status = err?.response?.status
    if (status === 401 || status === 403) {
      const path = window.location.pathname + window.location.search + window.location.hash
      // Don't loop if we're already on /login (e.g. the login POST itself failed).
      if (!window.location.pathname.startsWith('/login')) {
        const { clearSession } = useAuth()
        clearSession()
        const q = path && path !== '/' ? `?redirect=${encodeURIComponent(path)}` : ''
        window.location.replace(`/login${q}`)
      }
    }
    return Promise.reject(err)
  },
)

export default api

export const Auth = {
  // The login endpoint is special — it must NOT carry a stale
  // Authorization header from the interceptor, so callers should
  // use the bare axios instance (see Login.vue).
  me: () => api.get('/auth/me').then((r) => r.data),
  changePassword: (oldPassword, newPassword) =>
    api.post('/auth/change-password', { old_password: oldPassword, new_password: newPassword })
      .then((r) => r.data),
  logout: () => {
    const { clearSession } = useAuth()
    clearSession()
  },
}

export const Incidents = {
  list: (params) => api.get('/incidents', { params }).then((r) => r.data),
}
export const Machines = {
  list: () => api.get('/machines').then((r) => r.data),
  snapshot: () => api.get('/snapshot').then((r) => r.data),
  inject: (payload) => api.post('/inject', payload).then((r) => r.data),
  replayHistorical: () => api.post('/replay-historical', {}).then((r) => r.data),
}
export const Predictions = {
  list: () => api.get('/predictions').then((r) => r.data),
  explain: (machineId) => api.post(`/predictions/explain/${machineId}`).then((r) => r.data),
}
export const RCA = {
  list: () => api.get('/rca/reports').then((r) => r.data),
  get: (id) => api.get(`/rca/reports/${id}`).then((r) => r.data),
  run: (incidentId) => api.post('/rca/run', { incident_id: incidentId }).then((r) => r.data),
}
export const Agents = {
  list: () => api.get('/agents').then((r) => r.data),
  activity: (limit = 100) => api.get('/agents/activity', { params: { limit } }).then((r) => r.data),
  run: (task) => api.post('/agents/run', { task }).then((r) => r.data),
}
export const Chat = {
  send: (sessionId, message) =>
    api.post('/chat', { session_id: sessionId, message, stream: false }).then((r) => r.data),
}
export const Reports = {
  list: () => api.get('/reports', { params: {} }).then((r) => r.data),
  generate: (kind = 'shift') => api.post('/reports/generate', { kind }).then((r) => r.data),
}
export const Notifications = {
  recent: () => api.get('/notifications/recent').then((r) => r.data),
}
export const Workflows = {
  list: () => api.get('/workflows').then((r) => r.data),
  runs: (limit = 50) => api.get('/workflows/runs', { params: { limit } }).then((r) => r.data),
  run: (name, payload) => api.post(`/workflows/${name}/run`, payload).then((r) => r.data),
}
export const Admin = {
  overview: () => api.get('/admin/agents').then((r) => r.data),
  health: () => api.get('/admin/health').then((r) => r.data),
  updateDefault: (payload) => api.put('/admin/llm/default', payload).then((r) => r.data),
  updateAgent: (agentName, payload) =>
    api.put(`/admin/agents/${agentName}/config`, payload).then((r) => r.data),
}

// User credentials managed from the Admin Panel (bcrypt-hashed, persistent).
// Env-var bootstrap users are returned under env_users in the list response.
export const AuthUsers = {
  list: () => api.get('/admin/auth/users').then((r) => r.data),
  upsert: (username, payload) =>
    api.put(`/admin/auth/users/${encodeURIComponent(username)}`, payload).then((r) => r.data),
  remove: (username) =>
    api.delete(`/admin/auth/users/${encodeURIComponent(username)}`).then((r) => r.data),
}

export const LLMGateway = {
  // Providers
  providers: () => api.get('/admin/llm/providers').then((r) => r.data),
  createProvider: (payload) => api.post('/admin/llm/providers', payload).then((r) => r.data),
  updateProvider: (id, payload) => api.put(`/admin/llm/providers/${id}`, payload).then((r) => r.data),
  deleteProvider: (id) => api.delete(`/admin/llm/providers/${id}`).then((r) => r.data),

  // Models
  models: () => api.get('/admin/llm/models').then((r) => r.data),
  createModel: (payload) => api.post('/admin/llm/models', payload).then((r) => r.data),
  updateModel: (id, payload) => api.put(`/admin/llm/models/${id}`, payload).then((r) => r.data),
  deleteModel: (id) => api.delete(`/admin/llm/models/${id}`).then((r) => r.data),

  // Agent routing
  agentRouting: (agentName) => api.get(`/admin/llm/agents/${agentName}/routing`).then((r) => r.data),
  updateAgentRouting: (agentName, payload) => api.put(`/admin/llm/agents/${agentName}/routing`, payload).then((r) => r.data),

  // Agent fallback
  agentFallback: (agentName) => api.get(`/admin/llm/agents/${agentName}/fallback`).then((r) => r.data),
  updateAgentFallback: (agentName, payload) => api.put(`/admin/llm/agents/${agentName}/fallback`, payload).then((r) => r.data),

  // Analytics
  usage: (params) => api.get('/admin/llm/usage', { params }).then((r) => r.data),
  cost: (params) => api.get('/admin/llm/cost', { params }).then((r) => r.data),
  audit: (params) => api.get('/admin/llm/audit', { params }).then((r) => r.data),

  // Health
  health: () => api.get('/admin/llm/health').then((r) => r.data),
}
