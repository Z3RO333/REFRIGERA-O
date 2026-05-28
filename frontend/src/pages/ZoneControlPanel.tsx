import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, Bot, ChevronDown, Clock, Pencil, Play,
  RefreshCw, Shield, ShieldOff, Thermometer, Trash2, TrendingDown,
  TrendingUp, Wind, Zap, Wifi,
} from 'lucide-react'
import { automationApi, customZonesApi, digitalTwinApi, storesApi, zonesApi } from '../api/client'
import { cn, formatRelativeTime } from '../lib/utils'
import { useAuthStore } from '../store/useAuthStore'
import type { CustomZone, DigitalTwinZone, Store, ZoneAutomationState, ZonePriority } from '../types'

// ── Metadados de status térmico ───────────────────────────────────────────────

type ThermalStatus = 'COLD' | 'COMFORT' | 'WARM' | 'HOT' | 'CRITICAL' | 'NO_READING'

const STATUS_META: Record<ThermalStatus, {
  label: string; border: string; dot: string; bg: string; text: string
}> = {
  COLD:       { label: 'Frio demais',  border: 'border-l-blue-500',   dot: 'bg-blue-500',   bg: 'bg-blue-50 dark:bg-blue-900/20',    text: 'text-blue-600 dark:text-blue-400' },
  COMFORT:    { label: 'Confortável',  border: 'border-l-green-500',  dot: 'bg-green-500',  bg: 'bg-green-50 dark:bg-green-900/20',  text: 'text-green-600 dark:text-green-400' },
  WARM:       { label: 'Aquecendo',   border: 'border-l-yellow-500', dot: 'bg-yellow-500', bg: 'bg-yellow-50 dark:bg-yellow-900/20',text: 'text-yellow-600 dark:text-yellow-400' },
  HOT:        { label: 'Quente',      border: 'border-l-orange-500', dot: 'bg-orange-500', bg: 'bg-orange-50 dark:bg-orange-900/20',text: 'text-orange-600 dark:text-orange-400' },
  CRITICAL:   { label: 'Crítico',     border: 'border-l-red-500',    dot: 'bg-red-500 animate-pulse', bg: 'bg-red-50 dark:bg-red-900/20', text: 'text-red-600 dark:text-red-400' },
  NO_READING: { label: 'Sem leitura', border: 'border-l-gray-400',   dot: 'bg-gray-400',   bg: 'bg-gray-50 dark:bg-gray-800/40',    text: 'text-gray-500 dark:text-gray-400' },
}

