import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { ArrowLeft, Edit2, Save } from 'lucide-react'
import { storesApi, devicesApi } from '../api/client'
import FloorPlanCanvas from '../components/map/FloorPlanCanvas'
import StatusBadge from '../components/StatusBadge'
import { formatTemp, formatDelta } from '../lib/utils'
import type { Device } from '../types'

export default function FloorMap() {
  const { storeId, sectorId } = useParams<{ storeId: string; sectorId: string }>()
  const navigate = useNavigate()
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null)
  const [editMode, setEditMode] = useState(false)

  const { data: devices = [], refetch } = useQuery({
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

  const sector = sectors.find((s: any) => s.id === sectorId) || null
  const sectorDevices = devices.filter((d: any) => d.sector_id === sectorId)

  const moveDevice = useMutation({
    mutationFn: ({ id, x, y }: { id: string; x: number; y: number }) =>
      devicesApi.updatePosition(id, x, y),
  })

  const handleDeviceMove = (deviceId: string, x: number, y: number) => {
    moveDevice.mutate({ id: deviceId, x, y })
  }

  return (
    <div className="h-full flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="font-semibold text-gray-900 dark:text-white">{sector?.name || 'Mapa de Planta'}</h1>
            <p className="text-xs text-gray-500">{sectorDevices.length} equipamentos neste setor</p>
          </div>
        </div>
        <button
          onClick={() => { setEditMode(!editMode); if (editMode) refetch() }}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-colors ${
            editMode
              ? 'bg-blue-600 text-gray-900 dark:text-white'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
          }`}
        >
          {editMode ? <><Save className="w-4 h-4" /> Salvar</> : <><Edit2 className="w-4 h-4" /> Editar mapa</>}
        </button>
      </div>

      <div className="flex gap-4 flex-1 min-h-0">
        <div className="flex-1">
          <FloorPlanCanvas
            devices={sectorDevices}
            sector={sector}
            onDeviceClick={setSelectedDevice}
            editMode={editMode}
            onDeviceMove={handleDeviceMove}
          />
        </div>

        {selectedDevice && (
          <div className="w-72 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4 space-y-4 overflow-y-auto">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="font-semibold text-gray-900 dark:text-white">{selectedDevice.name}</h3>
                <p className="text-xs text-gray-500">{selectedDevice.sector_name}</p>
              </div>
              <button onClick={() => setSelectedDevice(null)} className="text-gray-500 dark:text-gray-600 hover:text-gray-400">✕</button>
            </div>
            <StatusBadge status={selectedDevice.status} />
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <div className="text-gray-500 text-xs">Temperatura</div>
                <div className="text-gray-900 dark:text-white font-medium">{formatTemp(selectedDevice.temperature)}</div>
              </div>
              <div>
                <div className="text-gray-500 text-xs">Delta</div>
                <div className="text-gray-900 dark:text-white font-medium">{formatDelta(selectedDevice.delta_temp)}</div>
              </div>
              <div>
                <div className="text-gray-500 text-xs">Umidade</div>
                <div className="text-gray-900 dark:text-white font-medium">{selectedDevice.humidity ?? '—'}%</div>
              </div>
              <div>
                <div className="text-gray-500 text-xs">BTU</div>
                <div className="text-gray-900 dark:text-white font-medium">{selectedDevice.btu?.toLocaleString()}</div>
              </div>
            </div>
            {selectedDevice.is_critical_environment && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-2 text-xs text-red-400">
                Ambiente crítico — monitoramento prioritário
              </div>
            )}
            <div className="flex flex-col gap-2">
              <button
                onClick={() => navigate(`/devices/${selectedDevice.id}`)}
                className="w-full py-2 bg-blue-600/20 border border-blue-600/30 text-blue-400 rounded-lg text-sm hover:bg-blue-600/30 transition-colors"
              >
                Ver detalhes completos
              </button>
              <button
                onClick={() => navigate(`/history/${selectedDevice.id}`)}
                className="w-full py-2 bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 rounded-lg text-sm hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
              >
                Ver histórico
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 text-xs text-gray-500">
        {['NORMAL', 'ATENÇÃO', 'CRÍTICO', 'BAIXA_EFICIÊNCIA', 'SEM_LEITURA', 'DESLIGADO'].map(s => (
          <StatusBadge key={s} status={s} size="sm" />
        ))}
      </div>
    </div>
  )
}
