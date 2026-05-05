import axios from 'axios'
import type { DeviceControlAction } from '../types'

export const api = axios.create({ baseURL: '/api/v1' })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('hvac_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('hvac_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

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
  control: (id: string, action: DeviceControlAction, step = 1) =>
    api.post(`/devices/${id}/control`, { action, step }).then(r => r.data),
  updatePosition: (id: string, x: number, y: number) => api.put(`/devices/${id}/position`, { position_x: x, position_y: y }),
  sync: (id: string) => api.post(`/devices/${id}/sync`),
  create: (data: object) => api.post('/devices', data),
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
