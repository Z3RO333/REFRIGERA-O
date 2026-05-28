import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Building2, AlertTriangle, Zap, Link2, Activity,
  ChevronRight, Thermometer, Wind, Clock, CheckCircle,
  TrendingUp, Shield,
} from 'lucide-react'
import { portfolioApi, alertsApi, logsApi } from '../api/client'
import { useInspectorStore } from '../store/useInspectorStore'
import { cn, formatTime } from '../lib/utils'

// ── Types ──────────────────────────────────────────────────────────────────────
interface StoreRow {
  store_id: string
  store_name: string
  store_code: string
  urgency_score: number
  risk_level: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  alerts_p1: number
  alerts_p2: number
  zones_hot: number
  zones_warm: number
  zones_comfort: number
  zones_cold: number
  zones_total: number
  zones_auto: number
  zones_maintenance: number
  avg_temperature: number | null
  binding_conflicts: number
  actions_in_progress: number
}

interface PortfolioKPIs {
  total_stores: number
  stores_at_risk: number
  binding_conflicts: number
  actions_in_progress: number
  open_p1: number
  open_p2: number
}

// ── Helpers ────────────────────────────────────────────────────────────────────
const RISK_DOT: Record<string, string> = {
  CRITICAL: 'bg-red-500',
  HIGH: 'bg-orange-500',
  MEDIUM: 'bg-yellow-500',
  LOW: 'bg-green-500',
}

const RISK_LABEL: Record<string, string> = {
  CRITICAL: 'Crítico',
  HIGH: 'Alto',
  MEDIUM: 'Médio',
  LOW: 'Baixo',
}

const RISK_BORDER: Record<string, string> = {
  CRITICAL: 'border-red-800/50',
  HIGH: 'border-orange-800/50',
  MEDIUM: 'border-yellow-800/30',
  LOW: 'border-gray-800',
}

const RISK_BG: Record<string, string> = {
  CRITICAL: 'bg-red-950/20',
  HIGH: 'bg-orange-950/20',
  MEDIUM: 'bg-yellow-950/10',
  LOW: 'bg-gray-900',
}

const LOG_STATUS_STYLE: Record<string, string> = {
  pending_verification: 'text-blue-400',
  blocked: 'text-gray-500',
  suggestion: 'text-purple-400',
  verified_success: 'text-green-400',
  verified_failure: 'text-red-400',
}

// ── KPI strip card ─────────────────────────────────────────────────────────────
function KpiCard({
  icon: Icon, label, value, sub, urgent,
}: {
  icon: React.ElementType
  label: string
  value: number | string
  sub?: string
  urgent?: boolean
}) {
  return (
    <div className={cn(
      'flex-1 min-w-0 p-4 rounded-xl border flex items-start gap-3',
      urgent && Number(value) > 0
        ? 'bg-red-950/20 border-red-800/50'
        : 'bg-gray-900 border-gray-800'
    )}>
      <div className={cn(
        'p-2 rounded-lg shrink-0',
        urgent && Number(value) > 0 ? 'bg-red-900/40' : 'bg-gray-800'
      )}>
        <Icon className={cn('w-4 h-4', urgent && Number(value) > 0 ? 'text-red-400' : 'text-blue-400')} />
      </div>
      <div className="min-w-0">
        <div className="text-xs text-gray-500 mb-0.5">{label}</div>
        <div className={cn(
          'text-2xl font-bold tabular-nums',
          urgent && Number(value) > 0 ? 'text-red-400' : 'text-white'
        )}>{value}</div>
        {sub && <div className="text-xs text-gray-600 mt-0.5">{sub}</div>}
      </div>
    </div>
  )
}

