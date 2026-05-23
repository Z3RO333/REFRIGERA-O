import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle, Clock, RefreshCw, WifiOff, Zap, Activity, XCircle } from 'lucide-react'
import { diagnosticsApi, storesApi } from '../api/client'
import { cn, formatRelativeTime } from '../lib/utils'
import type { Store } from '../types'

const HEALTH_META: Record<string, { label: string; icon: React.ReactNode; cls: string; bg: string }> = {
  OK:             { label: 'Online',           icon: <CheckCircle className="h-4 w-4" />,   cls: 'text-green-500',  bg: 'bg-green-500/10 border-green-500/30' },
  DADO_ATRASADO:  { label: 'Dado atrasado',    icon: <Clock className="h-4 w-4" />,         cls: 'text-yellow-500', bg: 'bg-yellow-500/10 border-yellow-500/30' },
  SEM_LEITURA:    { label: 'Sem leitura',      icon: <AlertTriangle className="h-4 w-4" />, cls: 'text-orange-500', bg: 'bg-orange-500/10 border-orange-500/30' },
  SEM_TEMPERATURA:{ label: 'Sem temperatura',  icon: <AlertTriangle className="h-4 w-4" />, cls: 'text-orange-500', bg: 'bg-orange-500/10 border-orange-500/30' },
  OFFLINE:        { label: 'Offline',          icon: <WifiOff className="h-4 w-4" />,       cls: 'text-red-500',    bg: 'bg-red-500/10 border-red-500/30' },
  FALHA_API:      { label: 'Falha na API',     icon: <XCircle className="h-4 w-4" />,       cls: 'text-red-500',    bg: 'bg-red-500/10 border-red-500/30' },
  DESLIGADO:      { label: 'Desligado',        icon: <Zap className="h-4 w-4" />,           cls: 'text-gray-400',   bg: 'bg-gray-500/10 border-gray-500/30' },
  NUNCA_LIDO:     { label: 'Nunca lido',       icon: <XCircle className="h-4 w-4" />,       cls: 'text-red-500',    bg: 'bg-red-500/10 border-red-500/30' },
}

const OVERALL_META: Record<string, { label: string; cls: string }> = {
  OK:        { label: 'Saudável',  cls: 'text-green-500' },
  PARCIAL:   { label: 'Parcial',   cls: 'text-yellow-500' },
  DEGRADADO: { label: 'Degradado', cls: 'text-orange-500' },
  CRÍTICO:   { label: 'Crítico',   cls: 'text-red-500' },
}

function HealthBadge({ health }: { health: string }) {
  const m = HEALTH_META[health] ?? HEALTH_META.SEM_LEITURA
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium', m.bg, m.cls)}>
      {m.icon} {m.label}
    </span>
  )
}

