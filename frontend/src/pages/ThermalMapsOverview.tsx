import { useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Building2, MapPinned, Thermometer } from 'lucide-react'
import { storesApi } from '../api/client'
import { formatRelativeTime } from '../lib/utils'
import type { Store } from '../types'

export default function ThermalMapsOverview() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const selectedStoreId = params.get('loja')

  const { data: stores = [], isLoading } = useQuery({
    queryKey: ['stores'],
    queryFn: storesApi.list,
    refetchInterval: 60000,
  })

  const visibleStores = useMemo(() => {
    return stores
      .filter((store: Store) => (store.device_count ?? 0) > 0)
      .filter((store: Store) => !selectedStoreId || store.id === selectedStoreId)
  }, [stores, selectedStoreId])

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Mapa Térmico</h1>
          <p className="text-xs text-gray-500">{visibleStores.length} unidades disponíveis</p>
        </div>
        {selectedStoreId && (
          <button
            type="button"
            onClick={() => navigate('/mapa-termico')}
            className="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            Ver todas
          </button>
        )}
      </div>

      {isLoading ? (
        <div className="py-16 text-center text-sm text-gray-500">Carregando mapas...</div>
      ) : visibleStores.length === 0 ? (
        <div className="py-16 text-center text-sm text-gray-500">Nenhuma unidade com mapa disponível</div>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {visibleStores.map((store: Store) => (
            <ThermalStoreCard key={store.id} store={store} />
          ))}
        </div>
      )}
    </div>
  )
}

function ThermalStoreCard({ store }: { store: Store }) {
  const navigate = useNavigate()

  return (
    <article
      className="group flex cursor-pointer flex-col overflow-hidden rounded-xl border border-gray-200 bg-white transition-shadow hover:shadow-md dark:border-gray-800 dark:bg-gray-900"
      onClick={() => navigate(`/mapa-termico/${store.id}`)}
    >
      <div className="flex items-start justify-between gap-3 p-5">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase text-blue-500">
            <Thermometer className="h-4 w-4" />
            {store.kind === 'ESCRITORIO' ? 'Escritório' : store.kind === 'MATRIZ' ? 'Matriz' : store.kind || 'LOJA'}
          </div>
          <h2 className="truncate text-base font-semibold text-gray-900 group-hover:text-blue-600 dark:text-white dark:group-hover:text-blue-400">
            {store.name}
          </h2>
          <p className="mt-1 text-xs text-gray-500">
            {store.device_count ?? 0} equipamentos · última leitura {formatRelativeTime(store.last_reading_at)}
          </p>
        </div>
        <Building2 className="h-5 w-5 shrink-0 text-gray-400" />
      </div>

      <div className="mt-auto flex gap-2 border-t border-gray-100 p-4 dark:border-gray-800">
        <button
          type="button"
          onClick={e => { e.stopPropagation(); navigate(`/mapa-termico/${store.id}`) }}
          className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500"
        >
          <Thermometer className="h-4 w-4" />
          Mapa térmico
        </button>
        <button
          type="button"
          onClick={e => { e.stopPropagation(); navigate(`/lojas/${store.id}/mapa`) }}
          className="flex items-center justify-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <MapPinned className="h-4 w-4" />
        </button>
      </div>
    </article>
  )
}
