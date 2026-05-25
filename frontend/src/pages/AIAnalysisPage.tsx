import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, Bot, CheckCircle, ChevronRight, Clock,
  Cpu, RefreshCw, Thermometer, TrendingUp, Wifi, WifiOff, Wrench, Zap,
} from 'lucide-react'
import { aiApi } from '../api/client'
import type { AIAnalysis, AIStatus, ZoneAIAnalysis } from '../types'
import { cn, formatRelativeTime } from '../lib/utils'

const SEV_META: Record<string, { label: string; bg: string; text: string; border: string; badge: string }> = {
  CRITICAL: { label: 'Crítico',  bg: 'bg-red-50 dark:bg-red-950/30',    text: 'text-red-700 dark:text-red-300',    border: 'border-red-300 dark:border-red-800',    badge: 'bg-red-600 text-white' },
  HIGH:     { label: 'Alto',     bg: 'bg-orange-50 dark:bg-orange-950/30', text: 'text-orange-700 dark:text-orange-300', border: 'border-orange-300 dark:border-orange-700', badge: 'bg-orange-500 text-white' },
  MEDIUM:   { label: 'Médio',    bg: 'bg-yellow-50 dark:bg-yellow-950/20', text: 'text-yellow-700 dark:text-yellow-300', border: 'border-yellow-300 dark:border-yellow-700', badge: 'bg-yellow-500 text-white' },
  LOW:      { label: 'Baixo',    bg: 'bg-blue-50 dark:bg-blue-950/20',   text: 'text-blue-700 dark:text-blue-300',   border: 'border-blue-200 dark:border-blue-800',   badge: 'bg-blue-500 text-white' },
}

const URGENCY_LABEL = (h: number) => {
  if (h === 0) return { label: 'Imediato', cls: 'text-red-600 font-bold' }
  if (h <= 8)  return { label: `Hoje (${h}h)`, cls: 'text-orange-500 font-semibold' }
  if (h <= 48) return { label: `${h}h`, cls: 'text-yellow-600' }
  return { label: `${Math.round(h / 24)}d`, cls: 'text-gray-500' }
}

function DetailModal({ analysis, onClose }: { analysis: AIAnalysis; onClose: () => void }) {
  const m = SEV_META[analysis.severity || 'LOW']
  const delta = analysis.temperature != null && analysis.setpoint_cool != null
    ? (analysis.temperature - analysis.setpoint_cool).toFixed(1)
    : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white dark:bg-gray-900 shadow-2xl overflow-hidden">
        <div className={cn('flex items-center justify-between px-5 py-3', m.bg, m.border, 'border-b')}>
          <div className="flex items-center gap-2">
            <span className={cn('rounded px-2 py-0.5 text-xs font-bold', m.badge)}>{m.label}</span>
            <span className="font-semibold text-gray-900 dark:text-white">{analysis.device_name}</span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none">×</button>
        </div>

        <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
          {/* Situação atual */}
          <section>
            <h3 className="text-xs font-bold uppercase text-gray-400 mb-2">Situação atual</h3>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Temperatura" value={analysis.temperature != null ? `${analysis.temperature.toFixed(1)}°C` : '—'} cls={analysis.temperature && analysis.setpoint_cool && analysis.temperature > analysis.setpoint_cool + 2 ? 'text-red-600' : undefined} />
              <Stat label="Setpoint" value={analysis.setpoint_cool != null ? `${analysis.setpoint_cool}°C` : '—'} />
              <Stat label="Delta" value={delta != null ? `${Number(delta) > 0 ? '+' : ''}${delta}°C` : '—'} cls={Number(delta || 0) > 2 ? 'text-orange-600' : undefined} />
              <Stat label="Loja" value={analysis.store_name || '—'} />
              <Stat label="Setor" value={analysis.sector_name || '—'} />
              <Stat label="Urgência" value={URGENCY_LABEL(analysis.urgency_hours).label} cls={URGENCY_LABEL(analysis.urgency_hours).cls} />
            </div>
          </section>

          {/* Causa raiz */}
          <Section icon={<AlertTriangle className="h-4 w-4 text-orange-500" />} title="Causa raiz provável">
            <p className="text-sm text-gray-700 dark:text-gray-300">{analysis.root_cause || '—'}</p>
          </Section>

          {/* Diagnóstico */}
          <Section icon={<Activity className="h-4 w-4 text-blue-500" />} title="Diagnóstico técnico">
            <p className="text-sm text-gray-700 dark:text-gray-300">{analysis.diagnosis || '—'}</p>
          </Section>

          {/* Ação recomendada */}
          <Section icon={<Wrench className="h-4 w-4 text-purple-500" />} title="Ação recomendada ao técnico">
            <p className="text-sm font-medium text-gray-800 dark:text-gray-200">{analysis.recommended_action || '—'}</p>
          </Section>

          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-400">Análise gerada: {formatRelativeTime(analysis.analyzed_at)}</p>
            <span className={cn('rounded px-2 py-0.5 text-xs font-medium',
              analysis.analysis_source === 'llm'
                ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300'
                : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
            )}>
              {analysis.analysis_source === 'llm' ? '🤖 LLM' : analysis.analysis_source === 'deterministic' ? '⚙️ Determinístico' : '📏 Regras'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="rounded-lg bg-gray-50 dark:bg-gray-800 p-2">
      <div className="text-xs text-gray-400">{label}</div>
      <div className={cn('text-sm font-semibold text-gray-900 dark:text-white truncate', cls)}>{value}</div>
    </div>
  )
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase text-gray-400 mb-1.5">{icon}{title}</h3>
      {children}
    </section>
  )
}

