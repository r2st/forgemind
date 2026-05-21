import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 60000,
})

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('fm_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

export default api

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