// ── Store ranking card ─────────────────────────────────────────────────────────
function StoreCard({ store, onClick }: { store: StoreRow; onClick: () => void }) {
  const navigate = useNavigate()
  const hasIssues = store.alerts_p1 > 0 || store.alerts_p2 > 0 || store.zones_hot > 0

  return (
    <div
      className={cn(
        'flex items-center gap-3 px-4 py-3 rounded-xl border cursor-pointer transition-all hover:border-gray-600 hover:bg-gray-800/60 group',
        RISK_BORDER[store.risk_level],
        RISK_BG[store.risk_level],
      )}
      onClick={onClick}
    >
      {/* Dot de risco */}
      <div className={cn('w-2 h-2 rounded-full shrink-0', RISK_DOT[store.risk_level])} />

      {/* Nome + código */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-200 truncate">{store.store_name}</span>
          {store.actions_in_progress > 0 && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-300 border border-blue-800/50 shrink-0">
              {store.actions_in_progress} em curso
            </span>
          )}
        </div>

        {/* Status pills */}
        <div className="flex flex-wrap items-center gap-1.5 mt-1">
          {store.alerts_p1 > 0 && (
            <span className="text-xs text-red-400 flex items-center gap-0.5">
              <AlertTriangle className="w-3 h-3" />{store.alerts_p1} P1
            </span>
          )}
          {store.alerts_p2 > 0 && (
            <span className="text-xs text-orange-400 flex items-center gap-0.5">
              <AlertTriangle className="w-3 h-3" />{store.alerts_p2} P2
            </span>
          )}
          {store.zones_hot > 0 && (
            <span className="text-xs text-orange-400 flex items-center gap-0.5">
              <Thermometer className="w-3 h-3" />{store.zones_hot} quente{store.zones_hot > 1 ? 's' : ''}
            </span>
          )}
          {store.zones_warm > 0 && (
            <span className="text-xs text-yellow-400 flex items-center gap-0.5">
              <Thermometer className="w-3 h-3" />{store.zones_warm} morna{store.zones_warm > 1 ? 's' : ''}
            </span>
          )}
          {store.binding_conflicts > 0 && (
            <span className="text-xs text-purple-400 flex items-center gap-0.5">
              <Link2 className="w-3 h-3" />{store.binding_conflicts} conflito{store.binding_conflicts > 1 ? 's' : ''}
            </span>
          )}
          {!hasIssues && store.zones_comfort > 0 && (
            <span className="text-xs text-green-400 flex items-center gap-0.5">
              <CheckCircle className="w-3 h-3" />{store.zones_comfort} zona{store.zones_comfort > 1 ? 's' : ''} OK
            </span>
          )}
        </div>
      </div>

      {/* Temperatura + score + acções */}
      <div className="flex items-center gap-3 shrink-0">
        {store.avg_temperature != null && (
          <div className="text-right hidden sm:block">
            <div className="text-sm font-semibold text-gray-200">{store.avg_temperature.toFixed(1)}°C</div>
            <div className="text-xs text-gray-600">média</div>
          </div>
        )}
        <div className="flex gap-1">
          <button
            onClick={e => { e.stopPropagation(); navigate(`/mapa-termico/${store.store_id}`) }}
            className="p-1.5 rounded hover:bg-gray-700 text-gray-500 hover:text-blue-400 transition-colors"
            title="Mapa térmico"
          >
            <Wind className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={e => { e.stopPropagation(); navigate(`/lojas/${store.store_id}`) }}
            className="p-1.5 rounded hover:bg-gray-700 text-gray-500 hover:text-gray-300 transition-colors"
            title="Ver loja"
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Página principal ───────────────────────────────────────────────────────────
export default function PortfolioPage() {
  const setTarget = useInspectorStore(s => s.setTarget)

  const { data: kpis, isLoading: kpisLoading } = useQuery<PortfolioKPIs>({
    queryKey: ['portfolio-kpis'],
    queryFn: portfolioApi.kpis,
    refetchInterval: 30_000,
  })

  const { data: stores = [], isLoading: storesLoading } = useQuery<StoreRow[]>({
    queryKey: ['portfolio-stores'],
    queryFn: portfolioApi.stores,
    refetchInterval: 30_000,
  })

  const { data: openAlerts = [] } = useQuery<any[]>({
    queryKey: ['portfolio-alerts'],
    queryFn: () => alertsApi.list({ status: 'OPEN', limit: 10 }).then((r: any) => r?.alerts ?? r ?? []),
    refetchInterval: 30_000,
  })

  const { data: recentLogs = [] } = useQuery<any[]>({
    queryKey: ['portfolio-logs'],
    queryFn: () => logsApi.list({ origin: 'automation', limit: 12 }).then((r: any) => r?.items ?? r ?? []),
    refetchInterval: 60_000,
  })

  const storesAtRisk = stores.filter(s => s.risk_level === 'CRITICAL' || s.risk_level === 'HIGH')
  const storesOk = stores.filter(s => s.risk_level === 'LOW' || s.risk_level === 'MEDIUM')

  return (
    <div className="space-y-6">
      {/* Título */}
      <div>
        <h1 className="text-xl font-bold text-gray-100">Centro de Comando</h1>
        <p className="text-sm text-gray-500 mt-0.5">Visão global de portfolio — todas as lojas</p>
      </div>

      {/* KPI strip */}
      <div className="flex gap-3 flex-wrap">
        <KpiCard
          icon={Building2}
          label="Total de lojas"
          value={kpisLoading ? '—' : (kpis?.total_stores ?? 0)}
        />
        <KpiCard
          icon={AlertTriangle}
          label="Lojas em risco"
          value={kpisLoading ? '—' : (kpis?.stores_at_risk ?? 0)}
          sub="com alertas P1/P2 abertos"
          urgent
        />
        <KpiCard
          icon={Zap}
          label="Alertas P1 abertos"
          value={kpisLoading ? '—' : (kpis?.open_p1 ?? 0)}
          sub={`+ ${kpis?.open_p2 ?? 0} P2`}
          urgent
        />
        <KpiCard
          icon={Link2}
          label="Conflitos de binding"
          value={kpisLoading ? '—' : (kpis?.binding_conflicts ?? 0)}
          sub="devices em duas zonas"
          urgent
        />
        <KpiCard
          icon={Activity}
          label="Ações em curso"
          value={kpisLoading ? '—' : (kpis?.actions_in_progress ?? 0)}
          sub="últimos 30 min"
        />
      </div>

      {/* Corpo */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">

        {/* Ranking de lojas — 60% */}
        <div className="lg:col-span-3 space-y-3">
          <h2 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-orange-400" />
            Ranking por urgência
            {storesLoading && <span className="text-xs text-gray-600 font-normal">carregando…</span>}
          </h2>

          {/* Lojas em risco */}
          {storesAtRisk.length > 0 && (
            <div className="space-y-1.5">
              {storesAtRisk.map(store => (
                <StoreCard
                  key={store.store_id}
                  store={store}
                  onClick={() => setTarget({ type: 'store', storeId: store.store_id, storeName: store.store_name })}
                />
              ))}
            </div>
          )}

          {/* Separador */}
          {storesAtRisk.length > 0 && storesOk.length > 0 && (
            <div className="flex items-center gap-2 text-xs text-gray-700">
              <div className="flex-1 h-px bg-gray-800" />
              <Shield className="w-3 h-3 text-green-700" />
              <span>Lojas estáveis</span>
              <div className="flex-1 h-px bg-gray-800" />
            </div>
          )}

          {/* Lojas OK */}
          {storesOk.length > 0 && (
            <div className="space-y-1.5">
              {storesOk.map(store => (
                <StoreCard
                  key={store.store_id}
                  store={store}
                  onClick={() => setTarget({ type: 'store', storeId: store.store_id, storeName: store.store_name })}
                />
              ))}
            </div>
          )}

          {!storesLoading && stores.length === 0 && (
            <div className="text-center py-8 text-gray-600 text-sm">Nenhuma loja com automação ativa encontrada</div>
          )}
        </div>

        {/* Alertas + log IA — 40% */}
        <div className="lg:col-span-2 space-y-4">

          {/* Alertas acionáveis */}
          <div>
            <h2 className="text-sm font-semibold text-gray-300 mb-2 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-red-400" />
              Alertas acionáveis
            </h2>
            <div className="space-y-1.5">
              {openAlerts.length === 0 && (
                <div className="text-xs text-gray-600 py-2">Nenhum alerta P1/P2 aberto</div>
              )}
              {openAlerts.map((a: any) => (
                <div
                  key={a.id}
                  className={cn(
                    'flex items-start gap-2.5 p-2.5 rounded-lg border cursor-pointer hover:border-gray-600 transition-colors',
                    a.severity === 'P1'
                      ? 'bg-red-950/20 border-red-800/40'
                      : 'bg-orange-950/20 border-orange-800/30'
                  )}
                  onClick={() => a.device_id && setTarget({
                    type: 'device',
                    deviceId: a.device_id,
                    deviceName: a.device_name ?? 'Equipamento',
                    storeId: a.store_id,
                  })}
                >
                  <span className={cn(
                    'text-xs font-bold px-1.5 py-0.5 rounded shrink-0 mt-0.5',
                    a.severity === 'P1' ? 'bg-red-900/60 text-red-300' : 'bg-orange-900/60 text-orange-300'
                  )}>
                    {a.severity}
                  </span>
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-gray-200 truncate">
                      {a.device_name ?? 'Dispositivo'} — {a.store_name ?? ''}
                    </div>
                    <div className="text-xs text-gray-500 leading-relaxed mt-0.5 line-clamp-2">
                      {a.message}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Divisor */}
          <div className="h-px bg-gray-800" />

          {/* Timeline de decisões IA */}
          <div>
            <h2 className="text-sm font-semibold text-gray-300 mb-2 flex items-center gap-2">
              <Clock className="w-4 h-4 text-blue-400" />
              Decisões recentes da IA
            </h2>
            <div className="space-y-1.5">
              {recentLogs.length === 0 && (
                <div className="text-xs text-gray-600 py-2">Sem decisões registadas recentemente</div>
              )}
              {recentLogs.map((log: any) => {
                const time = log.created_at
                  ? formatTime(log.created_at)
                  : ''
                const statusColor = LOG_STATUS_STYLE[log.status ?? ''] ?? 'text-gray-400'
                return (
                  <div key={log.id} className="flex items-start gap-2 text-xs py-1.5 border-b border-gray-800/60 last:border-0">
                    <span className="text-gray-700 w-10 shrink-0 pt-0.5 tabular-nums">{time}</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        {log.zone_key && (
                          <span className="text-gray-500 truncate">{log.zone_key}</span>
                        )}
                        <span className={cn('shrink-0', statusColor)}>
                          {log.status === 'pending_verification' ? 'executado'
                            : log.status === 'blocked' ? 'bloqueado'
                            : log.status === 'suggestion' ? 'sugestão'
                            : log.status === 'verified_success' ? 'verificado ✓'
                            : log.status === 'verified_failure' ? 'falhou'
                            : log.status ?? ''}
                        </span>
                      </div>
                      <div className="text-gray-600 leading-relaxed line-clamp-2">
                        {log.summary ?? log.reason ?? ''}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
