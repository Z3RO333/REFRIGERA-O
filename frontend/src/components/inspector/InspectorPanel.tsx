import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  X, Building2, Wind, Monitor, Thermometer, Zap,
  Clock, AlertTriangle, CheckCircle, Shield, ExternalLink,
  Activity, Droplets,
} from 'lucide-react'
import { useInspectorStore } from '../../store/useInspectorStore'
import { digitalTwinApi, kpiApi, devicesApi, alertsApi, zonesApi } from '../../api/client'
import { cn } from '../../lib/utils'

const RISK_STYLE: Record<string, string> = {
  CRITICAL: 'text-red-400 bg-red-900/30 border-red-800',
  HIGH: 'text-orange-400 bg-orange-900/30 border-orange-800',
  MEDIUM: 'text-yellow-400 bg-yellow-900/30 border-yellow-800',
  LOW: 'text-green-400 bg-green-900/30 border-green-800',
}

const STATUS_STYLE: Record<string, string> = {
  CRITICAL: 'text-red-400',
  HOT: 'text-orange-400',
  WARM: 'text-yellow-400',
  COMFORT: 'text-green-400',
  COLD: 'text-blue-400',
  NO_READING: 'text-gray-500',
}

const MODE_LABEL: Record<string, string> = {
  auto: 'Auto',
  semi: 'Semi-auto',
  suggestion: 'Sugestão',
  manual: 'Manual',
  maintenance: 'Manutenção',
}

function FreshnessBar({ ratio }: { ratio: number }) {
  const pct = Math.round(ratio * 100)
  const color = pct >= 80 ? 'bg-green-500' : pct >= 60 ? 'bg-yellow-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400 w-8 text-right">{pct}%</span>
    </div>
  )
}

function Row({ label, value, className }: { label: string; value: React.ReactNode; className?: string }) {
  return (
    <div className="flex items-start justify-between gap-2 py-1.5 border-b border-gray-800/60 last:border-0">
      <span className="text-xs text-gray-500 shrink-0">{label}</span>
      <span className={cn('text-xs text-right', className ?? 'text-gray-200')}>{value}</span>
    </div>
  )
}