const MODE_META: Record<string, { label: string; cls: string }> = {
  manual:      { label: 'Manual',      cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300' },
  suggestion:  { label: 'Sugestão',    cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
  semi:        { label: 'Semi-auto',   cls: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400' },
  auto:        { label: 'Automático',  cls: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
  maintenance: { label: 'Manutenção',  cls: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400' },
}

const PRIORITY_META: Record<ZonePriority, { label: string; icon: string }> = {
  conforto:     { label: 'Conforto',     icon: '😊' },
  economia:     { label: 'Economia',     icon: '💰' },
  estabilidade: { label: 'Estabilidade', icon: '⚖️' },
  manutencao:   { label: 'Manutenção',   icon: '🔧' },
  critico:      { label: 'Crítico',      icon: '⚠️' },
}

const SUMMARY_COLORS: Record<ThermalStatus, string> = {
  COLD:       'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  COMFORT:    'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  WARM:       'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300',
  HOT:        'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
  CRITICAL:   'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  NO_READING: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function toThermal(s: string): ThermalStatus {
  if (s === 'COLD' || s === 'COMFORT' || s === 'WARM' || s === 'HOT' || s === 'CRITICAL') return s
  return 'NO_READING'
}

function formatCooldown(secs: number | null | undefined): string | null {
  if (!secs || secs <= 0) return null
  const m = Math.ceil(secs / 60)
  return m === 1 ? '1 min' : `${m} min`
}

// ── Sub-componentes ───────────────────────────────────────────────────────────

function TrendBadge({ value }: { value: number | null | undefined }) {
  if (value == null) return null
  const up = value > 0.3
  const down = value < -0.3
  const color = up ? 'text-red-500' : down ? 'text-blue-500' : 'text-green-500'
  return (
    <span className={cn('flex items-center gap-0.5 text-xs font-medium tabular-nums', color)}>
      {up ? <TrendingUp className="h-3 w-3" /> : down ? <TrendingDown className="h-3 w-3" /> : <Activity className="h-3 w-3" />}
      {value > 0 ? '+' : ''}{value.toFixed(1)}°C/h
    </span>
  )
}

// ── Card de zona ──────────────────────────────────────────────────────────────

interface ZoneCardProps {
  twin: DigitalTwinZone
  automation: ZoneAutomationState | undefined
  storeId: string
  killSwitchActive: boolean
  canEdit: boolean
  canAdmin: boolean
  isCustom?: boolean
  onModeChange: (mode: string) => void
  onPriorityChange: (priority: ZonePriority) => void
  onTrigger: () => void
  isTriggerPending: boolean
  onEdit?: () => void
  onDelete?: () => void
}

function ZoneCard({
  twin, automation, killSwitchActive,
  canEdit, canAdmin, isCustom,
  onModeChange, onPriorityChange, onTrigger, isTriggerPending,
  onEdit, onDelete,
}: ZoneCardProps) {
  const [devicesOpen, setDevicesOpen] = useState(false)

  const thermalStatus = toThermal(twin.current_status)
  const meta = STATUS_META[thermalStatus]
  const modeMeta = MODE_META[automation?.mode ?? 'manual'] ?? MODE_META.manual
  const priority: ZonePriority = (automation?.priority as ZonePriority) ?? 'conforto'

  const guardrailActive = automation?.guardrail_active ?? false
  const cooldownStr = formatCooldown(automation?.cooldown_remaining_s)
  const isBlocked = !!automation?.blocked_reason
  const inCooldown = !!cooldownStr && !guardrailActive

  const editDisabled = !canEdit || killSwitchActive
  const adminDisabled = !canAdmin || killSwitchActive

  // Explicação da IA — prefere twin.explanation (mais rica), fallback para last_action
  const aiExplanation = twin.explanation || automation?.last_action?.reason || null
  const lastActionTime = automation?.last_action?.created_at

  const modeOptions = canAdmin
    ? Object.entries(MODE_META)
    : Object.entries(MODE_META).filter(([k]) => k !== 'auto' && k !== 'maintenance')

  return (
    <div className={cn(
      'rounded-xl border border-gray-200 dark:border-gray-800',
      'bg-white dark:bg-gray-900 overflow-hidden flex flex-col',
      'border-l-4', meta.border,
    )}>
      {/* ── Header: nome + modo ── */}
      <div className="px-4 py-3 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
            <span className={cn('inline-flex items-center gap-1 text-xs font-semibold rounded-full px-2 py-0.5', meta.bg, meta.text)}>
              <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', meta.dot)} />
              {meta.label}
            </span>
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {twin.zone_type === 'SALA_FECHADA' ? 'Sala' : 'Aberta'}
            </span>
            {isBlocked && (
              <span className="text-xs font-medium bg-orange-100 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400 rounded px-1.5 py-0.5">
                Bloqueado
              </span>
            )}
          </div>
          <p className="font-semibold text-gray-900 dark:text-white text-sm truncate">{twin.zone_label}</p>
          <p className="text-xs text-gray-400 mt-0.5">
            {twin.ideal_min}–{twin.ideal_max}°C ideal
            {automation && automation.daily_count > 0 && ` · ${automation.daily_count} ações hoje`}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {isCustom && canEdit && (
            <>
              <button
                onClick={onEdit}
                title="Editar zona"
                className="p-1 rounded text-gray-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={onDelete}
                title="Excluir zona"
                className="p-1 rounded text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </>
          )}
          <select
            value={automation?.mode ?? 'manual'}
            onChange={e => onModeChange(e.target.value)}
            disabled={editDisabled}
            className={cn(
              'rounded-lg px-2 py-1 text-xs font-medium border-0 outline-none cursor-pointer',
              modeMeta.cls,
              editDisabled && 'opacity-50 cursor-not-allowed',
            )}
          >
            {modeOptions.map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Temperatura ── */}
      <div className={cn('px-4 py-3 flex items-center gap-4 border-t border-b border-gray-100 dark:border-gray-800')}>
        <div className="flex-1">
          <div className={cn('text-4xl font-bold tabular-nums leading-none', meta.text)}>
            {twin.current_avg_temp != null ? `${twin.current_avg_temp.toFixed(1)}°C` : '—'}
          </div>
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Meta: {twin.ideal_min}–{twin.ideal_max}°C
          </div>
        </div>
        <div className="text-right space-y-1">
          <TrendBadge value={twin.trend_c_per_hour} />
          <div className="text-xs text-gray-400 tabular-nums">
            conf. {Math.round(twin.confidence * 100)}%
          </div>
          <div className="flex gap-1 justify-end text-xs text-gray-400">
            <span>15m: {twin.predicted_temp_15m != null ? `${twin.predicted_temp_15m.toFixed(1)}°` : '—'}</span>
            <span>·</span>
            <span>30m: {twin.predicted_temp_30m != null ? `${twin.predicted_temp_30m.toFixed(1)}°` : '—'}</span>
          </div>
        </div>
      </div>

      {/* ── Avisos de guardrail / cooldown / manutenção ── */}
      {guardrailActive && automation?.guardrail_reason && (
        <div className="px-4 py-1.5 flex items-center gap-1.5 bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-200 dark:border-yellow-800/40">
          <Shield className="h-3 w-3 text-yellow-600 shrink-0" />
          <span className="text-xs text-yellow-700 dark:text-yellow-300">{automation.guardrail_reason}</span>
        </div>
      )}
      {inCooldown && (
        <div className="px-4 py-1.5 flex items-center gap-1.5 bg-blue-50 dark:bg-blue-900/20 border-b border-blue-200 dark:border-blue-800/40">
          <Clock className="h-3 w-3 text-blue-500 shrink-0" />
          <span className="text-xs text-blue-600 dark:text-blue-300">
            Próxima avaliação: {cooldownStr}
          </span>
        </div>
      )}
      {isBlocked && automation?.blocked_reason && (
        <div className="px-4 py-1.5 flex items-start gap-1.5 bg-orange-50 dark:bg-orange-900/20 border-b border-orange-200 dark:border-orange-800/40">
          <AlertTriangle className="h-3 w-3 text-orange-600 shrink-0 mt-0.5" />
          <span className="text-xs text-orange-700 dark:text-orange-300 line-clamp-2">
            {automation.blocked_reason}
            {automation.blocked_until && ` até ${new Date(automation.blocked_until).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}`}
          </span>
        </div>
      )}

      {/* ── Explicação da IA ── */}
      {aiExplanation && (
        <div className="px-4 py-2.5 border-b border-gray-100 dark:border-gray-800">
          <div className="flex items-start gap-2">
            <Bot className="h-3.5 w-3.5 text-purple-500 shrink-0 mt-0.5" />
            <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed line-clamp-3">
              {aiExplanation}
            </p>
          </div>
          {lastActionTime && (
            <p className="text-xs text-gray-400 mt-1 ml-5">
              {formatRelativeTime(lastActionTime)}
              {automation?.last_action?.status === 'verified_success' && ' · ✓ Efetivo'}
              {automation?.last_action?.status === 'verified_failure' && ' · ✗ Sem efeito'}
            </p>
          )}
        </div>
      )}

      {/* ── Equipamentos ── */}
      {twin.contributing_devices.length > 0 && (
        <div className="border-b border-gray-100 dark:border-gray-800">
          <button
            onClick={() => setDevicesOpen(o => !o)}
            className="w-full flex items-center justify-between px-4 py-2 text-xs font-medium text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
          >
            <span className="flex items-center gap-1.5">
              <Wind className="h-3 w-3" />
              Equipamentos ({twin.contributing_devices.length})
            </span>
            <ChevronDown className={cn('h-3 w-3 transition-transform', devicesOpen && 'rotate-180')} />
          </button>
          {devicesOpen && (
            <div className="px-4 pb-2 space-y-1">
              {twin.contributing_devices.map(d => (
                <div key={d.device_id} className="flex items-center gap-2 py-0.5">
                  {d.is_external_sensor
                    ? <Wifi className="h-3 w-3 text-blue-400 shrink-0" />
                    : <Zap className="h-3 w-3 text-gray-400 shrink-0" />
                  }
                  <span className="text-xs text-gray-700 dark:text-gray-300 flex-1 truncate">{d.name}</span>
                  <span className="text-xs font-medium tabular-nums text-gray-600 dark:text-gray-400 shrink-0">
                    {d.temperature != null ? `${d.temperature.toFixed(1)}°C` : '—'}
                  </span>
                  {d.efficiency_score != null && !d.is_external_sensor && (
                    <span className={cn('text-xs tabular-nums shrink-0',
                      d.efficiency_score < 0.6 ? 'text-orange-500' : 'text-gray-400'
                    )}>
                      {Math.round(d.efficiency_score * 100)}%
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Rodapé: prioridade + trigger ── */}
      <div className="px-4 py-2.5 flex items-center justify-between gap-2">
        <select
          value={priority}
          onChange={e => onPriorityChange(e.target.value as ZonePriority)}
          disabled={adminDisabled}
          className={cn(
            'text-xs rounded-lg px-2 py-1 border border-gray-200 dark:border-gray-700',
            'bg-gray-50 dark:bg-gray-800 text-gray-600 dark:text-gray-400',
            'outline-none cursor-pointer',
            adminDisabled && 'opacity-50 cursor-not-allowed',
          )}
        >
          {(Object.entries(PRIORITY_META) as [ZonePriority, { label: string; icon: string }][]).map(([k, v]) => (
            <option key={k} value={k}>{v.icon} {v.label}</option>
          ))}
        </select>

        <button
          onClick={onTrigger}
          disabled={!canEdit || isTriggerPending || automation?.mode === 'maintenance'}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
            'bg-blue-600 hover:bg-blue-500 text-white',
            (!canEdit || isTriggerPending || automation?.mode === 'maintenance') && 'opacity-50 cursor-not-allowed',
          )}
        >
          {isTriggerPending
            ? <RefreshCw className="h-3 w-3 animate-spin" />
            : <Play className="h-3 w-3" />
          }
          Avaliar agora
        </button>
      </div>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────────────

export default function ZoneControlPanel() {
  const { role } = useAuthStore()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const canEdit = role === 'EDITOR' || role === 'ADMIN'
  const canAdmin = role === 'ADMIN'

  const [storeId, setStoreId] = useState<string>('')
  const [filterStatus, setFilterStatus] = useState<ThermalStatus | 'ALL'>('ALL')
  const [triggeringKey, setTriggeringKey] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  // Lojas disponíveis
  const { data: stores = [] } = useQuery<Store[]>({
    queryKey: ['stores'],
    queryFn: storesApi.list,
  })

  useEffect(() => {
    if (!storeId && stores.length > 0) setStoreId(stores[0].id)
  }, [stores, storeId])

  // Estado de automação (mode, last_action, guardrails, cooldown...)
  const { data: automationsData, isLoading: autoLoading } = useQuery({
    queryKey: ['zones-automation', storeId],
    queryFn: () => zonesApi.list(storeId),
    refetchInterval: 30000,
    enabled: !!storeId,
  })
  const automations: ZoneAutomationState[] = (automationsData as ZoneAutomationState[]) ?? []

  // Digital twin (temperatura atual, tendência, equipamentos, explicação da IA)
  const { data: twinsData, isLoading: twinLoading, refetch: refetchTwin } = useQuery({
    queryKey: ['digital-twin', storeId],
    queryFn: () => digitalTwinApi.store(storeId),
    refetchInterval: 30000,
    enabled: !!storeId,
  })
  const twins: DigitalTwinZone[] = (twinsData as DigitalTwinZone[]) ?? []

  // Zonas personalizadas
  const { data: customZonesData } = useQuery({
    queryKey: ['custom-zones', storeId],
    queryFn: () => customZonesApi.list(storeId),
    refetchInterval: 30000,
    enabled: !!storeId,
  })
  const customZones: CustomZone[] = (customZonesData as CustomZone[]) ?? []

  // Status global da automação (kill switch)
  const { data: autoStatus } = useQuery({
    queryKey: ['automation-status'],
    queryFn: automationApi.status,
    refetchInterval: 10000,
  })

  const killSwitchActive: boolean = autoStatus?.kill_switch_active ?? false

  // Mescla twin + automation + custom zones por zone_key
  const zones = useMemo(() => {
    const autoMap = Object.fromEntries(automations.map(a => [a.zone_key, a]))
    const twinMap = Object.fromEntries(twins.map(t => [t.zone_key, t]))

    // Zonas padrão (hardcoded + via digital twin)
    const standardZones = twins.map(twin => ({
      twin,
      automation: autoMap[twin.zone_key],
      isCustom: false,
      customZone: undefined as CustomZone | undefined,
    }))

    // Zonas customizadas sem twin (usa dados do customZone direto)
    const customKeys = new Set(twins.map(t => t.zone_key))
    const customOnly = customZones
      .filter(cz => !customKeys.has(cz.zone_key))
      .map(cz => ({
        twin: {
          zone_key: cz.zone_key,
          zone_label: cz.name,
          zone_type: cz.zone_type,
          ideal_min: cz.ideal_min,
          ideal_max: cz.ideal_max,
          current_avg_temp: cz.current_temp,
          current_status: cz.temp_status,
          trend_c_per_hour: null,
          predicted_temp_15m: null,
          predicted_temp_30m: null,
          predicted_temp_60m: null,
          risk_level: 'LOW' as const,
          confidence: 1,
          freshness_ratio: 1,
          fresh_device_count: 0,
          stale_device_count: 0,
          early_warning: false,
          contributing_devices: [],
          recommended_action: '',
          explanation: autoMap[cz.zone_key]?.last_action?.reason ?? '',
          simulated_actions: [],
          computed_at: '',
          store_id: storeId,
        } as DigitalTwinZone,
        automation: autoMap[cz.zone_key],
        isCustom: true,
        customZone: cz,
      }))

    return [...standardZones, ...customOnly]
      .filter(z => filterStatus === 'ALL' || toThermal(z.twin.current_status) === filterStatus)
  }, [twins, automations, customZones, filterStatus, storeId])

  // Resumo de status para pills de filtro
  const statusCounts = useMemo(() => {
    const counts: Partial<Record<ThermalStatus, number>> = {}
    for (const t of twins) {
      const s = toThermal(t.current_status)
      counts[s] = (counts[s] ?? 0) + 1
    }
    return counts
  }, [twins])

  // Mutação: deletar zona customizada
  const deleteMutation = useMutation({
    mutationFn: (zoneKey: string) => customZonesApi.delete(storeId, zoneKey),
    onMutate: () => setActionError(null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['custom-zones', storeId] })
      qc.invalidateQueries({ queryKey: ['zones-automation', storeId] })
    },
    onError: (err: any) => {
      setActionError(err?.response?.data?.detail ?? 'Não foi possível remover a zona.')
    },
  })

  // Mutação: trocar modo
  const modeMutation = useMutation({
    mutationFn: ({ zoneKey, mode, priority }: { zoneKey: string; mode: string; priority?: string }) =>
      zonesApi.setMode(storeId, zoneKey, { mode, ...(priority ? { priority } : {}) }),
    onMutate: () => setActionError(null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['zones-automation', storeId] })
    },
    onError: (err: any) => {
      setActionError(err?.response?.data?.detail ?? 'Não foi possível alterar o modo da zona.')
    },
  })

  // Mutação: trigger manual
  const triggerMutation = useMutation({
    mutationFn: (zoneKey: string) => zonesApi.trigger(storeId, zoneKey),
    onMutate: () => setActionError(null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['zones-automation', storeId] })
      qc.invalidateQueries({ queryKey: ['digital-twin', storeId] })
      setTriggeringKey(null)
    },
    onError: (err: any) => {
      setActionError(err?.response?.data?.detail ?? 'Não foi possível disparar a avaliação da zona.')
      setTriggeringKey(null)
    },
  })

  const isLoading = autoLoading || twinLoading

  const statusOrder: ThermalStatus[] = ['CRITICAL', 'HOT', 'WARM', 'COLD', 'COMFORT', 'NO_READING']

  return (
    <div className="space-y-5">
      {/* ── Cabeçalho ── */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Thermometer className="h-5 w-5 text-blue-500" />
            Controle de Ambientes
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Monitoramento e automação por zona térmica
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Seletor de loja */}
          {stores.length > 1 && (
            <select
              value={storeId}
              onChange={e => setStoreId(e.target.value)}
              className="rounded-lg px-3 py-1.5 text-sm bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 outline-none"
            >
              {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}

          {canEdit && storeId && (
            <button
              onClick={() => navigate(`/mapa-termico/${storeId}?editZones=1`)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-sm font-medium transition-colors"
            >
              <Pencil className="h-4 w-4" />
              Editar zonas no mapa
            </button>
          )}

          {/* Kill switch badge */}
          {killSwitchActive && (
            <span className="flex items-center gap-1.5 px-3 py-1.5 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded-lg text-sm font-medium">
              <ShieldOff className="h-4 w-4" />
              Kill switch ativo
            </span>
          )}

          <button
            onClick={() => { refetchTwin(); qc.invalidateQueries({ queryKey: ['zones-automation', storeId] }) }}
            className="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            title="Atualizar"
          >
            <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
          </button>
        </div>
      </div>

      {actionError && (
        <div className="flex items-start gap-3 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/60 rounded-xl">
          <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-700 dark:text-red-300">{actionError}</p>
        </div>
      )}

      {/* ── Banner kill switch ── */}
      {killSwitchActive && (
        <div className="flex items-start gap-3 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800/60 rounded-xl">
          <Shield className="h-5 w-5 text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-red-700 dark:text-red-400">Automação suspensa globalmente</p>
            <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">
              O kill switch está ativo. Nenhuma ação automática será executada.
              {autoStatus?.kill_switch_activated_by && ` Ativado por ${autoStatus.kill_switch_activated_by}.`}
            </p>
          </div>
        </div>
      )}

      {/* ── Filtros de status ── */}
      {twins.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setFilterStatus('ALL')}
            className={cn(
              'px-3 py-1 rounded-full text-xs font-medium transition-colors',
              filterStatus === 'ALL'
                ? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
                : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700',
            )}
          >
            Todos ({twins.length})
          </button>
          {statusOrder.filter(s => statusCounts[s]).map(s => (
            <button
              key={s}
              onClick={() => setFilterStatus(filterStatus === s ? 'ALL' : s)}
              className={cn(
                'px-3 py-1 rounded-full text-xs font-medium transition-colors',
                filterStatus === s ? SUMMARY_COLORS[s] + ' ring-2 ring-offset-1 ring-current' : SUMMARY_COLORS[s],
              )}
            >
              {STATUS_META[s].label} ({statusCounts[s]})
            </button>
          ))}
        </div>
      )}

      {/* ── Grid de zonas ── */}
      {isLoading && !zones.length ? (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <RefreshCw className="h-6 w-6 animate-spin mr-3" />
          Carregando ambientes…
        </div>
      ) : zones.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          {!storeId ? 'Selecione uma loja para ver os ambientes.' : 'Nenhum ambiente encontrado.'}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {zones.map(({ twin, automation, isCustom, customZone }) => (
            <ZoneCard
              key={twin.zone_key}
              twin={twin}
              automation={automation}
              storeId={storeId}
              killSwitchActive={killSwitchActive}
              canEdit={canEdit}
              canAdmin={canAdmin}
              isCustom={isCustom}
              onModeChange={(mode) => modeMutation.mutate({ zoneKey: twin.zone_key, mode })}
              onPriorityChange={(priority) => modeMutation.mutate({
                zoneKey: twin.zone_key,
                mode: automation?.mode ?? 'manual',
                priority,
              })}
              onTrigger={() => {
                setTriggeringKey(twin.zone_key)
                triggerMutation.mutate(twin.zone_key)
              }}
              isTriggerPending={triggeringKey === twin.zone_key && triggerMutation.isPending}
              onEdit={() => navigate(`/mapa-termico/${storeId}?editZones=1&zone=${twin.zone_key}`)}
              onDelete={() => {
                if (confirm(`Excluir a zona "${twin.zone_label}"?`)) {
                  deleteMutation.mutate(twin.zone_key)
                }
              }}
            />
          ))}
        </div>
      )}

    </div>
  )
}
