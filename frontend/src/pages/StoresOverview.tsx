import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowUpRight, Building2, Map, Search, Thermometer, WifiOff } from 'lucide-react'
import { kpiApi, storesApi } from '../api/client'
import { cn, formatRelativeTime, formatTemp } from '../lib/utils'
import type { Store } from '../types'

const KIND_OPTIONS = ['TODAS', 'MATRIZ', 'ESCRITORIO', 'LOJA', 'FARMA', 'CD']

const KIND_LABELS: Record<string, string> = {
  TODAS: 'Todas',
  MATRIZ: 'Matriz',
  ESCRITORIO: 'Escritórios',
  LOJA: 'Lojas',
  FARMA: 'Farma',
  CD: 'CD',
}

const STORE_STATUS = {
  normal: {
    label: 'Normal',
    dot: 'bg-green-500',
    border: 'border-green-500/30',
    bg: 'bg-green-500/5',
    text: 'text-green-500',
  },
  warning: {
    label: 'Atenção',
    dot: 'bg-yellow-500',
    border: 'border-yellow-500/40',
    bg: 'bg-yellow-500/5',
    text: 'text-yellow-500',
  },
  critical: {
    label: 'Crítico',
    dot: 'bg-red-500',
    border: 'border-red-500/50',
    bg: 'bg-red-500/5',
    text: 'text-red-500',
  },
  offline: {
    label: 'Offline',
    dot: 'bg-gray-500',
    border: 'border-gray-400/40 dark:border-gray-700',
    bg: 'bg-gray-500/5',
    text: 'text-gray-500',
  },
}

type StoreStatusKey = keyof typeof STORE_STATUS

export default function StoresOverview() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('TODAS')

  const { data: stores = [], isLoading } = useQuery({
    queryKey: ['stores'],
    queryFn: storesApi.list,
    refetchInterval: 60000,
  })

  const filteredStores = useMemo(() => {
    const term = query.trim().toLowerCase()
    return stores
      .filter((store: Store) => (store.device_count ?? 0) > 0)
      .filter((store: Store) => kind === 'TODAS' || store.kind === kind)
      .filter((store: Store) => {
        if (!term) return true
        return `${store.code} ${store.name} ${store.city || ''} ${store.kind || ''}`.toLowerCase().includes(term)
      })
  }, [stores, query, kind])

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Mapa das Lojas</h1>
          <p className="text-xs text-gray-500">{filteredStores.length} unidades com equipamentos monitorados</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-500" />
            <input
              value={query}
              onChange={event => setQuery(event.target.value)}
              className="h-9 w-full rounded-lg border border-gray-200 bg-white pl-9 pr-3 text-sm text-gray-900 outline-none focus:border-blue-500 dark:border-gray-800 dark:bg-gray-900 dark:text-white sm:w-72"
              placeholder="Buscar unidade"
            />
          </div>
          <div className="flex rounded-lg border border-gray-200 bg-white p-1 dark:border-gray-800 dark:bg-gray-900">
            {KIND_OPTIONS.map(option => (
              <button
                key={option}
                onClick={() => setKind(option)}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  kind === option ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-900 dark:hover:text-white'
                )}
              >
                {KIND_LABELS[option] || option}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="py-16 text-center text-sm text-gray-500">Carregando unidades...</div>
      ) : filteredStores.length === 0 ? (
        <div className="py-16 text-center text-sm text-gray-500">Nenhuma unidade encontrada</div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {filteredStores.map((store: Store) => (
            <StoreHealthCard
              key={store.id}
              store={store}
              onOpen={() => navigate(`/lojas/${store.id}`)}
              onMap={() => navigate(`/mapa-termico?loja=${store.id}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function StoreHealthCard({ store, onOpen, onMap }: { store: Store; onOpen: () => void; onMap: () => void }) {
  const { data } = useQuery({
    queryKey: ['store-kpis', store.id],
    queryFn: () => kpiApi.store(store.id),
    refetchInterval: 60000,
  })

  const total = data?.total_devices ?? store.device_count ?? 0
  const offline = (data?.devices_no_reading ?? 0) + (data?.devices_stale ?? 0) + (data?.devices_off ?? 0)
  const critical = data?.devices_critical ?? 0
  const warning = (data?.devices_warning ?? 0) + (data?.devices_low_efficiency ?? 0)
  const statusKey: StoreStatusKey =
    total > 0 && offline >= total ? 'offline' :
    critical > 0 ? 'critical' :
    warning > 0 || offline > 0 ? 'warning' :
    'normal'
  const status = STORE_STATUS[statusKey]

  return (
    <article className={cn('rounded-lg border bg-white p-4 transition-colors dark:bg-gray-900', status.border, status.bg)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn('h-2.5 w-2.5 rounded-full', status.dot)} />
            <span className={cn('text-xs font-semibold uppercase', status.text)}>{status.label}</span>
          </div>
          <h2 className="mt-2 truncate text-base font-semibold text-gray-900 dark:text-white">{store.name}</h2>
          <p className="text-xs text-gray-500">{kindLabel(store.kind)}{store.city ? ` • ${store.city}` : ''}</p>
        </div>
        <Building2 className="h-5 w-5 shrink-0 text-gray-400" />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <Metric icon={<Thermometer className="h-3.5 w-3.5" />} label="Temp. média" value={formatTemp(data?.avg_temperature)} />
        <Metric icon={<Building2 className="h-3.5 w-3.5" />} label="Equipamentos" value={total} />
        <Metric icon={<AlertTriangle className="h-3.5 w-3.5" />} label="Críticos" value={critical} tone={critical > 0 ? 'text-red-500' : undefined} />
        <Metric icon={<WifiOff className="h-3.5 w-3.5" />} label="Offline" value={offline} tone={offline > 0 ? 'text-gray-500' : undefined} />
        <Metric label="Última leitura" value={formatRelativeTime(store.last_reading_at)} />
        <Metric label="SLA" value={data?.compliance_rate != null ? `${data.compliance_rate}%` : '—'} tone={(data?.compliance_rate ?? 100) < 80 ? 'text-yellow-500' : 'text-green-500'} />
      </div>

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={onOpen}
          className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500"
        >
          <ArrowUpRight className="h-4 w-4" />
          Abrir
        </button>
        <button
          type="button"
          onClick={onMap}
          className="flex items-center justify-center rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-100 dark:border-gray-800 dark:text-gray-300 dark:hover:bg-gray-800"
          title="Mapa térmico"
        >
          <Map className="h-4 w-4" />
        </button>
      </div>
    </article>
  )
}

function Metric({ icon, label, value, tone }: { icon?: React.ReactNode; label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-xs text-gray-500">
        {icon}
        {label}
      </div>
      <div className={cn('mt-0.5 font-semibold text-gray-900 dark:text-white', tone)}>{value}</div>
    </div>
  )
}

function kindLabel(kind?: string) {
  if (kind === 'ESCRITORIO') return 'Escritório'
  if (kind === 'MATRIZ') return 'Matriz'
  return kind || 'LOJA'
}