function DeviceRow({ d }: { d: any }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={cn('rounded-lg border p-3 text-sm', d.health === 'OK' ? 'border-gray-200 dark:border-gray-800' : 'border-orange-500/30 bg-orange-500/5 dark:border-orange-800/50')}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-900 dark:text-white truncate">{d.name}</span>
            <span className="font-mono text-xs text-gray-400">{d.brise_id}</span>
            {d.is_external_sensor && <span className="rounded bg-amber-100 px-1 text-[10px] text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">sensor</span>}
          </div>
          <p className="mt-0.5 text-xs text-gray-500">{d.reason}</p>
          {d.last_error && (
            <p className="mt-0.5 text-xs text-red-500">⚠ {d.last_error}</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {d.temperature != null && <span className="text-sm font-mono text-gray-700 dark:text-gray-300">{d.temperature.toFixed(1)}°C</span>}
          <HealthBadge health={d.health} />
          <button onClick={() => setOpen(v => !v)} className="text-xs text-gray-400 hover:text-gray-600">
            {open ? '▲' : '▼'}
          </button>
        </div>
      </div>

      {open && (
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-gray-100 pt-2 text-xs dark:border-gray-800">
          <div className="text-gray-500">Última leitura OK</div>
          <div className="text-gray-700 dark:text-gray-300">{d.last_success_at ? formatRelativeTime(d.last_success_at) : '—'}</div>
          <div className="text-gray-500">Último erro</div>
          <div className="text-gray-700 dark:text-gray-300">{d.last_error_at ? formatRelativeTime(d.last_error_at) : '—'}</div>
          <div className="text-gray-500">Falhas consecutivas</div>
          <div className={cn('font-semibold', d.consecutive_failures >= 3 ? 'text-red-500' : 'text-gray-700 dark:text-gray-300')}>{d.consecutive_failures}</div>
          <div className="text-gray-500">Minutos sem leitura</div>
          <div className="text-gray-700 dark:text-gray-300">{d.minutes_since_reading != null ? `${d.minutes_since_reading} min` : '—'}</div>
          <div className="text-gray-500">Status Brise</div>
          <div className="text-gray-700 dark:text-gray-300">{d.status_classification ?? '—'}</div>
          <div className="text-gray-500">Dado atrasado?</div>
          <div className={d.is_stale ? 'text-orange-500 font-medium' : 'text-gray-700 dark:text-gray-300'}>{d.is_stale ? 'Sim' : 'Não'}</div>
        </div>
      )}
    </div>
  )
}

export default function DiagnosticsPage() {
  const [selectedStore, setSelectedStore] = useState<string>('')

  const { data: stores = [] } = useQuery<Store[]>({
    queryKey: ['stores'],
    queryFn: storesApi.list,
  })

  const { data: diag, isLoading, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['diagnostics', selectedStore],
    queryFn: () => diagnosticsApi.store(selectedStore),
    enabled: !!selectedStore,
    refetchInterval: 60000,
  })

  const overall = diag ? OVERALL_META[diag.summary?.overall_health] : null

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Activity className="h-5 w-5 text-blue-500" />
            Diagnóstico da API
          </h1>
          <p className="text-xs text-gray-500">
            {diag ? `Gerado ${formatRelativeTime(diag.generated_at)} • ${diag.summary.total_devices} equipamentos` : 'Selecione uma loja para diagnóstico'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={selectedStore}
            onChange={e => setSelectedStore(e.target.value)}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-700 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-300"
          >
            <option value="">Selecionar loja…</option>
            {stores.map((s: Store) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          {selectedStore && (
            <button onClick={() => refetch()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800">
              <RefreshCw className={cn('h-3.5 w-3.5', isLoading && 'animate-spin')} />
              Atualizar
            </button>
          )}
        </div>
      </div>

      {!selectedStore && (
        <div className="rounded-xl border border-dashed border-gray-300 py-16 text-center text-gray-500 dark:border-gray-700">
          Selecione uma loja para ver o diagnóstico da API
        </div>
      )}

      {isLoading && (
        <div className="flex items-center justify-center py-16">
          <RefreshCw className="h-6 w-6 animate-spin text-blue-500" />
        </div>
      )}

      {diag && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            {[
              { label: 'Online',       value: diag.summary.ok,          cls: 'text-green-500' },
              { label: 'Offline/API',  value: diag.summary.offline,     cls: diag.summary.offline > 0 ? 'text-red-500' : 'text-gray-400' },
              { label: 'Atrasado',     value: diag.summary.stale,       cls: diag.summary.stale > 0 ? 'text-yellow-500' : 'text-gray-400' },
              { label: 'Sem leitura',  value: diag.summary.no_reading,  cls: diag.summary.no_reading > 0 ? 'text-orange-500' : 'text-gray-400' },
              { label: 'Desligado',    value: diag.summary.off,         cls: 'text-gray-400' },
              { label: 'Saúde geral',  value: overall?.label ?? '—',    cls: overall?.cls ?? 'text-gray-500' },
            ].map(k => (
              <div key={k.label} className="rounded-xl border border-gray-200 bg-white p-3 dark:border-gray-800 dark:bg-gray-900">
                <div className="text-xs font-medium uppercase text-gray-500">{k.label}</div>
                <div className={cn('mt-1 text-2xl font-semibold', k.cls)}>{k.value}</div>
              </div>
            ))}
          </div>

          {/* Piores equipamentos */}
          {diag.worst_devices?.length > 0 && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 dark:border-red-800/40 dark:bg-red-950/20">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-red-700 dark:text-red-400">
                <AlertTriangle className="h-4 w-4" />
                Equipamentos com problema
              </h2>
              <div className="space-y-2">
                {diag.worst_devices.map((d: any) => <DeviceRow key={d.device_id} d={d} />)}
              </div>
            </div>
          )}

          {/* Por setor */}
          <div className="space-y-4">
            {diag.sectors.map((sector: any) => (
              <div key={sector.sector_name} className="rounded-xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900 overflow-hidden">
                <div className={cn('flex items-center justify-between px-4 py-3',
                  sector.health === 'CRÍTICO' ? 'bg-red-50 dark:bg-red-950/20' :
                  sector.health === 'PARCIAL'  ? 'bg-yellow-50 dark:bg-yellow-950/20' : '')}>
                  <div>
                    <h3 className="font-semibold text-gray-900 dark:text-white">{sector.sector_name}</h3>
                    <p className="text-xs text-gray-500">
                      {sector.ok} ok · {sector.offline} offline · {sector.stale} atrasado · {sector.no_reading} sem leitura · {sector.off} desligado
                      {sector.avg_temp != null && ` · média ${sector.avg_temp}°C`}
                    </p>
                  </div>
                  <HealthBadge health={sector.health === 'OK' ? 'OK' : sector.health === 'CRÍTICO' ? 'OFFLINE' : 'DADO_ATRASADO'} />
                </div>
                <div className="divide-y divide-gray-100 p-3 space-y-2 dark:divide-gray-800">
                  {sector.devices
                    .sort((a: any, b: any) => {
                      const order: Record<string, number> = { OFFLINE: 0, FALHA_API: 0, NUNCA_LIDO: 1, SEM_LEITURA: 2, DADO_ATRASADO: 3, SEM_TEMPERATURA: 4, DESLIGADO: 5, OK: 6 }
                      return (order[a.health] ?? 9) - (order[b.health] ?? 9)
                    })
                    .map((d: any) => <DeviceRow key={d.device_id} d={d} />)}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
