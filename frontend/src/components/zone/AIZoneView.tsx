import { useQuery } from '@tanstack/react-query'
import { Brain, AlertTriangle, CheckCircle, XCircle, Activity, RefreshCw } from 'lucide-react'
import { zonesApi } from '../../api/client'
import { cn, formatTime } from '../../lib/utils'

interface AIDeviceView {
  device_id: string
  name: string
  btu: number | null
  status_classification: string | null
  is_on: boolean
  is_off: boolean
  temperature: number | null
  setpoint_cool: number | null
  fan_speed: number | null
  last_reading_at: string | null
  eligible_power_on: boolean
  eligible_setpoint_change: boolean
  excluded_reasons: string[]
}

interface AIZoneViewData {
  zone_key: string
  zone_label: string
  snapshot_at: string
  temperature: {
    avg: number | null
    ideal_min: number
    ideal_max: number
    thermal_status: string
    trend_c_per_hour: number | null
  }
  hotspot: { peak_temp: number; peak_device_name: string | null } | null
  automation: {
    mode: string
    setpoint_min: number
    setpoint_max: number
    allow_auto_power_off: boolean
    is_critical_zone: boolean
    recovery_enabled: boolean
    recovery_min_setpoint: number
    recovery_target_setpoint: number
    recovery_max_duration_minutes: number
  }
  recovery: {
    started_at: string
    reason: string
    current_min_setpoint: number
    ramp_state: string
    ramp_step_target: number
    comfort_streak: number
    last_evaluated_at: string
    remaining_seconds: number | null
  } | null
  devices_summary: {
    total: number
    on: number
    off: number
    eligible_power_on: number
    eligible_setpoint_change: number
  }
  devices: AIDeviceView[]
  recommended_action: { action: string; rationale: string }
  blockers: string[]
  source: string
}

const STATUS_COLORS: Record<string, string> = {
  COLD: 'text-blue-400',
  COMFORT: 'text-green-400',
  WARM: 'text-yellow-400',
  HOT: 'text-orange-400',
  CRITICAL: 'text-red-500',
  NO_READING: 'text-gray-400',
}

const ACTION_LABELS: Record<string, { label: string; color: string }> = {
  power_on: { label: 'Ligar AC', color: 'text-blue-400' },
  power_off: { label: 'Desligar AC', color: 'text-cyan-400' },
  setpoint_down: { label: 'Reduzir setpoint', color: 'text-orange-400' },
  setpoint_up: { label: 'Subir setpoint', color: 'text-yellow-400' },
  blocked: { label: 'Bloqueado', color: 'text-red-400' },
  wait: { label: 'Aguardar', color: 'text-gray-400' },
  none: { label: 'Sem ação', color: 'text-gray-400' },
}

