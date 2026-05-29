export type DeviceStatus = 'NORMAL' | 'ATENÇÃO' | 'CRÍTICO' | 'BAIXA_EFICIÊNCIA' | 'SEM_LEITURA' | 'LEITURA_STALE' | 'AGUARDANDO_LEITURA' | 'DESLIGADO' | 'COMPRESSOR_CYCLING'
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
  consumption?: number | null
  consumption_estimated?: number | null
  consumption_estimated_kw?: number | null
  delta_temp: number | null
  efficiency_score: number | null
  state: boolean | null
  setpoint_cool?: number | null
  current_setpoint?: number | null
  setpoint_synced_at?: string | null
  setpoint_stale?: boolean
  setpoint_source?: string | null
  min_allowed_setpoint?: number | null
  max_allowed_setpoint?: number | null
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
  kind?: 'LOJA' | 'FARMA' | 'CD' | 'ESCRITORIO' | 'MATRIZ'
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
  devices_stale: number
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

export type ZoneMode = 'manual' | 'suggestion' | 'semi' | 'auto' | 'maintenance'
export type ZonePriority = 'conforto' | 'economia' | 'estabilidade' | 'manutencao' | 'critico'
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
  fan_speed_before: number | null
  fan_speed_after: number | null
  reason: string | null
  confidence: number | null
  mode: ZoneMode | null
  status: ZoneActionStatus
  block_reason: string | null
  attempt_count: number
  created_at: string
  verified_at: string | null
}

export interface ZoneRecoveryState {
  started_at: string
  reason: string
  current_min_setpoint: number
  ramp_state: 'active' | 'ramping' | 'completed'
  ramp_step_target: number
  comfort_streak: number
  last_evaluated_at: string
  remaining_seconds: number | null
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
  recovery_enabled: boolean
  recovery_min_setpoint: number
  recovery_target_setpoint: number
  recovery_max_duration_minutes: number
  recovery: ZoneRecoveryState | null
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
  priority: ZonePriority
  // manutenção
  blocked_reason: string | null
  blocked_until: string | null
  blocked_by_user_name: string | null
  blocked_at: string | null
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
  freshness_ratio: number
  fresh_device_count: number
  stale_device_count: number
  early_warning: boolean
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

// ── Logs & Rastreabilidade ─────────────────────────────────────────────────────

export type LogEventType =
  | 'temperature_change'
  | 'device_power'
  | 'mode_change'
  | 'ai_analysis'
  | 'ai_suggestion'
  | 'automation_exec'
  | 'guardrail_block'
  | 'kill_switch'
  | 'zone_trigger'
  | 'zone_guardrails_change'
  | 'alert_ack'
  | 'alert_resolve'

export type LogOrigin = 'user' | 'ai' | 'automation' | 'system'

export interface LogEntry {
  id: string
  source: 'audit' | 'automation'
  event_type: LogEventType
  origin: LogOrigin
  created_at: string
  store_id: string | null
  store_name: string | null
  zone_key: string | null
  zone_label: string | null
  sector_name: string | null
  device_id: string | null
  device_name: string | null
  user_name: string | null
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | null
  status: string | null
  summary: string
  old_value: string | null
  new_value: string | null
  details: Record<string, unknown>
}

export interface LogsPage {
  items: LogEntry[]
  total: number
  offset: number
  limit: number
}

export interface LogKPIs {
  ai_suggestions: number
  auto_executed: number
  verified_success: number
  verified_failure: number
  guardrail_blocks: number
  manual_controls: number
  ai_analyses: number
  ai_critical: number
  ai_high: number
  mode_changes: number
  kill_switches: number
  alert_acks: number
  alert_resolves: number
  avg_recovery_minutes: number | null
  top_zones: { zone_key: string; zone_label: string; count: number }[]
  top_devices: { device_id: string; device_name: string; count: number }[]
}

// ── Análise de IA ──────────────────────────────────────────────────────────────

export interface AIAnalysis {
  device_id: string
  device_name: string
  issue_detected: boolean
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | null
  root_cause: string
  diagnosis: string
  recommended_action: string
  urgency_hours: number
  email_worthy: boolean
  analysis_source: 'llm' | 'fallback' | 'deterministic'
  analyzed_at: string
  temperature: number | null
  setpoint_cool: number | null
  store_name: string | null
  sector_name: string | null
}

export interface AIStatus {
  ai_analysis_enabled: boolean
  ollama_url: string
  ollama_model: string
  ollama_available: boolean
  email_enabled: boolean
}

export type AISeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export interface ZoneAIAnalysis {
  zone_key: string
  zone_label: string
  store_id: string
  issue_detected: boolean
  severity: AISeverity | null
  root_cause: string
  diagnosis: string
  recommended_action: string
  urgency_hours: number
  analysis_source: 'llm' | 'fallback' | 'deterministic'
  devices_analyzed: number
  zone_status: string
  trend_c_per_hour: number | null
  analyzed_at: string
}

export interface ZoneGeometry {
  type: 'polygon' | 'rect'
  points: { x: number; y: number }[]  // coordenadas em % da planta
  unit: 'percent'
}

export interface CustomZone {
  id: string
  store_id: string
  zone_key: string
  name: string
  zone_type: ZoneType
  ideal_min: number
  ideal_max: number
  geometry: ZoneGeometry | null
  floor: number
  color: string | null
  created_by_name: string | null
  updated_by_name: string | null
  device_ids: string[]
  current_temp: number | null
  temp_status: string
  created_at: string
  is_custom: true
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