function ZoneAnalysisCard({ z, onTrigger, isPending }: {
  z: ZoneAIAnalysis
  onTrigger: (storeId: string, zoneKey: string) => void
  isPending: boolean
}) {
  const m = SEV_META[z.severity || 'LOW']
  const urg = URGENCY_LABEL(z.urgency_hours)
  const [expanded, setExpanded] = useState(false)

  return (
    <div className={cn('rounded-xl border p-4 space-y-3 transition-shadow hover:shadow-md', m.bg, m.border)}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
            <span className={cn('rounded px-1.5 py-0.5 text-xs font-bold', m.badge)}>{m.label}</span>
            <span className="rounded bg-indigo-100 dark:bg-indigo-900/30 px-1.5 py-0.5 text-xs font-medium text-indigo-700 dark:text-indigo-300">
              Zona
            </span>
            <span className={cn('rounded px-1.5 py-0.5 text-xs font-medium',
              z.analysis_source === 'llm'
                ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300'
                : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
            )}>
              {z.analysis_source === 'llm' ? 'IA' : z.analysis_source === 'fallback' ? 'Regras' : 'Determinístico'}
            </span>
          </div>
          <p className="font-semibold text-gray-900 dark:text-white truncate">{z.zone_label}</p>
          <p className="text-xs text-gray-500">{z.devices_analyzed} dispositivo(s) · status {z.zone_status}</p>
        </div>
        <div className="shrink-0 text-right space-y-0.5">
          {z.trend_c_per_hour !== null && (
            <div className={cn('flex items-center gap-1 text-xs justify-end',
              (z.trend_c_per_hour ?? 0) > 1 ? 'text-red-600' : (z.trend_c_per_hour ?? 0) < -1 ? 'text-green-600' : 'text-gray-500'
            )}>
              <TrendingUp className="h-3 w-3" />
              {z.trend_c_per_hour !== null ? `${z.trend_c_per_hour > 0 ? '+' : ''}${z.trend_c_per_hour.toFixed(1)}°C/h` : '—'}
            </div>
          )}
          <div className="flex items-center gap-1 text-xs text-gray-400 justify-end">
            <Clock className="h-3 w-3" />
            <span className={urg.cls}>{urg.label}</span>
          </div>
        </div>
      </div>

      <p className="text-xs text-gray-700 dark:text-gray-300 line-clamp-2">{z.diagnosis || z.root_cause}</p>

      {expanded && (
        <div className="space-y-2 pt-1 border-t border-gray-200 dark:border-gray-700">
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase mb-0.5">Causa raiz</p>
            <p className="text-xs text-gray-700 dark:text-gray-300">{z.root_cause}</p>
          </div>
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase mb-0.5">Ação recomendada</p>
            <p className="text-xs font-medium text-gray-800 dark:text-gray-200">{z.recommended_action}</p>
          </div>
          <p className="text-xs text-gray-400">Analisado: {formatRelativeTime(z.analyzed_at)}</p>
        </div>
      )}

      <div className="flex items-center justify-between pt-1">
        <button
          onClick={() => setExpanded(e => !e)}
          className={cn('flex items-center gap-1 text-xs font-medium hover:underline', m.text)}
        >
          {expanded ? 'Recolher' : 'Ver detalhes'} <ChevronRight className={cn('h-3 w-3 transition-transform', expanded && 'rotate-90')} />
        </button>
        <button
          onClick={() => onTrigger(z.store_id, z.zone_key)}
          disabled={isPending}
          className="flex items-center gap-1 text-xs text-gray-500 hover:text-purple-600 disabled:opacity-40"
        >
          <RefreshCw className={cn('h-3 w-3', isPending && 'animate-spin')} />
          Re-analisar
        </button>
      </div>
    </div>
  )
}

