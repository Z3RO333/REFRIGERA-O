import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, Bot, ChevronDown, ChevronRight, Clock,
  RefreshCw, Search, Shield, ShieldOff, Thermometer, ToggleLeft, Wrench, Zap,
} from 'lucide-react'
import { logsApi, storesApi } from '../api/client'
import type { LogEntry, LogKPIs } from '../types'
import { cn, formatRelativeTime } from '../lib/utils'

// ── Metadados de evento ───────────────────────────────────────────────────────

const EVENT_META: Record<string, {
  icon: React.ReactNode
  label: string
  color: string
  badge: string
}> = {
  temperature_change: { icon: <Thermometer className="h-3.5 w-3.5" />, label: 'Temperatura',    color: 'text-blue-600',   badge: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300' },
  device_power:       { icon: <Zap className="h-3.5 w-3.5" />,         label: 'Liga/Desliga',    color: 'text-gray-600',   badge: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300' },
  mode_change:        { icon: <ToggleLeft className="h-3.5 w-3.5" />,   label: 'Modo',            color: 'text-purple-600', badge: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300' },
  ai_analysis:        { icon: <Bot className="h-3.5 w-3.5" />,          label: 'Análise IA',      color: 'text-violet-600', badge: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300' },
  ai_suggestion:      { icon: <Bot className="h-3.5 w-3.5" />,          label: 'Sugestão IA',     color: 'text-violet-500', badge: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300' },
  automation_exec:    { icon: <Activity className="h-3.5 w-3.5" />,     label: 'Automação',       color: 'text-green-600',  badge: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' },
  guardrail_block:    { icon: <Shield className="h-3.5 w-3.5" />,       label: 'Bloqueio',        color: 'text-orange-600', badge: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300' },
  kill_switch:        { icon: <ShieldOff className="h-3.5 w-3.5" />,    label: 'Kill Switch',     color: 'text-red-600',    badge: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300' },
  zone_trigger:       { icon: <Zap className="h-3.5 w-3.5" />,          label: 'Gatilho Manual',  color: 'text-teal-600',   badge: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300' },
}

const SEV_BADGE: Record<string, string> = {
  CRITICAL: 'bg-red-600 text-white',
  HIGH:     'bg-orange-500 text-white',
  MEDIUM:   'bg-yellow-500 text-white',
  LOW:      'bg-blue-500 text-white',
}

const ORIGIN_LABEL: Record<string, string> = {
  user:       'Usuário',
  ai:         'IA',
  automation: 'Automação',
  system:     'Sistema',
}

const STATUS_BADGE: Record<string, string> = {
  suggestion:           'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  pending_verification: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300',
  verified_success:     'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
  verified_failure:     'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  blocked:              'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
}

const STATUS_LABEL: Record<string, string> = {
  suggestion:           'Sugestão',
  pending_verification: 'Aguardando…',
  verified_success:     'Eficaz ✓',
  verified_failure:     'Sem efeito ✗',
  blocked:              'Bloqueado',
}

// ── Detalhe modal ─────────────────────────────────────────────────────────────

function DetailModal({ entry, onClose }: { entry: LogEntry; onClose: () => void }) {
  const m = EVENT_META[entry.event_type] ?? EVENT_META.temperature_change
  const d = entry.details as Record<string, unknown>

  const rows: { label: string; value: unknown }[] = [
    { label: 'ID', value: entry.id },
    { label: 'Origem', value: ORIGIN_LABEL[entry.origin] ?? entry.origin },
    { label: 'Tipo', value: m.label },
    ...(entry.store_name   ? [{ label: 'Loja', value: entry.store_name }] : []),
    ...(entry.zone_label ?? entry.zone_key ? [{ label: 'Zona', value: entry.zone_label ?? entry.zone_key }] : []),
    ...(entry.sector_name  ? [{ label: 'Setor', value: entry.sector_name }] : []),
    ...(entry.device_name  ? [{ label: 'Equipamento', value: entry.device_name }] : []),
    ...(entry.user_name    ? [{ label: 'Usuário', value: entry.user_name }] : []),
    ...(entry.old_value != null ? [{ label: 'Antes', value: entry.old_value }] : []),
    ...(entry.new_value != null ? [{ label: 'Depois', value: entry.new_value }] : []),
    ...(entry.severity     ? [{ label: 'Severidade', value: entry.severity }] : []),
    ...(entry.status       ? [{ label: 'Status', value: STATUS_LABEL[entry.status] ?? entry.status }] : []),
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white dark:bg-gray-900 shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-800">
          <div className="flex items-center gap-2">
            <span className={cn('rounded px-2 py-1 text-xs font-medium', m.badge)}>{m.label}</span>
            <span className="text-sm font-semibold text-gray-900 dark:text-white">{entry.summary}</span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div className="p-5 max-h-[70vh] overflow-y-auto space-y-4">
          {/* Campos principais */}
          <div className="grid grid-cols-2 gap-2">
            {rows.map(r => (
              <div key={r.label} className="rounded-lg bg-gray-50 dark:bg-gray-800 px-3 py-2">
                <div className="text-xs text-gray-400 mb-0.5">{r.label}</div>
                <div className="text-sm font-medium text-gray-800 dark:text-gray-200 break-all">{String(r.value ?? '—')}</div>
              </div>
            ))}
          </div>

          {/* Contexto IA (ai_analysis) */}
          {entry.event_type === 'ai_analysis' && (
            <div className="space-y-2">
              {Boolean(d.root_cause) && (
                <div>
                  <p className="text-xs font-bold uppercase text-gray-400 mb-1">Causa raiz</p>
                  <p className="text-sm text-gray-700 dark:text-gray-300">{String(d.root_cause)}</p>
                </div>
              )}
              {Boolean(d.recommended_action) && (
                <div>
                  <p className="text-xs font-bold uppercase text-gray-400 mb-1">Ação recomendada</p>
                  <p className="text-sm text-gray-700 dark:text-gray-300">{String(d.recommended_action)}</p>
                </div>
              )}
            </div>
          )}

          {/* Automação: antes/depois */}
          {entry.source === 'automation' && (d.temp_before != null || d.temp_after != null) && (
            <div>
              <p className="text-xs font-bold uppercase text-gray-400 mb-1.5">Temperatura</p>
              <div className="flex items-center gap-3 text-sm">
                <span className="font-mono">{d.temp_before != null ? `${Number(d.temp_before as number).toFixed(1)}°C` : '—'}</span>
                <ChevronRight className="h-4 w-4 text-gray-400" />
                <span className="font-mono">{d.temp_after != null ? `${Number(d.temp_after as number).toFixed(1)}°C` : 'aguardando…'}</span>
              </div>
            </div>
          )}

          {/* Motivo / reason */}
          {Boolean(d.reason) && (
            <div>
              <p className="text-xs font-bold uppercase text-gray-400 mb-1">Motivo</p>
              <p className="text-sm text-gray-600 dark:text-gray-400">{String(d.reason)}</p>
            </div>
          )}

          <p className="text-xs text-gray-400">
            {new Date(entry.created_at).toLocaleString('pt-BR')}
          </p>
        </div>
      </div>
    </div>
  )
}

// ── KPI Card ──────────────────────────────────────────────────────────────────

function KPICard({ label, value, sub, color }: { label: string; value: number | string; sub?: string; color?: string }) {
  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4">
      <div className={cn('text-2xl font-bold', color ?? 'text-gray-900 dark:text-white')}>{value}</div>
      <div className="text-xs font-medium text-gray-600 dark:text-gray-400 mt-0.5">{label}</div>
      {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}

// ── Log row ───────────────────────────────────────────────────────────────────

function LogRow({ entry, onSelect }: { entry: LogEntry; onSelect: (e: LogEntry) => void }) {
  const m = EVENT_META[entry.event_type] ?? { icon: <Activity className="h-3.5 w-3.5" />, label: entry.event_type, badge: 'bg-gray-100 text-gray-600' }

  return (
    <tr
      className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer transition-colors"
      onClick={() => onSelect(entry)}
    >
      <td className="py-2.5 pl-4 pr-2 w-32 whitespace-nowrap">
        <div className="flex items-center gap-1 text-xs text-gray-500">
          <Clock className="h-3 w-3 shrink-0" />
          {formatRelativeTime(entry.created_at)}
        </div>
      </td>
      <td className="py-2.5 px-2">
        <span className={cn('inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium', m.badge)}>
          {m.icon}{m.label}
        </span>
      </td>
      <td className="py-2.5 px-2 text-xs text-gray-500">{ORIGIN_LABEL[entry.origin] ?? entry.origin}</td>
      <td className="py-2.5 px-2">
        <p className="text-sm text-gray-800 dark:text-gray-200 line-clamp-1">{entry.summary}</p>
        <div className="flex flex-wrap gap-1 mt-0.5">
          {entry.store_name && <Tag>{entry.store_name}</Tag>}
          {(entry.zone_label ?? entry.zone_key) && <Tag>{entry.zone_label ?? entry.zone_key}</Tag>}
          {entry.device_name && <Tag>{entry.device_name}</Tag>}
          {entry.user_name && <Tag>{entry.user_name}</Tag>}
        </div>
      </td>
      <td className="py-2.5 px-2 w-20">
        {entry.severity && (
          <span className={cn('rounded px-1.5 py-0.5 text-xs font-bold', SEV_BADGE[entry.severity])}>
            {entry.severity}
          </span>
        )}
      </td>
      <td className="py-2.5 px-2 w-28">
        {entry.status && (
          <span className={cn('rounded px-1.5 py-0.5 text-xs font-medium', STATUS_BADGE[entry.status] ?? 'bg-gray-100 text-gray-500')}>
            {STATUS_LABEL[entry.status] ?? entry.status}
          </span>
        )}
      </td>
      <td className="py-2.5 pr-4 pl-2 w-8 text-right">
        <ChevronRight className="h-4 w-4 text-gray-400 inline" />
      </td>
    </tr>
  )
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-xs text-gray-500">
      {children}
    </span>
  )
}

// ── Página principal ──────────────────────────────────────────────────────────

const PAGE_SIZE = 100

export default function LogsPage() {
  const [selected, setSelected] = useState<LogEntry | null>(null)
  const [showFilters, setShowFilters] = useState(false)
  const [offset, setOffset] = useState(0)

  const [filters, setFilters] = useState({
    event_type: '',
    origin: '',
    severity: '',
    status: '',
    zone_key: '',
    store_id: '',
    date_from: '',
    date_to: '',
  })
  const [activeFilters, setActiveFilters] = useState({ ...filters })

  const { data: storesData } = useQuery({
    queryKey: ['stores'],
    queryFn: () => storesApi.list(),
  })
  const stores: { id: string; name: string }[] = storesData ?? []

  const { data: kpisData } = useQuery<LogKPIs>({
    queryKey: ['logs-kpis', activeFilters.store_id, activeFilters.date_from, activeFilters.date_to],
    queryFn: () => logsApi.kpis({
      store_id: activeFilters.store_id || undefined,
      date_from: activeFilters.date_from || undefined,
      date_to: activeFilters.date_to || undefined,
    }),
  })

  const { data: logsData, isLoading, isFetching } = useQuery({
    queryKey: ['logs', offset, activeFilters],
    queryFn: () => logsApi.list({
      limit: PAGE_SIZE,
      offset,
      event_type: activeFilters.event_type || undefined,
      origin: activeFilters.origin || undefined,
      severity: activeFilters.severity || undefined,
      status: activeFilters.status || undefined,
      zone_key: activeFilters.zone_key || undefined,
      store_id: activeFilters.store_id || undefined,
      date_from: activeFilters.date_from || undefined,
      date_to: activeFilters.date_to || undefined,
    }),
    placeholderData: (prev: unknown) => prev,
  })

  const entries: LogEntry[] = logsData?.items ?? []
  const total: number = logsData?.total ?? 0
  const kpis = kpisData

  const apply = () => { setActiveFilters({ ...filters }); setOffset(0) }
  const clear  = () => { const e = { event_type:'',origin:'',severity:'',status:'',zone_key:'',store_id:'',date_from:'',date_to:'' }; setFilters(e); setActiveFilters(e); setOffset(0) }

  const activeCount = Object.values(activeFilters).filter(Boolean).length

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Activity className="h-5 w-5 text-blue-500" />
            Logs & Rastreabilidade
          </h1>
          <p className="text-xs text-gray-500">Histórico completo de ações da IA, automação e usuários</p>
        </div>
        <button
          onClick={() => setShowFilters(v => !v)}
          className={cn(
            'flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
            showFilters
              ? 'border-blue-500 bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400'
              : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800',
          )}
        >
          <Search className="h-3.5 w-3.5" />
          Filtros
          {activeCount > 0 && (
            <span className="ml-1 rounded-full bg-blue-500 text-white px-1.5 py-0.5 text-xs leading-none">{activeCount}</span>
          )}
          <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showFilters && 'rotate-180')} />
        </button>
      </div>

      {/* KPIs */}
      {kpis && (
        <div className="px-6 py-4 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3 bg-gray-50 dark:bg-gray-950 border-b border-gray-200 dark:border-gray-800">
          <KPICard label="Sugestões IA"    value={kpis.ai_suggestions}   color="text-violet-600" />
          <KPICard label="Auto executadas" value={kpis.auto_executed}     color="text-green-600" />
          <KPICard label="Eficazes"        value={kpis.verified_success}  color="text-green-600" sub={`${kpis.auto_executed > 0 ? Math.round(kpis.verified_success / kpis.auto_executed * 100) : 0}%`} />
          <KPICard label="Sem efeito"      value={kpis.verified_failure}  color="text-red-500" />
          <KPICard label="Bloqueios"       value={kpis.guardrail_blocks}  color="text-orange-500" />
          <KPICard label="Controles manuais" value={kpis.manual_controls} color="text-blue-600" />
          <KPICard label="Análises IA"     value={kpis.ai_analyses}       color="text-violet-600" sub={`${kpis.ai_critical} críticas`} />
          <KPICard label="Recuperação média" value={kpis.avg_recovery_minutes != null ? `${kpis.avg_recovery_minutes}min` : '—'} color="text-teal-600" />
        </div>
      )}

      {/* Filtros avançados */}
      {showFilters && (
        <div className="px-6 py-4 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
            <FilterSelect label="Tipo de evento" value={filters.event_type} onChange={v => setFilters(f => ({ ...f, event_type: v }))}>
              <option value="">Todos</option>
              <option value="temperature_change">Temperatura</option>
              <option value="mode_change">Modo</option>
              <option value="ai_analysis">Análise IA</option>
              <option value="ai_suggestion">Sugestão IA</option>
              <option value="automation_exec">Automação</option>
              <option value="guardrail_block">Bloqueio</option>
              <option value="kill_switch">Kill Switch</option>
            </FilterSelect>
            <FilterSelect label="Origem" value={filters.origin} onChange={v => setFilters(f => ({ ...f, origin: v }))}>
              <option value="">Todas</option>
              <option value="user">Usuário</option>
              <option value="ai">IA</option>
              <option value="automation">Automação</option>
              <option value="system">Sistema</option>
            </FilterSelect>
            <FilterSelect label="Severidade" value={filters.severity} onChange={v => setFilters(f => ({ ...f, severity: v }))}>
              <option value="">Todas</option>
              <option value="CRITICAL">Crítico</option>
              <option value="HIGH">Alto</option>
              <option value="MEDIUM">Médio</option>
              <option value="LOW">Baixo</option>
            </FilterSelect>
            <FilterSelect label="Status" value={filters.status} onChange={v => setFilters(f => ({ ...f, status: v }))}>
              <option value="">Todos</option>
              <option value="suggestion">Sugestão</option>
              <option value="pending_verification">Aguardando</option>
              <option value="verified_success">Eficaz</option>
              <option value="verified_failure">Sem efeito</option>
              <option value="blocked">Bloqueado</option>
            </FilterSelect>
            <FilterSelect label="Loja" value={filters.store_id} onChange={v => setFilters(f => ({ ...f, store_id: v }))}>
              <option value="">Todas</option>
              {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </FilterSelect>
            <FilterInput label="Zona" placeholder="ex: farmacia" value={filters.zone_key} onChange={v => setFilters(f => ({ ...f, zone_key: v }))} />
            <FilterInput label="De" type="datetime-local" value={filters.date_from} onChange={v => setFilters(f => ({ ...f, date_from: v }))} />
            <FilterInput label="Até" type="datetime-local" value={filters.date_to} onChange={v => setFilters(f => ({ ...f, date_to: v }))} />
          </div>
          <div className="flex gap-2">
            <button onClick={apply} className="rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-500">
              Aplicar filtros
            </button>
            {activeCount > 0 && (
              <button onClick={clear} className="rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800">
                Limpar
              </button>
            )}
          </div>
        </div>
      )}

      {/* Tabela */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-gray-400">
            <RefreshCw className="h-5 w-5 animate-spin mr-2" /> Carregando logs…
          </div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-gray-400">
            <Activity className="h-10 w-10 mb-3" />
            <p>Nenhum log encontrado com os filtros aplicados.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-50 dark:bg-gray-950 border-b border-gray-200 dark:border-gray-800">
              <tr>
                <th className="py-2 pl-4 pr-2 text-left text-xs font-semibold text-gray-500 w-32">Quando</th>
                <th className="py-2 px-2 text-left text-xs font-semibold text-gray-500">Tipo</th>
                <th className="py-2 px-2 text-left text-xs font-semibold text-gray-500">Origem</th>
                <th className="py-2 px-2 text-left text-xs font-semibold text-gray-500">Descrição</th>
                <th className="py-2 px-2 text-left text-xs font-semibold text-gray-500 w-20">Severidade</th>
                <th className="py-2 px-2 text-left text-xs font-semibold text-gray-500 w-28">Status</th>
                <th className="py-2 pr-4 pl-2 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {entries.map(e => (
                <LogRow key={`${e.source}-${e.id}`} entry={e} onSelect={setSelected} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Paginação */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between px-6 py-3 border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
          <span className="text-xs text-gray-500">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} de {total} registros
            {isFetching && <RefreshCw className="h-3 w-3 animate-spin inline ml-1" />}
          </span>
          <div className="flex gap-2">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
              className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-1 text-xs font-medium disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              ← Anterior
            </button>
            <button
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(o => o + PAGE_SIZE)}
              className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-1 text-xs font-medium disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Próxima →
            </button>
          </div>
        </div>
      )}

      {/* Top Zonas & Equipamentos */}
      {kpis && (kpis.top_zones.length > 0 || kpis.top_devices.length > 0) && (
        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 grid grid-cols-1 sm:grid-cols-2 gap-4">
          {kpis.top_zones.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase text-gray-400 mb-2">Zonas com mais intervenções</p>
              <div className="space-y-1">
                {kpis.top_zones.map(z => (
                  <div key={z.zone_key} className="flex items-center gap-2">
                    <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="bg-green-500 h-full rounded-full"
                        style={{ width: `${Math.min(100, (z.count / (kpis.top_zones[0]?.count || 1)) * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-600 dark:text-gray-400 w-36 truncate">{z.zone_label}</span>
                    <span className="text-xs font-semibold text-gray-800 dark:text-gray-200 w-6 text-right">{z.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {kpis.top_devices.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase text-gray-400 mb-2">Equipamentos com mais reincidência</p>
              <div className="space-y-1">
                {kpis.top_devices.map(d => (
                  <div key={d.device_id} className="flex items-center gap-2">
                    <div className="flex-1 bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden">
                      <div
                        className="bg-orange-400 h-full rounded-full"
                        style={{ width: `${Math.min(100, (d.count / (kpis.top_devices[0]?.count || 1)) * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-600 dark:text-gray-400 w-36 truncate">{d.device_name}</span>
                    <span className="text-xs font-semibold text-gray-800 dark:text-gray-200 w-6 text-right">{d.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {selected && <DetailModal entry={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function FilterSelect({ label, value, onChange, children }: {
  label: string; value: string; onChange: (v: string) => void; children: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-gray-500 font-medium">{label}</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-xs text-gray-800 dark:text-gray-200 px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400"
      >
        {children}
      </select>
    </div>
  )
}

function FilterInput({ label, value, onChange, placeholder, type = 'text' }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-gray-500 font-medium">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-xs text-gray-800 dark:text-gray-200 px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400"
      />
    </div>
  )
}
