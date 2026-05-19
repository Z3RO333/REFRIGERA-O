import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, Bot, CheckCircle, ChevronRight, Clock,
  RefreshCw, Thermometer, Wifi, WifiOff, Wrench, Zap,
} from 'lucide-react'
import { aiApi } from '../api/client'
import type { AIAnalysis, AIStatus } from '../types'
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

export default function AIAnalysisPage() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<AIAnalysis | null>(null)
  const [severityFilter, setSeverityFilter] = useState<string>('all')

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
          <div className={cn('flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium',
            ollama ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-gray-100 text-gray-500 dark:bg-gray-800')}>
            {ollama ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
            {ollama ? 'Ollama online' : 'Ollama offline'}
          </div>
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
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5">
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

        {/* Lista de análises */}
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
                  {/* Cabeçalho */}
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

                  {/* Diagnóstico */}
                  <p className="text-xs text-gray-700 dark:text-gray-300 line-clamp-2">{a.diagnosis || a.root_cause}</p>

                  {/* Footer */}
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
      </div>

      {selected && <DetailModal analysis={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