export default function AIAnalysisPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<'devices' | 'zones'>('devices')
  const [selected, setSelected] = useState<AIAnalysis | null>(null)
  const [severityFilter, setSeverityFilter] = useState<string>('all')
  const [chatMessage, setChatMessage] = useState('')
  const [chatFeedback, setChatFeedback] = useState<string | null>(null)

  const { data: statusData } = useQuery<AIStatus>({
    queryKey: ['ai-status'],
    queryFn: () => aiApi.status(),
    refetchInterval: 30_000,
  })

  const { data: analysesData, isLoading } = useQuery({
    queryKey: ['ai-analyses'],
    queryFn: () => aiApi.analyses(),
    refetchInterval: 60_000,
  })

  const triggerMutation = useMutation({
    mutationFn: () => aiApi.trigger(),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['ai-analyses'] }), 5000),
  })

  const { data: zoneAnalysesData, isLoading: isLoadingZones } = useQuery({
    queryKey: ['ai-zone-analyses'],
    queryFn: () => aiApi.zoneAnalyses(),
    refetchInterval: 60_000,
  })
  const { data: chatPromptData } = useQuery({
    queryKey: ['ai-chat-command-prompt'],
    queryFn: () => aiApi.chatCommandPrompt(),
  })

  const [pendingZone, setPendingZone] = useState<string | null>(null)
  const triggerZoneMutation = useMutation({
    mutationFn: ({ storeId, zoneKey }: { storeId: string; zoneKey: string }) =>
      aiApi.analyzeZone(storeId, zoneKey),
    onMutate: ({ zoneKey }) => setPendingZone(zoneKey),
    onSettled: () => {
      setPendingZone(null)
      setTimeout(() => qc.invalidateQueries({ queryKey: ['ai-zone-analyses'] }), 8000)
    },
  })
  const chatCommandMutation = useMutation({
    mutationFn: (message: string) => aiApi.chatCommand(message),
    onSuccess: (data) => {
      setChatFeedback(
        `✅ ${data.success}/${data.total} aplicados` +
        (data.skipped ? ` · ${data.skipped} bloqueados/no-op` : '') +
        (data.failed ? ` · ${data.failed} falharam` : '')
      )
      setChatMessage('')
    },
    onError: (error: any) => {
      setChatFeedback(`❌ ${error?.response?.data?.detail || 'Erro ao executar comando'}`)
    },
  })

  const analyses: AIAnalysis[] = analysesData?.analyses ?? []
  const sevOrder: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
  const sorted = [...analyses].sort((a, b) =>
    (sevOrder[a.severity || 'LOW'] ?? 9) - (sevOrder[b.severity || 'LOW'] ?? 9) ||
    a.urgency_hours - b.urgency_hours
  )

  const filtered = severityFilter === 'all' ? sorted : sorted.filter(a => a.severity === severityFilter)

  const counts = analyses.reduce((acc, a) => {
    acc[a.severity || 'LOW'] = (acc[a.severity || 'LOW'] || 0) + 1
    return acc
  }, {} as Record<string, number>)

  const zoneAnalyses: ZoneAIAnalysis[] = zoneAnalysesData?.analyses ?? []
  const zoneSorted = [...zoneAnalyses].sort((a, b) =>
    (sevOrder[a.severity || 'LOW'] ?? 9) - (sevOrder[b.severity || 'LOW'] ?? 9)
  )
  const zoneFiltered = severityFilter === 'all' ? zoneSorted : zoneSorted.filter(z => z.severity === severityFilter)

  const ollama = statusData?.ollama_available

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <div className="flex items-center gap-3">
          <Bot className="h-6 w-6 text-purple-500" />
          <div>
            <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Análise de IA</h1>
            <p className="text-xs text-gray-500">Diagnóstico automático de anomalias térmicas</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden md:flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-2 py-1.5">
            <input
              value={chatMessage}
              onChange={(e) => setChatMessage(e.target.value)}
              placeholder='Ex.: "todos os ar com 25 graus"'
              className="w-72 bg-transparent text-xs outline-none text-gray-800 dark:text-gray-200"
            />
            <button
              onClick={() => chatMessage.trim() && chatCommandMutation.mutate(chatMessage)}
              disabled={chatCommandMutation.isPending || !chatMessage.trim()}
              className="rounded bg-purple-600 px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
            >
              {chatCommandMutation.isPending ? 'Aplicando...' : 'Executar'}
            </button>
          </div>
          <div className={cn('flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium',
            ollama ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-gray-100 text-gray-500 dark:bg-gray-800')}>
            {ollama ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
            {ollama ? 'Ollama online' : 'Ollama offline'}
          </div>
          {tab === 'devices' && (
            <button
              onClick={() => triggerMutation.mutate()}
              disabled={triggerMutation.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-500 disabled:opacity-50"
            >
              {triggerMutation.isPending
                ? <><RefreshCw className="h-3.5 w-3.5 animate-spin" /> Analisando…</>
                : <><Zap className="h-3.5 w-3.5" /> Analisar agora</>
              }
            </button>
          )}
        </div>
      </div>
      {chatFeedback && (
        <div className="px-6 py-2 text-xs text-gray-700 dark:text-gray-200 border-b border-gray-200 dark:border-gray-800 bg-purple-50/60 dark:bg-purple-950/20">
          {chatFeedback}
        </div>
      )}
      {chatPromptData?.system_prompt && (
        <div className="px-6 py-2 text-[11px] text-gray-600 dark:text-gray-300 border-b border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900/50">
          <span className="font-semibold">Prompt (base da IA): </span>
          <span className="opacity-90">use este template para evoluir o chat com escopo global/loja/zona.</span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 px-6 pt-3 pb-0 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <button
          onClick={() => setTab('devices')}
          className={cn(
            'flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors',
            tab === 'devices'
              ? 'border-purple-500 text-purple-600 dark:text-purple-400'
              : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          )}
        >
          <Thermometer className="h-4 w-4" />
          Dispositivos
          {analyses.length > 0 && (
            <span className="rounded-full bg-purple-100 dark:bg-purple-900/40 px-1.5 py-0.5 text-xs text-purple-700 dark:text-purple-300">
              {analyses.length}
            </span>
          )}
        </button>
        <button
          onClick={() => setTab('zones')}
          className={cn(
            'flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-t-lg border-b-2 transition-colors',
            tab === 'zones'
              ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
              : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          )}
        >
          <Cpu className="h-4 w-4" />
          Zonas
          {zoneAnalyses.length > 0 && (
            <span className="rounded-full bg-indigo-100 dark:bg-indigo-900/40 px-1.5 py-0.5 text-xs text-indigo-700 dark:text-indigo-300">
              {zoneAnalyses.length}
            </span>
          )}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
        {tab === 'devices' ? (
          <>
            {/* KPI summary */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              {(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map(sev => {
                const m = SEV_META[sev]
                const n = counts[sev] || 0
                return (
                  <button
                    key={sev}
                    onClick={() => setSeverityFilter(severityFilter === sev ? 'all' : sev)}
                    className={cn(
                      'rounded-xl border p-3 text-center transition-all',
                      m.bg, m.border,
                      severityFilter === sev ? 'ring-2 ring-offset-1 ring-purple-500' : ''
                    )}
                  >
                    <div className={cn('text-2xl font-bold', m.text)}>{n}</div>
                    <div className={cn('text-xs font-medium', m.text)}>{m.label}</div>
                  </button>
                )
              })}
              <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 p-3 text-center">
                <div className="text-2xl font-bold text-green-600 dark:text-green-400">{analysesData?.total ?? 0}</div>
                <div className="text-xs font-medium text-gray-500">Analisados</div>
              </div>
            </div>

            {/* Filtro rápido */}
            {severityFilter !== 'all' && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-500">Filtrando por:</span>
                <span className={cn('rounded px-2 py-0.5 text-xs font-bold', SEV_META[severityFilter]?.badge)}>
                  {SEV_META[severityFilter]?.label}
                </span>
                <button onClick={() => setSeverityFilter('all')} className="text-xs text-gray-400 hover:text-gray-600 underline">
                  limpar
                </button>
              </div>
            )}

            {/* Lista de análises de dispositivos */}
            {isLoading ? (
              <div className="flex items-center justify-center py-20 text-gray-400">
                <RefreshCw className="h-5 w-5 animate-spin mr-2" /> Carregando análises…
              </div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-gray-400">
                <CheckCircle className="h-10 w-10 mb-3 text-green-400" />
                <p className="font-medium text-gray-600 dark:text-gray-300">
                  {severityFilter !== 'all' ? `Nenhuma anomalia ${SEV_META[severityFilter]?.label.toLowerCase()}` : 'Nenhuma anomalia detectada'}
                </p>
                <p className="text-sm">Todos os equipamentos monitorados estão dentro da faixa normal.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {filtered.map(a => {
                  const m = SEV_META[a.severity || 'LOW']
                  const urg = URGENCY_LABEL(a.urgency_hours)
                  const delta = a.temperature != null && a.setpoint_cool != null
                    ? a.temperature - a.setpoint_cool
                    : null
                  return (
                    <div key={a.device_id} className={cn('rounded-xl border p-4 space-y-3 transition-shadow hover:shadow-md', m.bg, m.border)}>
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-1.5 mb-0.5">
                            <span className={cn('rounded px-1.5 py-0.5 text-xs font-bold', m.badge)}>{m.label}</span>
                            {a.email_worthy && (
                              <span className="rounded bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 text-xs text-red-600 dark:text-red-400 font-medium">Email</span>
                            )}
                            <span className={cn('rounded px-1.5 py-0.5 text-xs font-medium',
                              a.analysis_source === 'llm'
                                ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300'
                                : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
                            )}>
                              {a.analysis_source === 'llm' ? 'IA' : a.analysis_source === 'deterministic' ? 'Determinístico' : 'Regras'}
                            </span>
                          </div>
                          <p className="font-semibold text-gray-900 dark:text-white truncate">{a.device_name}</p>
                          <p className="text-xs text-gray-500 truncate">{a.store_name}{a.sector_name ? ` › ${a.sector_name}` : ''}</p>
                        </div>
                        <div className="shrink-0 text-right">
                          <div className="flex items-center gap-1 text-xs text-gray-500">
                            <Thermometer className="h-3 w-3" />
                            {a.temperature != null ? `${a.temperature.toFixed(1)}°C` : '—'}
                          </div>
                          {delta != null && (
                            <div className={cn('text-xs font-medium', delta > 3 ? 'text-red-600' : delta > 1 ? 'text-orange-500' : 'text-green-600')}>
                              {delta > 0 ? '+' : ''}{delta.toFixed(1)}°C
                            </div>
                          )}
                        </div>
                      </div>
                      <p className="text-xs text-gray-700 dark:text-gray-300 line-clamp-2">{a.diagnosis || a.root_cause}</p>
                      <div className="flex items-center justify-between pt-1">
                        <div className="flex items-center gap-1 text-xs">
                          <Clock className="h-3 w-3 text-gray-400" />
                          <span className={urg.cls}>{urg.label}</span>
                        </div>
                        <button
                          onClick={() => setSelected(a)}
                          className={cn('flex items-center gap-1 text-xs font-medium hover:underline', m.text)}
                        >
                          Ver detalhes <ChevronRight className="h-3 w-3" />
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </>
        ) : (
          <>
            {/* Filtro rápido zonas */}
            <div className="flex items-center gap-2 flex-wrap">
              {(['all', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] as const).map(sev => (
                <button
                  key={sev}
                  onClick={() => setSeverityFilter(sev)}
                  className={cn(
                    'rounded-full px-3 py-1 text-xs font-medium border transition-all',
                    sev === 'all'
                      ? severityFilter === 'all'
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400'
                      : severityFilter === sev
                        ? cn(SEV_META[sev].badge, 'border-transparent')
                        : cn(SEV_META[sev].bg, SEV_META[sev].border, SEV_META[sev].text)
                  )}
                >
                  {sev === 'all' ? 'Todas' : SEV_META[sev].label}
                  {sev !== 'all' && (
                    <span className="ml-1">
                      {zoneSorted.filter(z => z.severity === sev).length}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {isLoadingZones ? (
              <div className="flex items-center justify-center py-20 text-gray-400">
                <RefreshCw className="h-5 w-5 animate-spin mr-2" /> Carregando análises de zona…
              </div>
            ) : zoneFiltered.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-gray-400">
                <CheckCircle className="h-10 w-10 mb-3 text-green-400" />
                <p className="font-medium text-gray-600 dark:text-gray-300">Nenhuma anomalia de zona detectada</p>
                <p className="text-sm">As análises são geradas automaticamente a cada 30 minutos para zonas com anomalias.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {zoneFiltered.map(z => (
                  <ZoneAnalysisCard
                    key={`${z.store_id}:${z.zone_key}`}
                    z={z}
                    onTrigger={(storeId, zoneKey) => triggerZoneMutation.mutate({ storeId, zoneKey })}
                    isPending={pendingZone === z.zone_key && triggerZoneMutation.isPending}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {selected && <DetailModal analysis={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
