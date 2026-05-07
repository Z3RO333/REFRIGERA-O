import { useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Building2, Layers, MapPinned, Thermometer } from 'lucide-react'
import { storesApi } from '../api/client'
import { cn, formatRelativeTime } from '../lib/utils'
import type { Sector, Store } from '../types'

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
  const { data: sectors = [], isLoading } = useQuery({
    queryKey: ['store-sectors', store.id],
    queryFn: () => storesApi.sectors(store.id),
    enabled: !!store.id,
  })

  return (
    <article className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
      <div className="flex items-start justify-between gap-3 border-b border-gray-200 p-4 dark:border-gray-800">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase text-blue-500">
            <Thermometer className="h-4 w-4" />
            {store.kind || 'LOJA'}
          </div>
          <h2 className="mt-2 truncate text-base font-semibold text-gray-900 dark:text-white">{store.name}</h2>
          <p className="text-xs text-gray-500">{store.device_count ?? 0} equipamentos • última leitura {formatRelativeTime(store.last_reading_at)}</p>
        </div>
        <Building2 className="h-5 w-5 shrink-0 text-gray-400" />
      </div>

      <div className="grid min-h-44 grid-cols-1 md:grid-cols-[1fr_220px]">
        <div className="relative border-b border-gray-200 bg-gray-50 p-4 dark:border-gray-800 dark:bg-gray-950/60 md:border-b-0 md:border-r">
          <div className="grid h-full min-h-36 grid-cols-3 gap-2">
            {(isLoading ? Array.from({ length: 6 }) : sectors.slice(0, 6)).map((sector: Sector | unknown, index: number) => {
              const item = sector as Sector
              const hasSector = Boolean(item?.id)
              return (
                <button
                  key={hasSector ? item.id : index}
                  type="button"
                  disabled={!hasSector}
                  onClick={() => navigate(`/mapa-termico/${store.id}`)}
                  className={cn(
                    'flex min-h-16 flex-col items-start justify-between rounded-md border p-2 text-left transition-colors',
                    hasSector
                      ? item.is_critical
                        ? 'border-red-400/40 bg-red-500/10 hover:bg-red-500/15'
                        : 'border-blue-400/30 bg-blue-500/10 hover:bg-blue-500/15'
                      : 'border-gray-200 bg-gray-100 dark:border-gray-800 dark:bg-gray-900'
                  )}
                >
                  <span className="text-xs font-medium text-gray-900 dark:text-white">{hasSector ? item.name : 'Carregando'}</span>
                  {hasSector && <span className="text-[11px] text-gray-500">Andar {item.floor ?? 0}</span>}
                </button>
              )
            })}
            {!isLoading && sectors.length === 0 && (
              <div className="col-span-3 flex items-center justify-center rounded-md border border-dashed border-gray-300 text-sm text-gray-500 dark:border-gray-700">
                Sem setores cadastrados
              </div>
            )}
          </div>
        </div>

        <div className="space-y-3 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-white">
            <Layers className="h-4 w-4 text-gray-500" />
            Setores
          </div>
          <div className="space-y-2">
            {sectors.slice(0, 4).map((sector: Sector) => (
              <button
                key={sector.id}
                type="button"
                onClick={() => navigate(`/mapa-termico/${store.id}`)}
                className="flex w-full items-center justify-between gap-2 rounded-lg border border-gray-200 px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-300 dark:hover:bg-gray-800"
              >
                <span className="truncate">{sector.name}</span>
                <MapPinned className="h-4 w-4 shrink-0 text-gray-500" />
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => navigate(`/mapa-termico/${store.id}`)}
            className="w-full rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500"
          >
            Abrir conforto térmico
          </button>
          <button
            type="button"
            onClick={() => navigate(`/lojas/${store.id}/mapa`)}
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            Posicionar aparelhos
          </button>
        </div>
      </div>
    </article>
  )
}
