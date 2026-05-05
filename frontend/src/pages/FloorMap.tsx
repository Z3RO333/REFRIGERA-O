import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ArrowLeft, Edit2, MapPin, Save, Search, Trash2, X } from 'lucide-react'
import { storesApi, devicesApi } from '../api/client'
import FloorPlanCanvas from '../components/map/FloorPlanCanvas'
import StatusBadge from '../components/StatusBadge'
import { formatTemp, formatDelta } from '../lib/utils'
import type { Device } from '../types'

export default function FloorMap() {
  const { storeId, sectorId } = useParams<{ storeId: string; sectorId?: string }>()
  const navigate = useNavigate()
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null)
  const [editMode, setEditMode] = useState(false)
  const [selectedFloor, setSelectedFloor] = useState(1)
  const [draftPositions, setDraftPositions] = useState<Record<string, { x: number | null; y: number | null }>>({})
  const [isSavingPositions, setIsSavingPositions] = useState(false)
  const [deviceSearch, setDeviceSearch] = useState('')
  const [placingDeviceId, setPlacingDeviceId] = useState<string | null>(null)

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
  const isGeneralMap = !sectorId
  const currentFloor = sector?.floor ?? selectedFloor
  const floorPlanUrl = sectors.find((s: any) => s.floor === currentFloor && s.floor_plan_url)?.floor_plan_url || null
  const sectorsById = new Map<string, any>(sectors.map((s: any) => [s.id, s]))
  const mapContext = isGeneralMap
    ? { id: 'geral', name: `Matriz - ${formatFloor(currentFloor)}`, floor: currentFloor, floor_plan_url: floorPlanUrl, is_critical: false }
    : sector
  const sectorDevices = isGeneralMap
    ? devices.filter((d: any) => d.sector_name !== 'Offline' && sectorsById.get(d.sector_id)?.floor === currentFloor)
    : devices.filter((d: any) => d.sector_id === sectorId)
  const dirtyDeviceIds = Object.keys(draftPositions)
  const visibleDevices = sectorDevices.map((device: Device) => {
    const draft = draftPositions[device.id]
    if (!draft) return device
    return { ...device, position_x: draft.x, position_y: draft.y }
  })
  const placedCount = visibleDevices.filter((device: Device) => device.position_x != null && device.position_y != null).length
  const placingDevice = sectorDevices.find((device: Device) => device.id === placingDeviceId) || null
  const searchedDevices = sectorDevices
    .filter((device: Device) => {
      const term = deviceSearch.trim().toLowerCase()
      if (!term) return true
      return `${device.brise_id} ${device.name} ${device.sector_name || ''}`.toLowerCase().includes(term)
    })
    .sort((a: Device, b: Device) => {
      const aDraft = draftPositions[a.id]
      const bDraft = draftPositions[b.id]
      const aPlaced = (aDraft ? aDraft.x : a.position_x) != null && (aDraft ? aDraft.y : a.position_y) != null
      const bPlaced = (bDraft ? bDraft.x : b.position_x) != null && (bDraft ? bDraft.y : b.position_y) != null
      if (aPlaced !== bPlaced) return aPlaced ? 1 : -1
      return a.name.localeCompare(b.name)
    })

  const handleDeviceMove = (deviceId: string, x: number, y: number) => {
    setDraftPositions(prev => ({ ...prev, [deviceId]: { x, y } }))
    setSelectedDevice(prev => prev?.id === deviceId ? { ...prev, position_x: x, position_y: y } : prev)
  }

  const handleCanvasPlace = (x: number, y: number) => {
    if (!placingDevice) return
    handleDeviceMove(placingDevice.id, x, y)
    setSelectedDevice({ ...placingDevice, position_x: x, position_y: y })
    setPlacingDeviceId(null)
  }

  const removeFromMap = (device: Device) => {
    setDraftPositions(prev => ({ ...prev, [device.id]: { x: null, y: null } }))
    setSelectedDevice(prev => prev?.id === device.id ? { ...prev, position_x: null, position_y: null } : prev)
  }

  const startEditing = () => {
    setDraftPositions({})
    setPlacingDeviceId(null)
    setEditMode(true)
  }

  const cancelEditing = () => {
    setDraftPositions({})
    setPlacingDeviceId(null)
    setEditMode(false)
    refetch()
  }

  const savePositions = async () => {
    const entries = Object.entries(draftPositions)
    if (!entries.length) {
      setEditMode(false)
      return
    }
    setIsSavingPositions(true)
    try {
      await Promise.all(entries.map(([id, pos]) => devicesApi.updatePosition(id, pos.x, pos.y)))
      setDraftPositions({})
      setPlacingDeviceId(null)
      setEditMode(false)
      await refetch()
    } finally {
      setIsSavingPositions(false)
    }
  }

  return (
    <div className="h-full flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors">
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="font-semibold text-gray-900 dark:text-white">{mapContext?.name || 'Mapa de Planta'}</h1>
            <p className="text-xs text-gray-500">{placedCount} posicionados de {sectorDevices.length} equipamentos {isGeneralMap ? 'neste andar' : 'neste setor'}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isGeneralMap && (
            <div className="flex rounded-lg border border-gray-200 bg-white p-1 dark:border-gray-800 dark:bg-gray-900">
              {[1, 2, 3, 4].map(floor => (
                <button
                  key={floor}
                  type="button"
                  onClick={() => setSelectedFloor(floor)}
                  className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                    selectedFloor === floor ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-900 dark:hover:text-white'
                  }`}
                >
                  {formatFloor(floor)}
                </button>
              ))}
            </div>
          )}
          {editMode ? (
            <>
              <button
                onClick={cancelEditing}
                disabled={isSavingPositions}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                <X className="w-4 h-4" /> Cancelar
              </button>
              <button
                onClick={savePositions}
                disabled={isSavingPositions}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
              >
                <Save className="w-4 h-4" />
                {isSavingPositions ? 'Salvando...' : dirtyDeviceIds.length ? `Salvar ${dirtyDeviceIds.length}` : 'Concluir'}
              </button>
            </>
          ) : (
            <button
              onClick={startEditing}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
            >
              <Edit2 className="w-4 h-4" /> Editar posições
            </button>
          )}
        </div>
      </div>

      <div className="flex gap-4 flex-1 min-h-0">
        <div className="flex-1">
          <FloorPlanCanvas
            devices={visibleDevices}
            sector={mapContext}
            onDeviceClick={setSelectedDevice}
            editMode={editMode}
            onDeviceMove={handleDeviceMove}
            onCanvasPlace={handleCanvasPlace}
            placingDeviceName={placingDevice ? `${placingDevice.brise_id} — ${placingDevice.name}` : null}
            dirtyDeviceIds={dirtyDeviceIds}
          />
        </div>

        {editMode ? (
          <div className="w-80 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden flex flex-col">
            <div className="p-4 border-b border-gray-200 dark:border-gray-800 space-y-3">
              <div>
                <h3 className="font-semibold text-gray-900 dark:text-white">Posicionar aparelhos</h3>
                <p className="text-xs text-gray-500">{dirtyDeviceIds.length} alteração{dirtyDeviceIds.length === 1 ? '' : 'ões'} pendente{dirtyDeviceIds.length === 1 ? '' : 's'}</p>
              </div>
              <div className="relative">
                <Search className="absolute left-3 top-2.5 w-4 h-4 text-gray-500" />
                <input
                  value={deviceSearch}
                  onChange={event => setDeviceSearch(event.target.value)}
                  className="h-9 w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 pl-9 pr-3 text-sm text-gray-900 dark:text-white outline-none focus:border-blue-500"
                  placeholder="Pesquisar nº ou nome do ar"
                />
              </div>
              {placingDevice && (
                <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3 text-xs text-blue-700 dark:text-blue-300">
                  <div className="font-semibold">{placingDevice.brise_id} — {placingDevice.name}</div>
                  <div>Clique no ponto da planta onde ele deve ficar.</div>
                </div>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {searchedDevices.map((device: Device) => {
                const draft = draftPositions[device.id]
                const effectiveX = draft ? draft.x : device.position_x
                const effectiveY = draft ? draft.y : device.position_y
                const isPlaced = effectiveX != null && effectiveY != null
                const isDirty = dirtyDeviceIds.includes(device.id)
                const isPlacing = placingDeviceId === device.id
                return (
                  <div
                    key={device.id}
                    className={`rounded-lg border p-3 transition-colors ${
                      isPlacing
                        ? 'border-blue-500 bg-blue-500/10'
                        : isDirty
                          ? 'border-orange-400/50 bg-orange-500/10'
                          : 'border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="font-mono text-xs text-blue-500">{device.brise_id}</div>
                        <div className="truncate text-sm font-medium text-gray-900 dark:text-white">{device.name}</div>
                        <div className="truncate text-xs text-gray-500">{device.sector_name || 'Sem setor'}</div>
                      </div>
                      <StatusBadge status={device.status} size="sm" />
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={() => setPlacingDeviceId(device.id)}
                        className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500"
                      >
                        <MapPin className="w-3.5 h-3.5" />
                        {isPlaced ? 'Reposicionar' : 'Colocar'}
                      </button>
                      {isPlaced && (
                        <button
                          type="button"
                          onClick={() => removeFromMap(device)}
                          className="flex items-center justify-center rounded-lg border border-gray-200 dark:border-gray-800 px-2.5 py-1.5 text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800"
                          title="Remover do mapa"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
              {!searchedDevices.length && (
                <div className="py-10 text-center text-sm text-gray-500">Nenhum ar encontrado</div>
              )}
            </div>
          </div>
        ) : selectedDevice && (
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

function formatFloor(floor: number) {
  return `${floor}º andar`
}
