import { useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Search, SlidersHorizontal } from 'lucide-react'
import { storesApi } from '../api/client'
import DeviceCard from '../components/DeviceCard'
import { cn } from '../lib/utils'
import type { Device, DeviceStatus, Store } from '../types'

const STATUS_OPTIONS: Array<'TODOS' | DeviceStatus> = ['TODOS', 'NORMAL', 'ATENÇÃO', 'CRÍTICO', 'BAIXA_EFICIÊNCIA', 'SEM_LEITURA', 'LEITURA_STALE', 'DESLIGADO']

export default function EquipmentOverview() {
  const [query, setQuery] = useState('')
  const [storeId, setStoreId] = useState('TODAS')
  const [status, setStatus] = useState<'TODOS' | DeviceStatus>('TODOS')

  const { data: stores = [], isLoading: storesLoading } = useQuery({
    queryKey: ['stores'],
    queryFn: storesApi.list,
    refetchInterval: 60000,
  })

  const activeStores = useMemo(() => stores.filter((store: Store) => (store.device_count ?? 0) > 0), [stores])
  const deviceQueries = useQueries({
    queries: activeStores.map((store: Store) => ({
      queryKey: ['store-devices', store.id],
      queryFn: () => storesApi.devices(store.id),
      refetchInterval: 30000,
    })),
  })

  const devices = useMemo<Device[]>(() => {
    return activeStores.flatMap((store: Store, index: number) => {
      const rows = (deviceQueries[index]?.data || []) as Device[]
      return rows.map(device => ({
        ...device,
        store_id: store.id,
        store_name: store.name,
      }))
    })
  }, [activeStores, deviceQueries])

  const filtered = useMemo<Device[]>(() => {
    const term = query.trim().toLowerCase()
    return devices
      .filter(device => storeId === 'TODAS' || device.store_id === storeId)
      .filter(device => status === 'TODOS' || device.status === status)
      .filter(device => {
        if (!term) return true
        return `${device.brise_id} ${device.name} ${device.store_name || ''} ${device.sector_name || ''}`.toLowerCase().includes(term)
      })
  }, [devices, query, storeId, status])

  const isLoading = storesLoading || deviceQueries.some(queryResult => queryResult.isLoading)

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Equipamentos</h1>
          <p className="text-xs text-gray-500">{filtered.length} de {devices.length} equipamentos</p>
        </div>
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-500" />
            <input
              value={query}
              onChange={event => setQuery(event.target.value)}
              className="h-9 w-full rounded-lg border border-gray-200 bg-white pl-9 pr-3 text-sm text-gray-900 outline-none focus:border-blue-500 dark:border-gray-800 dark:bg-gray-900 dark:text-white lg:w-72"
              placeholder="Máquina, loja ou setor"
            />
          </div>
          <select
            value={storeId}
            onChange={event => setStoreId(event.target.value)}
            className="h-9 rounded-lg border border-gray-200 bg-white px-3 text-sm text-gray-900 outline-none focus:border-blue-500 dark:border-gray-800 dark:bg-gray-900 dark:text-white"
          >
            <option value="TODAS">Todas as unidades</option>
            {activeStores.map((store: Store) => (
              <option key={store.id} value={store.id}>{store.name}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex items-center gap-2 overflow-x-auto rounded-lg border border-gray-200 bg-white p-2 dark:border-gray-800 dark:bg-gray-900">
        <SlidersHorizontal className="h-4 w-4 shrink-0 text-gray-500" />
        {STATUS_OPTIONS.map(option => (
          <button
            key={option}
            onClick={() => setStatus(option)}
            className={cn(
              'shrink-0 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              status === option ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-900 dark:hover:text-white'
            )}
          >
            {option === 'TODOS' ? 'Todos' : option}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="py-16 text-center text-sm text-gray-500">Carregando equipamentos...</div>
      ) : filtered.length === 0 ? (
        <div className="py-16 text-center text-sm text-gray-500">Nenhum equipamento encontrado</div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
          {filtered.map(device => <DeviceCard key={device.id} device={device} />)}
        </div>
      )}
    </div>
  )
}
