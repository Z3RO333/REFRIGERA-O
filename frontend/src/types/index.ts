export type DeviceStatus = 'NORMAL' | 'ATENÇÃO' | 'CRÍTICO' | 'BAIXA_EFICIÊNCIA' | 'SEM_LEITURA' | 'DESLIGADO' | 'COMPRESSOR_CYCLING'
export type AlertSeverity = 'P1' | 'P2' | 'P3' | 'P4'
export type AlertStatus = 'OPEN' | 'ACK' | 'RESOLVED'
export type DeviceControlAction = 'power_on' | 'power_off' | 'temperature_up' | 'temperature_down'

export interface Device {
  id: string
  brise_id: string
  name: string
  sector_id: string | null
  sector_name: string | null
  store_id: string | null
  store_name: string | null
  btu: number
  position_x: number | null
  position_y: number | null
  is_critical_environment: boolean
  last_maintenance: string | null
  status: DeviceStatus
  temperature: number | null
  historical_avg?: number | null
  humidity: number | null
  delta_temp: number | null
  efficiency_score: number | null
  state: boolean | null
  setpoint_cool?: number
  updated_at: string | null
  parameters?: DeviceParameters
}

export interface DeviceParameters {
  mode_device: number
  mode_ac: number
  fan_speed: number
  setpoint_cool: number
  setpoint_heat: number
  eco_cool: number
  eco_heat: number
}

export interface Store {
  id: string
  name: string
  code: string
  city: string | null
  kind?: 'LOJA' | 'FARMA' | 'CD'
  device_count?: number
}

export interface Sector {
  id: string
  name: string
  floor: number
  floor_plan_url: string | null
  is_critical: boolean
}

export interface Alert {
  id: string
  device_id: string
  brise_id: string
  device_name: string | null
  store_name: string | null
  sector_name: string | null
  alert_type: string
  severity: AlertSeverity
  status: AlertStatus
  temperature_at_alert: number | null
  setpoint_at_alert: number | null
  delta_at_alert: number | null
  message: string | null
  opened_at: string
  acked_at: string | null
  acked_by: string | null
  resolved_at: string | null
}

export interface KPISummary {
  total_devices: number
  devices_normal: number
  devices_warning: number
  devices_critical: number
  devices_no_reading: number
  devices_low_efficiency: number
  devices_off: number
  devices_online: number
  alerts_p1_open: number
  alerts_p2_open: number
  avg_temperature: number | null
  avg_efficiency_score: number | null
  compliance_rate: number | null
}

export interface HistoryPoint {
  time: string
  temperature: number | null
  historical_avg?: number | null
  humidity: number | null
  status_classification: string | null
  delta_temp: number | null
  efficiency_score: number | null
  state: boolean | null
  consumption?: number | null
  consumption_estimated: number | null
  consumption_estimated_kw?: number | null
  estimated_kwh?: number | null
}

export interface HistoryStats {
  avg_temp: number | null
  max_temp: number | null
  min_temp: number | null
  avg_efficiency: number | null
  hours_critical: number
  hours_warning: number
  hours_normal: number
  avg_consumption_kw?: number | null
  peak_consumption_kw?: number | null
  total_kwh: number | null
  energy_price_per_kwh?: number | null
  energy_consumption_scale?: number | null
  estimated_cost?: number | null
}

export interface MaintenanceItem {
  rank: number
  device_id: string
  device_name: string
  store_name: string | null
  sector_name: string | null
  btu: number
  score: number
  status: DeviceStatus
  efficiency_score: number
  alerts_30d: number
  last_maintenance: string | null
  reasons: string[]
  recommended_action: string
}
