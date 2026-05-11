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
  dnd?: boolean
  position_x: number | null
  position_y: number | null
  is_critical_environment: boolean
  is_external_sensor?: boolean
  influence_radius_m?: number
  source_url?: string | null
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
  kind?: 'LOJA' | 'FARMA' | 'CD' | 'ESCRITORIO'
  device_count?: number
  last_reading_at?: string | null
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

export type ZoneMode = 'manual' | 'suggestion' | 'semi' | 'auto'
export type ZoneType = 'ABERTA' | 'SALA_FECHADA'
export type ZoneActionStatus =
  | 'suggestion'
  | 'pending_verification'
  | 'executed'
  | 'blocked'
  | 'verified_success'
  | 'verified_failure'

export interface ZoneActionRecord {
  id: string
  zone_key: string
  zone_label: string | null
  device_id: string | null
  device_name: string | null
  direction: 'up' | 'down' | null
  temp_before: number | null
  temp_after: number | null
  ideal_min: number
  ideal_max: number
  setpoint_before: number | null
  setpoint_after: number | null
  reason: string | null
  confidence: number | null
  mode: ZoneMode | null
  status: ZoneActionStatus
  block_reason: string | null
  attempt_count: number
  created_at: string
  verified_at: string | null
}

export interface ZoneAutomationState {
  zone_key: string
  zone_label: string
  zone_type: ZoneType
  sector_names: string[]
  ideal_min: number
  ideal_max: number
  mode: ZoneMode
  setpoint_min: number
  setpoint_max: number
  max_daily_adjustments: number
  daily_count: number
  consecutive_failures: number
  cooldown_remaining_s: number | null
  last_action: ZoneActionRecord | null
  // guardrails
  allowed_start_hour: number
  allowed_start_minute: number
  allowed_end_hour: number
  allowed_end_minute: number
  is_critical_zone: boolean
  guardrail_active: boolean
  guardrail_reason: string | null
  reading_confidence: number
}

export interface AutomationStatus {
  kill_switch_active: boolean
  kill_switch_activated_at: string | null
  kill_switch_activated_by: string | null
  mode_counts: Record<string, number>
  executed_today: number
}

// ── Digital Twin ──────────────────────────────────────────────────────────────

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export interface DigitalTwinDevice {
  device_id: string
  brise_id: string
  name: string
  temperature: number | null
  status: string
  is_external_sensor: boolean
  efficiency_score: number | null
  updated_at: string | null
}

export interface DigitalTwinSimulation {
  action: 'no_action' | 'setpoint_down_1' | 'setpoint_up_1'
  label: string
  predicted_temp_30m: number | null
  predicted_temp_60m: number | null
  status_30m: string
  status_60m: string
  risk_after_30m: RiskLevel
  feasible: boolean
  block_reason: string | null
}

export interface DigitalTwinZone {
  store_id: string
  zone_key: string
  zone_label: string
  zone_type: ZoneType
  ideal_min: number
  ideal_max: number
  current_avg_temp: number | null
  current_status: DeviceStatus | 'COLD' | 'COMFORT' | 'WARM' | 'HOT' | 'CRITICAL' | 'NO_READING'
  trend_c_per_hour: number | null
  predicted_temp_15m: number | null
  predicted_temp_30m: number | null
  predicted_temp_60m: number | null
  risk_level: RiskLevel
  confidence: number
  contributing_devices: DigitalTwinDevice[]
  recommended_action: string
  explanation: string
  simulated_actions: DigitalTwinSimulation[]
  computed_at: string
}

export interface BriseSchedule {
  schedule_id: number
  name: string | null
  enable: boolean
  active_days: string[]
  start_time: string | null
  end_time: string | null
  repetition_mode: number | null
  setpoint_cool: number | null
  mode_ac: number | null
  fan_speed: number | null
  currently_active: boolean
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