// ── Zone inspector ─────────────────────────────────────────────────────────────
function ZoneInspector({ storeId, zoneKey, zoneName }: { storeId: string; zoneKey: string; zoneName: string }) {
  const navigate = useNavigate()
  const { data: twin } = useQuery({
    queryKey: ['inspector-zone', storeId, zoneKey],
    queryFn: () => digitalTwinApi.zone(storeId, zoneKey),
    refetchInterval: 30_000,
  })
  const { data: automation } = useQuery({
    queryKey: ['inspector-zone-auto', storeId, zoneKey],
    queryFn: () => zonesApi.list(storeId).then((list: any[]) => list.find((z: any) => z.zone_key === zoneKey)),
    refetchInterval: 30_000,
  })

  const status = twin?.current_status ?? 'NO_READING'
  const temp = twin?.current_avg_temp
  const freshness = twin?.freshness_ratio ?? 1
  const fresh = twin?.fresh_device_count ?? 0
  const stale = twin?.stale_device_count ?? 0

  return (
    <div className="space-y-4">
      {/* Header status */}
      <div className="flex items-center gap-2 p-3 bg-gray-800/60 rounded-lg">
        <Wind className="w-4 h-4 text-blue-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className={cn('text-sm font-semibold', STATUS_STYLE[status] ?? 'text-gray-300')}>{status}</div>
          {temp != null && (
            <div className="text-lg font-bold text-white">{temp.toFixed(1)}°C</div>
          )}
        </div>
        {twin?.risk_level && (
          <span className={cn('text-xs px-2 py-0.5 rounded border', RISK_STYLE[twin.risk_level])}>
            {twin.risk_level}
          </span>
        )}
      </div>

      {/* Confiança */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-500">Confiança dos dados</span>
          <span className="text-xs text-gray-400">{fresh} frescos / {stale} obsoletos</span>
        </div>
        <FreshnessBar ratio={freshness} />
        {freshness < 0.6 && (
          <p className="text-xs text-yellow-500 mt-1">Dados insuficientemente frescos — automação bloqueada</p>
        )}
      </div>

      {/* Dados */}
      <div>
        {twin?.ideal_min != null && (
          <Row label="Faixa ideal" value={`${twin.ideal_min}–${twin.ideal_max}°C`} />
        )}
        {twin?.trend_c_per_hour != null && (
          <Row
            label="Tendência"
            value={`${twin.trend_c_per_hour > 0 ? '+' : ''}${twin.trend_c_per_hour.toFixed(1)}°C/h`}
            className={twin.trend_c_per_hour > 1.5 ? 'text-orange-400' : 'text-gray-200'}
          />
        )}
        {twin?.predicted_temp_30m != null && (
          <Row label="Previsão 30 min" value={`${twin.predicted_temp_30m.toFixed(1)}°C`} />
        )}
        {automation && (
          <Row label="Modo" value={MODE_LABEL[automation.mode] ?? automation.mode} />
        )}
        {automation && (
          <Row label="Setpoint" value={`${automation.setpoint_min}–${automation.setpoint_max}°C`} />
        )}
      </div>

      {/* Última acção */}
      {automation?.last_action && (
        <div className="p-2 bg-gray-800/40 rounded text-xs text-gray-400 leading-relaxed">
          <div className="flex items-center gap-1 mb-1 text-gray-300">
            <Activity className="w-3 h-3" />
            <span>Última decisão IA</span>
          </div>
          <div>{automation.last_action.reason?.slice(0, 120)}{(automation.last_action.reason?.length ?? 0) > 120 ? '…' : ''}</div>
        </div>
      )}

      {/* Acções */}
      <div className="flex flex-col gap-1.5">
        <button
          onClick={() => navigate(`/mapa-termico/${storeId}`)}
          className="flex items-center justify-center gap-1.5 w-full py-1.5 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
        >
          <ExternalLink className="w-3 h-3" />
          Ver mapa térmico
        </button>
        <button
          onClick={() => navigate(`/ambientes`)}
          className="flex items-center justify-center gap-1.5 w-full py-1.5 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-200 transition-colors"
        >
          Alterar automação
        </button>
      </div>
    </div>
  )
}

// ── Device inspector ───────────────────────────────────────────────────────────
function DeviceInspector({ deviceId, deviceName }: { deviceId: string; deviceName: string }) {
  const navigate = useNavigate()
  const { data: device } = useQuery({
    queryKey: ['inspector-device', deviceId],
    queryFn: () => devicesApi.get(deviceId),
    refetchInterval: 30_000,
  })
  const { data: alerts = [] } = useQuery<any[]>({
    queryKey: ['inspector-device-alerts', deviceId],
    queryFn: () => alertsApi.list({ device_id: deviceId, status: 'OPEN', limit: 3 }).then((r: any) => r?.alerts ?? r ?? []),
    refetchInterval: 30_000,
  })

  const s = device?.status
  const p = device?.parameters

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2 p-3 bg-gray-800/60 rounded-lg">
        <Monitor className="w-4 h-4 text-blue-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-gray-200 truncate">{device?.name ?? deviceName}</div>
          <div className="text-xs text-gray-500">{device?.sector_name ?? ''}</div>
        </div>
        {s && (
          <span className={cn(
            'text-xs px-2 py-0.5 rounded border',
            s.state ? 'text-green-400 bg-green-900/30 border-green-800' : 'text-gray-500 bg-gray-800 border-gray-700'
          )}>
            {s.state ? 'ON' : 'OFF'}
          </span>
        )}
      </div>

      {/* Leitura */}
      {s?.temperature != null && (
        <div className="grid grid-cols-2 gap-2">
          <div className="p-2 bg-gray-800/40 rounded text-center">
            <div className="flex items-center justify-center gap-1 text-xs text-gray-500 mb-0.5">
              <Thermometer className="w-3 h-3" />Temp
            </div>
            <div className="text-lg font-bold text-white">{s.temperature.toFixed(1)}°C</div>
          </div>
          {p?.setpoint_cool != null && (
            <div className="p-2 bg-gray-800/40 rounded text-center">
              <div className="text-xs text-gray-500 mb-0.5">Setpoint</div>
              <div className="text-lg font-bold text-blue-300">{p.setpoint_cool}°C</div>
            </div>
          )}
        </div>
      )}

      {/* Dados */}
      <div>
        {s?.status_classification && (
          <Row label="Status" value={s.status_classification} />
        )}
        {s?.delta_temp != null && (
          <Row
            label="Delta"
            value={`${s.delta_temp > 0 ? '+' : ''}${s.delta_temp.toFixed(1)}°C`}
            className={s.delta_temp > 2 ? 'text-orange-400' : 'text-gray-200'}
          />
        )}
        {s?.efficiency_score != null && (
          <Row label="Eficiência" value={`${(s.efficiency_score * 100).toFixed(0)}%`} />
        )}
        {s?.updated_at && (
          <Row label="Última leitura" value={new Date(s.updated_at).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })} />
        )}
        {device?.btu && (
          <Row label="BTU" value={device.btu.toLocaleString()} />
        )}
      </div>

      {/* Alertas abertos */}
      {alerts?.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 mb-1.5">Alertas abertos</div>
          {alerts.map((a: any) => (
            <div key={a.id} className="flex items-start gap-2 p-2 bg-gray-800/40 rounded mb-1 text-xs">
              <AlertTriangle className={cn('w-3 h-3 mt-0.5 shrink-0', a.severity === 'P1' ? 'text-red-400' : 'text-orange-400')} />
              <span className="text-gray-300 leading-relaxed">{a.message?.slice(0, 80)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Acções */}
      <div className="flex flex-col gap-1.5">
        <button
          onClick={() => navigate(`/devices/${deviceId}`)}
          className="flex items-center justify-center gap-1.5 w-full py-1.5 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
        >
          <ExternalLink className="w-3 h-3" />
          Abrir painel do equipamento
        </button>
        <button
          onClick={() => navigate(`/history/${deviceId}`)}
          className="flex items-center justify-center gap-1.5 w-full py-1.5 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-200 transition-colors"
        >
          Ver histórico
        </button>
      </div>
    </div>
  )
}

// ── Store inspector ────────────────────────────────────────────────────────────
function StoreInspector({ storeId, storeName }: { storeId: string; storeName: string }) {
  const navigate = useNavigate()
  const { data: kpi } = useQuery({
    queryKey: ['inspector-store-kpi', storeId],
    queryFn: () => kpiApi.store(storeId),
    refetchInterval: 30_000,
  })
  const { data: alerts = [] } = useQuery<any[]>({
    queryKey: ['inspector-store-alerts', storeId],
    queryFn: () => alertsApi.list({ store_id: storeId, status: 'OPEN', limit: 5 }).then((r: any) => r?.alerts ?? r ?? []),
    refetchInterval: 30_000,
  })

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2 p-3 bg-gray-800/60 rounded-lg">
        <Building2 className="w-4 h-4 text-blue-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-gray-200 truncate">{storeName}</div>
          {kpi && (
            <div className="text-xs text-gray-500">
              {kpi.devices_online ?? 0}/{kpi.total_devices ?? 0} online
            </div>
          )}
        </div>
      </div>

      {/* KPIs */}
      {kpi && (
        <div className="grid grid-cols-2 gap-2">
          {[
            { label: 'Normal', value: kpi.devices_normal ?? 0, color: 'text-green-400' },
            { label: 'Atenção', value: (kpi.devices_warning ?? 0) + (kpi.devices_critical ?? 0), color: 'text-orange-400' },
            { label: 'Alertas P1', value: kpi.alerts_p1_open ?? 0, color: 'text-red-400' },
            { label: 'Alertas P2', value: kpi.alerts_p2_open ?? 0, color: 'text-orange-400' },
          ].map(item => (
            <div key={item.label} className="p-2 bg-gray-800/40 rounded text-center">
              <div className="text-xs text-gray-500 mb-0.5">{item.label}</div>
              <div className={cn('text-lg font-bold', item.color)}>{item.value}</div>
            </div>
          ))}
        </div>
      )}

      {kpi?.avg_temperature != null && (
        <Row label="Temp. média" value={`${Number(kpi.avg_temperature).toFixed(1)}°C`} />
      )}
      {kpi?.compliance_rate != null && (
        <Row label="Conformidade" value={`${(kpi.compliance_rate * 100).toFixed(0)}%`} />
      )}

      {/* Alertas */}
      {alerts?.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 mb-1.5">Alertas abertos</div>
          {alerts.map((a: any) => (
            <div key={a.id} className="flex items-start gap-2 p-2 bg-gray-800/40 rounded mb-1 text-xs">
              <AlertTriangle className={cn('w-3 h-3 mt-0.5 shrink-0', a.severity === 'P1' ? 'text-red-400' : 'text-orange-400')} />
              <div className="min-w-0">
                <div className="text-gray-300 truncate">{a.device_name}</div>
                <div className="text-gray-500 leading-relaxed">{a.message?.slice(0, 60)}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Acções */}
      <div className="flex flex-col gap-1.5">
        <button
          onClick={() => navigate(`/mapa-termico/${storeId}`)}
          className="flex items-center justify-center gap-1.5 w-full py-1.5 text-xs rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
        >
          <ExternalLink className="w-3 h-3" />
          Mapa térmico
        </button>
        <button
          onClick={() => navigate(`/lojas/${storeId}`)}
          className="flex items-center justify-center gap-1.5 w-full py-1.5 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-200 transition-colors"
        >
          Ver loja
        </button>
      </div>
    </div>
  )
}

// ── Painel principal ───────────────────────────────────────────────────────────
export default function InspectorPanel() {
  const { target, open, close } = useInspectorStore()

  const title =
    target?.type === 'zone' ? target.zoneName
    : target?.type === 'device' ? target.deviceName
    : target?.type === 'store' ? target.storeName
    : ''

  const icon =
    target?.type === 'zone' ? <Wind className="w-4 h-4 text-blue-400" />
    : target?.type === 'device' ? <Monitor className="w-4 h-4 text-blue-400" />
    : <Building2 className="w-4 h-4 text-blue-400" />

  return (
    <aside
      className={cn(
        'fixed top-0 right-0 h-full w-80 bg-gray-900 border-l border-gray-800 z-40 flex flex-col shadow-2xl transition-transform duration-300 ease-in-out',
        open ? 'translate-x-0' : 'translate-x-full'
      )}
    >
      {/* Cabeçalho */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-800 shrink-0">
        {icon}
        <span className="flex-1 text-sm font-semibold text-gray-100 truncate">{title}</span>
        <button onClick={close} className="p-1 rounded hover:bg-gray-800 text-gray-400 hover:text-gray-200 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Conteúdo */}
      <div className="flex-1 overflow-y-auto p-4">
        {target?.type === 'zone' && (
          <ZoneInspector storeId={target.storeId} zoneKey={target.zoneKey} zoneName={target.zoneName} />
        )}
        {target?.type === 'device' && (
          <DeviceInspector deviceId={target.deviceId} deviceName={target.deviceName} />
        )}
        {target?.type === 'store' && (
          <StoreInspector storeId={target.storeId} storeName={target.storeName} />
        )}
      </div>
    </aside>
  )
}
