import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Map } from 'lucide-react'
import { useState } from 'react'
import { storesApi } from '../api/client'
import DeviceCard from '../components/DeviceCard'
import StatusBadge from '../components/StatusBadge'

const STATUS_OPTIONS = ['Todos', 'NORMAL', 'ATENÇÃO', 'CRÍTICO', 'BAIXA_EFICIÊNCIA', 'SEM_LEITURA', 'DESLIGADO']

export default function StoreView() {
  const { storeId } = useParams<{ storeId: string }>()
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState('Todos')
  const [sectorFilter, setSectorFilter] = useState('Todos')

  const { data: devices = [], isLoading } = useQuery({
    queryKey: ['store-devices', storeId],
    queryFn: () => storesApi.devices(storeId!),
    refetchInterval: 30000,
    enabled: !!storeId,
  })

  const { data: sectors = [] } = useQuery({
    queryKey: ['store-sectors', storeId],
    queryFn: () => storesApi.sectors(storeId!),
    enabled: !!storeId,
  })

  const filtered = devices.filter((d: any) => {
    if (statusFilter !== 'Todos' && d.status !== statusFilter) return false
    if (sectorFilter !== 'Todos' && d.sector_id !== sectorFilter) return false
    return true
  })

  const counts = devices.reduce((acc: any, d: any) => {
    acc[d.status] = (acc[d.status] || 0) + 1
    return acc
  }, {})

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          {['CRÍTICO', 'ATENÇÃO', 'BAIXA_EFICIÊNCIA', 'SEM_LEITURA'].filter(s => counts[s]).map(s => (
            <StatusBadge key={s} status={s} />
          ))}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={sectorFilter}
            onChange={e => setSectorFilter(e.target.value)}
            className="bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="Todos">Todos os setores</option>
            {sectors.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 rounded-lg px-3 py-1.5 text-sm"
          >
            {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      {sectors.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-gray-600 dark:text-gray-400">Ver no Mapa</h2>
          <div className="flex flex-wrap gap-2">
            {sectors.map((s: any) => (
              <button
                key={s.id}
                onClick={() => navigate(`/stores/${storeId}/map/${s.id}`)}
                className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700 rounded-lg text-sm text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white transition-colors"
              >
                <Map className="w-4 h-4" />
                {s.name}
                {s.is_critical && <span className="text-xs bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded">Crítico</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-600 dark:text-gray-400">
            Equipamentos {statusFilter !== 'Todos' && `— ${statusFilter}`}
          </h2>
          <span className="text-xs text-gray-500 dark:text-gray-600">{filtered.length} de {devices.length}</span>
        </div>
        {isLoading ? (
          <div className="text-center py-12 text-gray-500 dark:text-gray-600 text-sm">Carregando equipamentos...</div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12 text-gray-500 dark:text-gray-600 text-sm">Nenhum equipamento encontrado</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {filtered.map((device: any) => <DeviceCard key={device.id} device={device} />)}
          </div>
        )}
      </div>
    </div>
  )
}
