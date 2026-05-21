import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, Bot, Building2, CheckCircle, ChevronDown, ChevronRight,
  Clock, Cpu, Power, RefreshCw, Shield, ShieldOff, Thermometer, TrendingDown,
  TrendingUp, Wifi, WifiOff, Zap,
} from 'lucide-react'
import { digitalTwinApi, zonesApi, automationApi, storesApi, aiApi } from '../api/client'
import type {
  DigitalTwinZone, DigitalTwinSimulation, DigitalTwinDevice,
  ZoneAutomationState, AutomationStatus, ZoneAIAnalysis, Store,
} from '../types'
import { cn, formatRelativeTime } from '../lib/utils'
import { useAuthStore } from '../store/useAuthStore'

// ── Metadados visuais ──────────────────────────────────────────────────────────

const RISK_META: Record<string, { badge: string; border: string; label: string; numColor: string }> = {
  LOW:      { badge: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',     border: 'border-green-200 dark:border-green-800/50',   label: 'Baixo',   numColor: 'text-green-600 dark:text-green-400' },
  MEDIUM:   { badge: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300', border: 'border-yellow-300 dark:border-yellow-800/50', label: 'Médio',   numColor: 'text-yellow-600 dark:text-yellow-300' },
  HIGH:     { badge: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300', border: 'border-orange-300 dark:border-orange-700/50', label: 'Alto',    numColor: 'text-orange-600 dark:text-orange-300' },
  CRITICAL: { badge: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',             border: 'border-red-400 dark:border-red-700',           label: 'Crítico', numColor: 'text-red-600 dark:text-red-400' },
}

const STATUS_COLOR: Record<string, string> = {
  COLD:       'text-blue-500',
  COMFORT:    'text-green-500',
  WARM:       'text-yellow-500',
  HOT:        'text-orange-500',
  CRITICAL:   'text-red-600 font-bold',
  NO_READING: 'text-gray-400',
}

const STATUS_LABEL: Record<string, string> = {
  COLD: 'Frio', COMFORT: 'Confortável', WARM: 'Aquecendo',
  HOT: 'Quente', CRITICAL: 'Crítico', NO_READING: 'Sem leitura',
}

const MODE_META: Record<string, { label: string; cls: string }> = {
  manual:      { label: 'Manual',      cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  suggestion:  { label: 'Sugestão',    cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
  semi:        { label: 'Semi-auto',   cls: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400' },
  auto:        { label: 'Automático',  cls: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
  maintenance: { label: 'Manutenção',  cls: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400' },
}

const AI_SEV_META: Record<string, { badge: string; label: string }> = {
  CRITICAL: { badge: 'bg-red-600 text-white',     label: 'Crítico' },
  HIGH:     { badge: 'bg-orange-500 text-white',  label: 'Alto' },
  MEDIUM:   { badge: 'bg-yellow-500 text-white',  label: 'Médio' },
  LOW:      { badge: 'bg-blue-500 text-white',    label: 'Baixo' },
}

// ── Sub-componentes ────────────────────────────────────────────────────────────

function TrendBadge({ value }: { value: number | null }) {
  if (value === null) return <span className="text-xs text-gray-400">tendência ?</span>
  const up = value > 0.3
  const down = value < -0.3
  return (
    <span className={cn('flex items-center gap-0.5 text-xs font-medium',
      up ? 'text-red-500' : down ? 'text-blue-500' : 'text-green-500'
    )}>
      {up ? <TrendingUp className="h-3 w-3" /> : down ? <TrendingDown className="h-3 w-3" /> : <Activity className="h-3 w-3" />}
      {value > 0 ? '+' : ''}{value.toFixed(1)}°C/h
    </span>
  )
}

function PredBadge({ label, temp, status }: { label: string; temp: number | null; status: string }) {
  return (
    <div className="text-center px-2">
      <div className="text-xs text-gray-400 mb-0.5">{label}</div>
      <div className={cn('text-sm font-semibold', STATUS_COLOR[status] || 'text-gray-700 dark:text-white')}>
        {temp != null ? `${temp.toFixed(1)}°C` : '—'}
      </div>
    </div>
  )
}

function SimRow({ sim }: { sim: DigitalTwinSimulation }) {
  const icon = sim.action === 'setpoint_down_1' ? '❄️' : sim.action === 'setpoint_up_1' ? '🔥' : '⏸'
  const feas = sim.feasible
  return (
    <div className={cn('flex items-center gap-2 py-1', !feas && 'opacity-50')}>
      <span className="text-sm shrink-0">{icon}</span>
      <span className="text-xs text-gray-600 dark:text-gray-400 flex-1 truncate">{sim.label}</span>
      {feas ? (
        <div className="flex items-center gap-2 shrink-0">
          <span className={cn('text-xs font-medium', STATUS_COLOR[sim.status_30m] || 'text-gray-600')}>
            30m: {sim.predicted_temp_30m != null ? `${sim.predicted_temp_30m.toFixed(1)}°C` : '?'}
          </span>
          <span className={cn('text-xs font-medium', STATUS_COLOR[sim.status_60m] || 'text-gray-600')}>
            60m: {sim.predicted_temp_60m != null ? `${sim.predicted_temp_60m.toFixed(1)}°C` : '?'}
          </span>
        </div>
      ) : (
        <span className="text-xs text-red-500 shrink-0 truncate max-w-[120px]">{sim.block_reason}</span>
      )}
    </div>
  )
}

function DeviceRow({ d }: { d: DigitalTwinDevice }) {
  const isExt = d.is_external_sensor
  return (
    <div className="flex items-center gap-2 py-0.5">
      {isExt
        ? <Wifi className="h-3 w-3 text-blue-400 shrink-0" />
        : <Zap className="h-3 w-3 text-gray-400 shrink-0" />
      }
      <span className="text-xs text-gray-700 dark:text-gray-300 flex-1 truncate">{d.name}</span>
      <span className={cn('text-xs font-medium shrink-0', STATUS_COLOR[d.status] || 'text-gray-500')}>
        {d.temperature != null ? `${d.temperature.toFixed(1)}°C` : '—'}
      </span>
      {d.efficiency_score != null && !isExt && (
        <span className={cn('text-xs shrink-0',
          d.efficiency_score < 0.6 ? 'text-orange-500' : 'text-gray-400'
        )}>
          {Math.round(d.efficiency_score * 100)}%
        </span>
      )}
    </div>
  )
}

// ── Zona Card ──────────────────────────────────────────────────────────────────

function ZoneCard({
  twin, automation, aiAnalysis, storeId,
  onModeChange, onTrigger, isTriggerPending, killSwitchActive,
}: {
  twin: DigitalTwinZone
  automation: ZoneAutomationState | undefined
  aiAnalysis: ZoneAIAnalysis | undefined
  storeId: string
  onModeChange: (mode: string) => void
  onTrigger: () => void
  isTriggerPending: boolean
  killSwitchActive: boolean
}) {
  const [showSim, setShowSim]       = useState(false)
  const [showDevices, setShowDevices] = useState(false)

  const risk   = RISK_META[twin.risk_level] ?? RISK_META.LOW
  const mode   = automation ? MODE_META[automation.mode] ?? MODE_META.manual : MODE_META.manual
  const aiMeta = aiAnalysis?.severity ? AI_SEV_META[aiAnalysis.severity] : null

  const guardrailActive = automation?.guardrail_active ?? false
  const inCooldown      = (automation?.cooldown_remaining_s ?? 0) > 0
  const blocked         = automation?.blocked_reason != null

  return (
    <div className={cn('rounded-xl border bg-white dark:bg-gray-900 overflow-hidden flex flex-col', risk.border)}>
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-100 dark:border-gray-800 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap mb-0.5">
            <span className={cn('rounded px-1.5 py-0.5 text-xs font-bold', risk.badge)}>{risk.label}</span>
            <span className="rounded px-1.5 py-0.5 text-xs bg-gray-100 dark:bg-gray-800 text-gray-500">
              {twin.zone_type === 'SALA_FECHADA' ? 'Sala' : 'Aberta'}
            </span>
            {twin.early_warning && (
              <span className="rounded px-1.5 py-0.5 text-xs bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 font-medium animate-pulse">
                ⚡ Tendência
              </span>
            )}
            {blocked && <span className="rounded px-1.5 py-0.5 text-xs bg-orange-100 text-orange-600 font-medium">Bloqueado</span>}
          </div>
          <p className="font-semibold text-gray-900 dark:text-white truncate">{twin.zone_label}</p>
          <p className="text-xs text-gray-400">
            Faixa: {twin.ideal_min}–{twin.ideal_max}°C
            {automation && ` · ${automation.daily_count}/${automation.max_daily_adjustments} ajustes hoje`}
          </p>
        </div>

        {/* Mode selector */}
        <select
          value={automation?.mode ?? 'manual'}
          onChange={e => onModeChange(e.target.value)}
          disabled={killSwitchActive}
          className={cn(
            'rounded-lg px-2 py-1 text-xs font-medium border-0 outline-none cursor-pointer shrink-0',
            mode.cls,
            killSwitchActive && 'opacity-50 cursor-not-allowed'
          )}
        >
          {Object.entries(MODE_META).filter(([k]) => k !== 'maintenance').map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
      </div>

      {/* Temperature */}
      <div className="px-4 py-3 flex items-center gap-4 border-b border-gray-100 dark:border-gray-800">
        <div className="flex-1">
          <div className={cn('text-3xl font-bold tabular-nums', STATUS_COLOR[twin.current_status] || 'text-gray-800 dark:text-white')}>
            {twin.current_avg_temp != null ? `${twin.current_avg_temp.toFixed(1)}°C` : '—'}
          </div>
          <div className={cn('text-xs font-medium mt-0.5', STATUS_COLOR[twin.current_status] || 'text-gray-500')}>
            {STATUS_LABEL[twin.current_status] ?? twin.current_status}
          </div>
        </div>

        <div className="space-y-1 text-right">
          <TrendBadge value={twin.trend_c_per_hour} />
          <div className="text-xs text-gray-400">
            conf. {Math.round(twin.confidence * 100)}%
          </div>
        </div>
      </div>

      {/* Predictions */}
      <div className="px-4 py-2 flex items-center justify-around border-b border-gray-100 dark:border-gray-800">
        <PredBadge label="15 min" temp={twin.predicted_temp_15m} status={twin.current_status} />
        <div className="h-6 border-r border-gray-200 dark:border-gray-700" />
        <PredBadge label="30 min" temp={twin.predicted_temp_30m} status={twin.current_status} />
        <div className="h-6 border-r border-gray-200 dark:border-gray-700" />
        <PredBadge label="60 min" temp={twin.predicted_temp_60m} status={twin.current_status} />
      </div>

      {/* Guardrail / cooldown warning */}
      {guardrailActive && automation?.guardrail_reason && (
        <div className="px-4 py-1.5 bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-200 dark:border-yellow-800/40 flex items-center gap-1.5">
          <Shield className="h-3 w-3 text-yellow-600 shrink-0" />
          <span className="text-xs text-yellow-700 dark:text-yellow-300">{automation.guardrail_reason}</span>
        </div>
      )}
      {inCooldown && !guardrailActive && (
        <div className="px-4 py-1.5 bg-blue-50 dark:bg-blue-900/20 border-b border-blue-200 dark:border-blue-800/40 flex items-center gap-1.5">
          <Clock className="h-3 w-3 text-blue-500 shrink-0" />
          <span className="text-xs text-blue-600 dark:text-blue-300">
            Cooldown: {Math.round((automation?.cooldown_remaining_s ?? 0) / 60)} min
          </span>
        </div>
      )}

      {/* Simulations collapsible */}
      {twin.simulated_actions.length > 0 && (
        <div className="border-b border-gray-100 dark:border-gray-800">
          <button
            onClick={() => setShowSim(s => !s)}
            className="w-full flex items-center justify-between px-4 py-2 text-xs font-medium text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
          >
            <span className="flex items-center gap-1.5"><Activity className="h-3 w-3" />Simulações</span>
            <ChevronDown className={cn('h-3 w-3 transition-transform', showSim && 'rotate-180')} />
          </button>
          {showSim && (
            <div className="px-4 pb-2 divide-y divide-gray-100 dark:divide-gray-800">
              {twin.simulated_actions.map(sim => <SimRow key={sim.action} sim={sim} />)}
            </div>
          )}
        </div>
      )}

      {/* Devices collapsible */}
      {twin.contributing_devices.length > 0 && (
        <div className="border-b border-gray-100 dark:border-gray-800">
          <button
            onClick={() => setShowDevices(s => !s)}
            className="w-full flex items-center justify-between px-4 py-2 text-xs font-medium text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
          >
            <span className="flex items-center gap-1.5">
              <Thermometer className="h-3 w-3" />
              {twin.contributing_devices.length} dispositivo(s)
            </span>
            <ChevronDown className={cn('h-3 w-3 transition-transform', showDevices && 'rotate-180')} />
          </button>
          {showDevices && (
            <div className="px-4 pb-2">
              {twin.contributing_devices.map(d => <DeviceRow key={d.device_id} d={d} />)}
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="px-4 py-2.5 flex items-center justify-between gap-2 mt-auto">
        <div className="flex items-center gap-2 min-w-0">
          {aiMeta && (
            <span className="flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium shrink-0" style={{}}>
              <Bot className="h-3 w-3" />
              <span className={cn('rounded px-1 py-0 text-xs font-bold', aiMeta.badge)}>{aiMeta.label}</span>
            </span>
          )}
          <span className="text-xs text-gray-400 truncate">
            {formatRelativeTime(twin.computed_at)}
          </span>
        </div>

        <button
          onClick={onTrigger}
          disabled={isTriggerPending || killSwitchActive || blocked}
          className="flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-40 shrink-0 transition-colors"
        >
          {isTriggerPending
            ? <RefreshCw className="h-3 w-3 animate-spin" />
            : <Zap className="h-3 w-3" />
          }
          Executar
        </button>
      </div>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────────────

export default function DigitalTwinPage() {
  const qc = useQueryClient()
  const { name: userName } = useAuthStore()
  const [storeId, setStoreId] = useState<string>('')
  const [pendingTrigger, setPendingTrigger] = useState<string | null>(null)

  const { data: stores } = useQuery<Store[]>({
    queryKey: ['stores'],
    queryFn: storesApi.list,
  })

  useEffect(() => {
    if (!storeId && stores && stores.length > 0) setStoreId(stores[0].id)
  }, [storeId, stores])

  const selectedStoreId = storeId || (stores && stores.length > 0 ? stores[0].id : undefined)

  const { data: twins = [], isLoading: loadingTwin, refetch: refetchTwin } = useQuery<DigitalTwinZone[]>({
    queryKey: ['digital-twin', selectedStoreId],
    queryFn: () => digitalTwinApi.store(selectedStoreId!),
    enabled: !!selectedStoreId,
    refetchInterval: 60_000,
  })

  const { data: zonesData = [] } = useQuery<ZoneAutomationState[]>({
    queryKey: ['zones-automation', selectedStoreId],
    queryFn: () => zonesApi.list(selectedStoreId!),
    enabled: !!selectedStoreId,
    refetchInterval: 30_000,
  })

  const { data: autoStatus } = useQuery<AutomationStatus>({
    queryKey: ['automation-status'],
    queryFn: automationApi.status,
    refetchInterval: 15_000,
  })

  const { data: aiData } = useQuery({
    queryKey: ['ai-zone-analyses'],
    queryFn: aiApi.zoneAnalyses,
    refetchInterval: 60_000,
  })

  // Map zone_key → automation state
  const zoneMap = new Map<string, ZoneAutomationState>(
    zonesData.map(z => [z.zone_key, z])
  )

  // Map zone_key → AI analysis
  const aiMap = new Map<string, ZoneAIAnalysis>(
    ((aiData?.analyses ?? []) as ZoneAIAnalysis[])
      .filter(a => a.store_id === selectedStoreId)
      .map(a => [a.zone_key, a])
  )

  // Kill switch
  const killSwitchMutation = useMutation({
    mutationFn: (active: boolean) =>
      automationApi.setKillSwitch(active, userName ?? 'operador'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['automation-status'] }),
  })

  // Mode change
  const modeChangeMutation = useMutation({
    mutationFn: ({ zoneKey, mode }: { zoneKey: string; mode: string }) =>
      zonesApi.setMode(selectedStoreId!, zoneKey, { mode }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['zones-automation', selectedStoreId] })
    },
  })

  // Zone trigger
  const triggerMutation = useMutation({
    mutationFn: (zoneKey: string) => zonesApi.trigger(selectedStoreId!, zoneKey),
    onMutate: (zoneKey) => setPendingTrigger(zoneKey),
    onSettled: () => {
      setPendingTrigger(null)
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['digital-twin', selectedStoreId] })
        qc.invalidateQueries({ queryKey: ['zones-automation', selectedStoreId] })
      }, 3000)
    },
  })

  const ks = autoStatus?.kill_switch_active ?? false

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div className="flex items-center gap-3">
          <Cpu className="h-6 w-6 text-indigo-500" />
          <div>
            <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Digital Twin</h1>
            <p className="text-xs text-gray-500">Simulação e controle de zonas térmicas em tempo real</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Kill switch */}
          <button
            onClick={() => killSwitchMutation.mutate(!ks)}
            disabled={killSwitchMutation.isPending}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              ks
                ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50'
                : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
            )}
          >
            {ks ? <ShieldOff className="h-3.5 w-3.5" /> : <Shield className="h-3.5 w-3.5" />}
            {ks ? 'Kill switch ativo' : 'Kill switch'}
          </button>

          {/* Refresh */}
          <button
            onClick={() => refetchTwin()}
            className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <RefreshCw className={cn('h-4 w-4', loadingTwin && 'animate-spin')} />
          </button>

          {/* Store selector */}
          <div className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-gray-400" />
            <select
              value={selectedStoreId ?? ''}
              onChange={e => setStoreId(e.target.value)}
              className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-3 py-1.5 text-sm text-gray-900 dark:text-white outline-none focus:border-indigo-500"
            >
              {stores?.map((s: Store) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Kill switch banner */}
      {ks && (
        <div className="flex items-center gap-2 px-6 py-2 bg-red-50 dark:bg-red-950/40 border-b border-red-200 dark:border-red-800">
          <AlertTriangle className="h-4 w-4 text-red-600 shrink-0" />
          <span className="text-sm text-red-700 dark:text-red-300 font-medium">
            Kill switch ativo — automação suspensa em todas as zonas.
            {autoStatus?.kill_switch_activated_by && ` Ativado por: ${autoStatus.kill_switch_activated_by}`}
          </span>
        </div>
      )}

      {/* Zone grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {loadingTwin ? (
          <div className="flex items-center justify-center py-20 text-gray-400">
            <RefreshCw className="h-5 w-5 animate-spin mr-2" /> Calculando digital twin…
          </div>
        ) : twins.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <WifiOff className="h-10 w-10 mb-3" />
            <p className="font-medium text-gray-600 dark:text-gray-300">Nenhuma zona configurada para esta loja</p>
          </div>
        ) : (
          <>
            {/* Summary strip */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
              {(['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const).map(r => {
                const n = twins.filter(t => t.risk_level === r).length
                const m = RISK_META[r]
                return (
                  <div key={r} className={cn('rounded-xl border p-3 text-center', m.border, 'bg-white dark:bg-gray-900')}>
                    <div className={cn('text-2xl font-bold', m.numColor)}>{n}</div>
                    <div className="text-xs text-gray-500">{m.label}</div>
                  </div>
                )
              })}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {twins.map(twin => (
                <ZoneCard
                  key={twin.zone_key}
                  twin={twin}
                  automation={zoneMap.get(twin.zone_key)}
                  aiAnalysis={aiMap.get(twin.zone_key)}
                  storeId={selectedStoreId!}
                  onModeChange={mode => modeChangeMutation.mutate({ zoneKey: twin.zone_key, mode })}
                  onTrigger={() => triggerMutation.mutate(twin.zone_key)}
                  isTriggerPending={pendingTrigger === twin.zone_key && triggerMutation.isPending}
                  killSwitchActive={ks}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