export default function AIZoneView({
  storeId, zoneKey,
}: { storeId: string; zoneKey: string }) {
  const { data, isLoading, error } = useQuery<AIZoneViewData>({
    queryKey: ['ai-view', storeId, zoneKey],
    queryFn: () => zonesApi.aiView(storeId, zoneKey),
    refetchInterval: 30_000,
  })

  if (isLoading) return <div className="p-3 text-xs text-gray-400">Carregando visão da IA...</div>
  if (error || !data) return <div className="p-3 text-xs text-red-400">Erro ao carregar visão da IA.</div>

  const action = ACTION_LABELS[data.recommended_action.action] ?? ACTION_LABELS.none
  const recoveryMinutes = data.recovery?.remaining_seconds != null
    ? Math.max(0, Math.ceil(data.recovery.remaining_seconds / 60))
    : null

  return (
    <div className="space-y-3 rounded-lg border border-purple-500/30 bg-purple-950/20 p-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-purple-300">
        <Brain size={16} />
        Visão da IA sobre a zona
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <Info label="Temperatura média">
          {data.temperature.avg != null ? `${data.temperature.avg}°C` : '—'}
          {data.temperature.trend_c_per_hour != null && (
            <span className="ml-1 text-gray-400">
              ({data.temperature.trend_c_per_hour > 0 ? '+' : ''}{data.temperature.trend_c_per_hour}°C/h)
            </span>
          )}
        </Info>
        <Info label="Faixa ideal">{data.temperature.ideal_min}–{data.temperature.ideal_max}°C</Info>
        <Info label="Status térmico">
          <span className={cn('font-semibold', STATUS_COLORS[data.temperature.thermal_status])}>
            {data.temperature.thermal_status}
          </span>
        </Info>
        <Info label="Hotspot">
          {data.hotspot
            ? `${data.hotspot.peak_temp}°C ${data.hotspot.peak_device_name ? `(${data.hotspot.peak_device_name})` : ''}`
            : 'nenhum'}
        </Info>
        <Info label="Vinculados">{data.devices_summary.total}</Info>
        <Info label="Ligados / Desligados">{data.devices_summary.on} / {data.devices_summary.off}</Info>
        <Info label="Elegíveis power_on">{data.devices_summary.eligible_power_on}</Info>
        <Info label="Elegíveis setpoint">{data.devices_summary.eligible_setpoint_change}</Info>
      </div>

      <div className="rounded border border-purple-500/40 bg-black/30 p-2">
        <div className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-purple-300">
          <Activity size={12} /> Ação recomendada
        </div>
        <div className={cn('mt-1 text-sm font-semibold', action.color)}>{action.label}</div>
        <div className="mt-1 text-xs text-gray-300">{data.recommended_action.rationale}</div>
      </div>

      {data.recovery && (
        <div className="rounded border border-cyan-500/40 bg-cyan-950/30 p-2">
          <div className="flex items-center gap-1 text-[11px] uppercase text-cyan-300">
            <RefreshCw size={12} /> Modo Recuperação
          </div>
          <div className="mt-1 grid grid-cols-2 gap-2 text-xs">
            <Info label="Desde">{formatTime(data.recovery.started_at)}</Info>
            <Info label="Restante">{recoveryMinutes != null ? `${recoveryMinutes} min` : '—'}</Info>
            <Info label="Piso atual">{data.recovery.current_min_setpoint}°C</Info>
            <Info label="Ramp">{data.recovery.ramp_state}</Info>
            <Info label="Próximo SP">{data.recovery.ramp_step_target}°C</Info>
            <Info label="Comfort">{data.recovery.comfort_streak}/2 ciclos</Info>
          </div>
          <div className="mt-2 text-xs text-cyan-100">{data.recovery.reason}</div>
        </div>
      )}

      {data.blockers.length > 0 && (
        <div className="space-y-1 rounded border border-orange-500/40 bg-orange-950/30 p-2">
          <div className="flex items-center gap-1 text-[11px] uppercase text-orange-300">
            <AlertTriangle size={12} /> Bloqueios ativos
          </div>
          {data.blockers.map((b, i) => (
            <div key={i} className="text-xs text-orange-200">• {b}</div>
          ))}
        </div>
      )}

      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wide text-gray-400">Aparelhos considerados</div>
        <div className="space-y-1">
          {data.devices.map(d => (
            <div key={d.device_id} className="flex flex-col gap-0.5 rounded border border-gray-700/50 bg-black/20 p-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-200">{d.name}</span>
                <div className="flex items-center gap-1">
                  {d.eligible_power_on && (
                    <span className="rounded bg-blue-500/20 px-1.5 py-0.5 text-[10px] text-blue-300">
                      <CheckCircle size={10} className="inline mr-0.5" />power_on
                    </span>
                  )}
                  {d.eligible_setpoint_change && (
                    <span className="rounded bg-green-500/20 px-1.5 py-0.5 text-[10px] text-green-300">
                      <CheckCircle size={10} className="inline mr-0.5" />setpoint
                    </span>
                  )}
                  {d.excluded_reasons.length > 0 && (
                    <span className="rounded bg-red-500/20 px-1.5 py-0.5 text-[10px] text-red-300">
                      <XCircle size={10} className="inline mr-0.5" />ignorado
                    </span>
                  )}
                </div>
              </div>
              <div className="flex gap-3 text-[10px] text-gray-400">
                <span>{d.status_classification ?? '—'}</span>
                <span>{d.is_on ? 'ligado' : 'desligado'}</span>
                {d.temperature != null && <span>{d.temperature}°C</span>}
                {d.setpoint_cool != null && <span>SP {d.setpoint_cool}°C</span>}
                {d.fan_speed != null && <span>fan {d.fan_speed}</span>}
              </div>
              {d.excluded_reasons.length > 0 && (
                <div className="text-[10px] text-red-300">
                  Motivo: {d.excluded_reasons.join(' · ')}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="text-[10px] text-gray-500">
        Atualizado às {formatTime(data.snapshot_at)} · {data.source}
      </div>
    </div>
  )
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
      <div className="text-gray-200">{children}</div>
    </div>
  )
}
