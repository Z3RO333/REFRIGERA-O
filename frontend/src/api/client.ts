import axios from 'axios'
import type { DeviceControlAction } from '../types'

export const api = axios.create({ baseURL: '/api/v1', withCredentials: true })

api.interceptors.response.use(
  r => r,
  err => {
    const url = err.config?.url ?? ''
    if (err.response?.status === 401 && !url.startsWith('/auth/')) {
      localStorage.removeItem('hvac_role')
      localStorage.removeItem('hvac_name')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export const authApi = {
  login: (email: string, password: string) => api.post('/auth/login', { email, password }).then(r => r.data),
  logout: () => api.post('/auth/logout').then(r => r.data),
  me: () => api.get('/auth/me').then(r => r.data),
  methods: () => api.get('/auth/methods').then(r => r.data),
}

export const kpiApi = {
  summary: (storeId?: string) => api.get('/kpis/summary', { params: storeId ? { store_id: storeId } : undefined }).then(r => r.data),
  store: (id: string) => api.get(`/kpis/stores/${id}`).then(r => r.data),
}

export const storesApi = {
  list: () => api.get('/stores').then(r => r.data),
  devices: (id: string) => api.get(`/stores/${id}/devices`).then(r => r.data.devices),
  sectors: (id: string) => api.get(`/stores/${id}/sectors`).then(r => r.data),
}

export const devicesApi = {
  get: (id: string) => api.get(`/devices/${id}`).then(r => r.data),
  search: (q: string) => api.get('/devices/search', { params: { q } }).then(r => r.data),
  status: (id: string) => api.get(`/devices/${id}/status`).then(r => r.data),
  updateParams: (id: string, params: object) => api.put(`/devices/${id}/parameters`, params),
  updateMetadata: (id: string, data: object) => api.patch(`/devices/${id}`, data).then(r => r.data),
  control: (id: string, action: DeviceControlAction, step = 1) =>
    api.post(`/devices/${id}/control`, { action, step }).then(r => r.data),
  updatePosition: (id: string, x: number | null, y: number | null) => api.put(`/devices/${id}/position`, { position_x: x, position_y: y }),
  refreshStatus: (id: string) => api.post(`/devices/${id}/refresh-status`).then(r => r.data),
  sync: (id: string) => api.post(`/devices/${id}/sync`),
  create: (data: object) => api.post('/devices', data),
  briseSchedules: (id: string) => api.get(`/devices/${id}/brise-schedules`).then(r => r.data),
}

export const alertsApi = {
  list: (params?: object) => api.get('/alerts', { params }).then(r => r.data),
  acknowledge: (id: string, notes?: string) => api.post(`/alerts/${id}/acknowledge`, { notes }),
  resolve: (id: string) => api.post(`/alerts/${id}/resolve`),
}

export const historyApi = {
  readings: (deviceId: string, hours = 24) => api.get(`/history/devices/${deviceId}`, { params: { hours } }).then(r => r.data),
  stats: (deviceId: string, hours = 24) => api.get(`/history/devices/${deviceId}/stats`, { params: { hours } }).then(r => r.data),
  consumption: (deviceId: string, hours = 24) => api.get(`/history/devices/${deviceId}/consumption`, { params: { hours } }).then(r => r.data),
  consumptionSummary: (hours = 24, limit = 10, storeId?: string) =>
    api.get('/history/consumption/summary', { params: { hours, limit, ...(storeId ? { store_id: storeId } : {}) } }).then(r => r.data),
}

export const maintenanceApi = {
  ranking: () => api.get('/maintenance/ranking').then(r => r.data.ranking),
}

export const zonesApi = {
  list: (storeId: string) => api.get(`/zones/${storeId}`).then(r => r.data),
  setMode: (storeId: string, zoneKey: string, data: {
    mode: string
    priority?: string
    blocked_reason?: string
    blocked_until?: string | null
    setpoint_min?: number
    setpoint_max?: number
  }) => api.put(`/zones/${storeId}/${zoneKey}/mode`, data).then(r => r.data),
  history: (storeId: string, zoneKey: string, limit = 20) =>
    api.get(`/zones/${storeId}/${zoneKey}/history`, { params: { limit } }).then(r => r.data),
  trigger: (storeId: string, zoneKey: string) =>
    api.post(`/zones/${storeId}/${zoneKey}/trigger`).then(r => r.data),
  aiView: (storeId: string, zoneKey: string) =>
    api.get(`/zones/${storeId}/${zoneKey}/ai-view`).then(r => r.data),
  updateGuardrails: (storeId: string, zoneKey: string, data: {
    allowed_start_time?: string
    allowed_end_time?: string
    allowed_end_next_day?: boolean
    is_critical_zone?: boolean
    allow_auto_power_off?: boolean
  }) => api.put(`/zones/${storeId}/${zoneKey}/guardrails`, data).then(r => r.data),
}

export const automationApi = {
  status: () => api.get('/automation/status').then(r => r.data),
  setKillSwitch: (active: boolean, by?: string) =>
    api.post('/automation/kill-switch', { active, by: by ?? 'operador' }).then(r => r.data),
}

export const digitalTwinApi = {
  store: (storeId: string) => api.get(`/digital-twin/stores/${storeId}`).then(r => r.data),
  zone:  (storeId: string, zoneKey: string) =>
    api.get(`/digital-twin/stores/${storeId}/zones/${zoneKey}`).then(r => r.data),
}

export const usersApi = {
  list: () => api.get('/users').then(r => r.data),
  updateRole: (id: string, role: string) => api.put(`/users/${id}/role`, { role }).then(r => r.data),
  toggleActive: (id: string, active: boolean) => api.put(`/users/${id}/active`, { active }).then(r => r.data),
}

export const auditApi = {
  list: (params?: {
    limit?: number
    offset?: number
    action_type?: string
    origin?: string
    severity?: string
    store_id?: string
    device_id?: string
    user_name?: string
  }) => api.get('/audit', { params }).then(r => r.data),
}

export const logsApi = {
  list: (params?: {
    limit?: number
    offset?: number
    store_id?: string
    zone_key?: string
    device_id?: string
    user_name?: string
    event_type?: string
    origin?: string
    severity?: string
    status?: string
    date_from?: string
    date_to?: string
  }) => api.get('/logs', { params }).then(r => r.data),
  kpis: (params?: { store_id?: string; zone_key?: string; date_from?: string; date_to?: string }) =>
    api.get('/logs/kpis', { params }).then(r => r.data),
}

interface ZoneGeometry {
  type: 'polygon' | 'rect'
  points: { x: number; y: number }[]
  unit: 'percent'
}

export const customZonesApi = {
  list: (storeId: string) => api.get(`/zones/${storeId}/custom`).then(r => r.data),
  create: (storeId: string, data: {
    name: string
    ideal_min?: number
    ideal_max?: number
    zone_type?: string
    device_ids?: string[]
    mode?: string
    geometry?: ZoneGeometry
    floor?: number
    color?: string
  }) => api.post(`/zones/${storeId}/custom`, data).then(r => r.data),
  update: (storeId: string, zoneKey: string, data: {
    name?: string
    ideal_min?: number
    ideal_max?: number
    zone_type?: string
    device_ids?: string[]
    geometry?: ZoneGeometry
    floor?: number
    color?: string
  }) => api.put(`/zones/${storeId}/custom/${zoneKey}`, data).then(r => r.data),
  delete: (storeId: string, zoneKey: string) =>
    api.delete(`/zones/${storeId}/custom/${zoneKey}`).then(r => r.data),
  restore: (storeId: string, zoneKey: string) =>
    api.post(`/zones/${storeId}/custom/${zoneKey}/restore`).then(r => r.data),
  suggestions: (storeId: string) =>
    api.get(`/zones/${storeId}/suggestions`).then(r => r.data),
}

export const diagnosticsApi = {
  store: (storeId: string) => api.get(`/diagnostics/stores/${storeId}`).then(r => r.data),
  device: (deviceId: string) => api.get(`/diagnostics/devices/${deviceId}`).then(r => r.data),
}

export const portfolioApi = {
  stores: () => api.get('/portfolio/stores').then(r => r.data),
  kpis: () => api.get('/portfolio/kpis').then(r => r.data),
}

export const aiApi = {
  status: () => api.get('/ai/status').then(r => r.data),
  analyses: () => api.get('/ai/analyses').then(r => r.data),
  trigger: () => api.post('/ai/trigger').then(r => r.data),
  zoneAnalyses: () => api.get('/ai/zone-analyses').then(r => r.data),
  analyzeZone: (storeId: string, zoneKey: string) =>
    api.post(`/ai/zones/${storeId}/${zoneKey}/analyze`).then(r => r.data),
  chatCommand: (message: string) => api.post('/ai/chat-command', { message }).then(r => r.data),
  chatCommandPrompt: () => api.get('/ai/chat-command/prompt').then(r => r.data),
}
