import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Eye, EyeOff, SlidersHorizontal, Thermometer, Zap } from 'lucide-react'
import { devicesApi, storesApi } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import DeviceMarker from '../components/map/DeviceMarker'
import { cn, formatRelativeTime, formatTemp } from '../lib/utils'
import type { Device, Sector } from '../types'

type ThermalStatus = 'COLD' | 'COMFORT' | 'WARM' | 'HOT' | 'CRITICAL' | 'NO_READING'

interface ZoneDefinition {
  key: string
  sectorNames: string[]
  label: string
  x: number
  y: number
  w: number
  h: number
  idealMin: number
  idealMax: number
}

const VIEWBOX = { w: 800, h: 556 }

const ZONES: ZoneDefinition[] = [
  { key: 'convivencia', sectorNames: ['Convivência', 'Refeitório', 'Salas de Descanso'], label: 'Convivência', x: 125, y: 8, w: 250, h: 105, idealMin: 22, idealMax: 24 },
  { key: 'sac', sectorNames: ['SAC'], label: 'SAC', x: 70, y: 128, w: 245, h: 112, idealMin: 22, idealMax: 24 },
  { key: 'conta-bemol', sectorNames: ['Conta Bemol'], label: 'Conta Bemol', x: 340, y: 140, w: 118, h: 92, idealMin: 22, idealMax: 24 },
  { key: 'auditorio', sectorNames: ['Auditório'], label: 'Auditório', x: 105, y: 250, w: 220, h: 82, idealMin: 22, idealMax: 24 },
  { key: 'comercial', sectorNames: ['Comercial'], label: 'Comercial', x: 515, y: 155, w: 210, h: 92, idealMin: 22, idealMax: 24 },
  { key: 'marketing', sectorNames: ['Marketing', 'Marketplace'], label: 'Marketing / Marketplace', x: 545, y: 265, w: 210, h: 92, idealMin: 22, idealMax: 24 },
  { key: 'contabilidade', sectorNames: ['Contabilidade', 'Gestão de Risco'], label: 'Contabilidade / Risco', x: 520, y: 365, w: 235, h: 90, idealMin: 22, idealMax: 24 },
  { key: 'bemol-online', sectorNames: ['Bemol Online', 'Televendas'], label: 'Online / Televendas', x: 128, y: 360, w: 245, h: 128, idealMin: 22, idealMax: 24 },
  { key: 'geral', sectorNames: ['Geral', 'Recepção', 'CAB'], label: 'Área central', x: 330, y: 250, w: 145, h: 150, idealMin: 22, idealMax: 24 },
  { key: 'farmacia', sectorNames: ['Farmácia'], label: 'Farmácia', x: 480, y: 110, w: 90, h: 92, idealMin: 20, idealMax: 22 },
]

const STATUS_META: Record<ThermalStatus, { label: string; color: string; fill: string; text: string }> = {
  COLD: { label: 'Frio demais', color: '#2563EB', fill: 'rgba(37, 99, 235, 0.48)', text: 'text-blue-600 dark:text-blue-400' },
  COMFORT: { label: 'Confortável', color: '#22C55E', fill: 'rgba(34, 197, 94, 0.38)', text: 'text-green-600 dark:text-green-400' },
  WARM: { label: 'Aquecendo', color: '#EAB308', fill: 'rgba(234, 179, 8, 0.45)', text: 'text-yellow-600 dark:text-yellow-400' },
  HOT: { label: 'Quente', color: '#F97316', fill: 'rgba(249, 115, 22, 0.48)', text: 'text-orange-600 dark:text-orange-400' },
  CRITICAL: { label: 'Muito quente', color: '#EF4444', fill: 'rgba(239, 68, 68, 0.52)', text: 'text-red-600 dark:text-red-400' },
  NO_READING: { label: 'Sem leitura', color: '#6B7280', fill: 'rgba(107, 114, 128, 0.28)', text: 'text-gray-500' },
}

export default function ThermalComfortMap() {
  const { storeId } = useParams<{ storeId: string }>()
  const navigate = useNavigate()
  const [selectedFloor, setSelectedFloor] = useState(1)
  const [selectedZoneKey, setSelectedZoneKey] = useState<string | null>(null)
  const [showEquipment, setShowEquipment] = useState(false)
  const [statusFilter, setStatusFilter] = useState<ThermalStatus | 'ALL'>('ALL')
  const [actionMessage, setActionMessage] = useState('')

  const { data: devices = [], refetch: refetchDevices } = useQuery({
    queryKey: ['store-devices', storeId],
    queryFn: () => storesApi.devices(storeId!),
    enabled: !!storeId,
    refetchInterval: 30000,
  })

  const { data: sectors = [] } = useQuery({
    queryKey: ['store-sectors', storeId],
    queryFn: () => storesApi.sectors(storeId!),
    enabled: !!storeId,
  })

  const floorPlanUrl = sectors.find((sector: Sector) => sector.floor === selectedFloor && sector.floor_plan_url)?.floor_plan_url || null
  const sectorsById = new Map<string, Sector>(sectors.map((sector: Sector) => [sector.id, sector]))
  const floorDevices = devices.filter((device: Device) => sectorsById.get(device.sector_id || '')?.floor === selectedFloor)
  const positionedDevices = floorDevices.filter((device: Device) => device.position_x != null && device.position_y != null)

  const zoneStates = useMemo(() => {
    return ZONES.map(zone => {
      const zoneDevices = floorDevices.filter((device: Device) => zone.sectorNames.includes(device.sector_name || ''))
      const temperatureDevices = zoneDevices.filter((device: Device) => device.temperature != null)
      const avgTemp = temperatureDevices.length
        ? temperatureDevices.reduce((sum: number, device: Device) => sum + Number(device.temperature), 0) / temperatureDevices.length
        : null
      const status = classifyZone(avgTemp, zone.idealMin, zone.idealMax)
      const actionableDevices = zoneDevices.filter((device: Device) => !['SEM_LEITURA', 'DESLIGADO'].includes(device.status))
      return {
        ...zone,
        devices: zoneDevices,
        actionableDevices,
        avgTemp,
        status,
      }
    })
  }, [floorDevices])

  const visibleZones = statusFilter === 'ALL'
    ? zoneStates
    : zoneStates.filter(zone => zone.status === statusFilter)
  const selectedZone = zoneStates.find(zone => zone.key === selectedZoneKey) || zoneStates[0] || null
  const avgStoreTemp = average(zoneStates.map(zone => zone.avgTemp).filter((value): value is number => value != null))
  const lastUpdate = newestDate(floorDevices.map((device: Device) => device.updated_at).filter(Boolean) as string[])

  const applyRecommendedAdjustment = async () => {
    if (!selectedZone) return
    const action = recommendedControlAction(selectedZone.status)
    if (!action) return
    setActionMessage('Aplicando ajuste...')
    const targets = selectedZone.actionableDevices.slice(0, 8)
    try {
      await Promise.all(targets.map((device: Device) => devicesApi.control(device.id, action, 1)))
      setActionMessage(`Ajuste enviado para ${targets.length} aparelho${targets.length === 1 ? '' : 's'}.`)
      await refetchDevices()
    } catch {
      setActionMessage('Não foi possível aplicar ajuste em todos os aparelhos.')
    }
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/mapa-termico')} className="rounded-lg p-2 text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-white">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div>
            <h1 className="font-semibold text-gray-900 dark:text-white">Conforto Térmico por Zona</h1>
            <p className="text-xs text-gray-500">Matriz - {formatFloor(selectedFloor)} • última atualização {formatRelativeTime(lastUpdate)}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {[1, 2, 3, 4].map(floor => (
            <button
              key={floor}
              type="button"
              onClick={() => setSelectedFloor(floor)}
              className={cn(
                'rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
                selectedFloor === floor ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800'
              )}
            >
              {formatFloor(floor)}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setShowEquipment(value => !value)}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            {showEquipment ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            Equipamentos
          </button>
          <button
            type="button"
            onClick={() => navigate(`/lojas/${storeId}/mapa`)}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800"
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Posicionamento
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        <ThermalKpi title="Temp. média" value={avgStoreTemp != null ? formatTemp(avgStoreTemp) : '—'} />
        <ThermalKpi title="Quentes" value={zoneStates.filter(zone => zone.status === 'HOT' || zone.status === 'CRITICAL').length} tone="text-orange-500" />
        <ThermalKpi title="Frias" value={zoneStates.filter(zone => zone.status === 'COLD').length} tone="text-blue-500" />
        <ThermalKpi title="Confortáveis" value={zoneStates.filter(zone => zone.status === 'COMFORT').length} tone="text-green-500" />
        <ThermalKpi title="Sem leitura" value={zoneStates.filter(zone => zone.status === 'NO_READING').length} tone="text-gray-500" />
        <ThermalKpi title="Ares vinculados" value={floorDevices.length} />
        <ThermalKpi title="Ares no mapa" value={positionedDevices.length} />
      </div>

      <div className="flex flex-wrap gap-2">
        {(['ALL', 'COLD', 'COMFORT', 'WARM', 'HOT', 'CRITICAL', 'NO_READING'] as const).map(status => (
          <button
            key={status}
            type="button"
            onClick={() => setStatusFilter(status)}
            className={cn(
              'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
              statusFilter === status ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800'
            )}
          >
            {status === 'ALL' ? 'Todos' : STATUS_META[status].label}
          </button>
        ))}
      </div>

      <div className="grid flex-1 min-h-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="relative overflow-hidden rounded-xl border border-gray-200 bg-gray-100 shadow-inner dark:border-gray-800 dark:bg-gray-950">
          {!floorPlanUrl && (
            <div className="absolute inset-0 z-10 flex items-center justify-center text-sm text-gray-500">
              Planta não cadastrada para este andar
            </div>
          )}
          <svg viewBox={`0 0 ${VIEWBOX.w} ${VIEWBOX.h}`} className="h-full w-full">
            <defs>
              <filter id="comfort-zone-shadow" x="-8%" y="-8%" width="116%" height="116%">
                <feDropShadow dx="0" dy="2" stdDeviation="4" floodOpacity="0.14" />
              </filter>
              <radialGradient id="zone-soft-edge">
                <stop offset="0%" stopColor="white" stopOpacity="0.9" />
                <stop offset="100%" stopColor="white" stopOpacity="0" />
              </radialGradient>
            </defs>
            <rect width={VIEWBOX.w} height={VIEWBOX.h} fill="#EEF2F7" />
            {floorPlanUrl && (
              <image href={floorPlanUrl} x={0} y={0} width={VIEWBOX.w} height={VIEWBOX.h} preserveAspectRatio="xMidYMid meet" opacity={0.68} filter="url(#comfort-zone-shadow)" />
            )}
            {visibleZones.map(zone => {
              const meta = STATUS_META[zone.status]
              const isSelected = selectedZone?.key === zone.key
              return (
                <g key={zone.key} onClick={() => { setSelectedZoneKey(zone.key); setActionMessage('') }} style={{ cursor: 'pointer' }}>
                  <rect
                    x={zone.x}
                    y={zone.y}
                    width={zone.w}
                    height={zone.h}
                    rx={16}
                    fill={meta.fill}
                    stroke={isSelected ? '#111827' : meta.color}
                    strokeWidth={isSelected ? 3 : 1.5}
                  />
                  <ellipse cx={zone.x + zone.w / 2} cy={zone.y + zone.h / 2} rx={zone.w * 0.45} ry={zone.h * 0.42} fill={meta.fill} opacity={0.6} />
                  <rect x={zone.x + 8} y={zone.y + 8} width={Math.min(zone.w - 16, 150)} height={34} rx={8} fill="rgba(17,24,39,0.72)" />
                  <text x={zone.x + 16} y={zone.y + 22} fontSize={10} fontWeight={700} fill="#FFFFFF">{zone.label}</text>
                  <text x={zone.x + 16} y={zone.y + 35} fontSize={10} fill="#E5E7EB">{zone.avgTemp != null ? formatTemp(zone.avgTemp) : 'Sem leitura'} • {meta.label}</text>
                </g>
              )
            })}
            {showEquipment && positionedDevices.map((device: Device) => (
              <DeviceMarker key={device.id} device={device} onClick={() => undefined} scale={0.78} />
            ))}
          </svg>
        </div>

        <aside className="overflow-y-auto rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
          {selectedZone ? (
            <ZonePanel
              zone={selectedZone}
              actionMessage={actionMessage}
              onApply={applyRecommendedAdjustment}
            />
          ) : (
            <div className="py-10 text-center text-sm text-gray-500">Selecione uma zona</div>
          )}
        </aside>
      </div>
    </div>
  )
}

function ZonePanel({ zone, actionMessage, onApply }: { zone: ReturnType<typeof buildZonePanelShape>; actionMessage: string; onApply: () => void }) {
  const meta = STATUS_META[zone.status]
  const action = recommendedText(zone.status)
  const canApply = Boolean(recommendedControlAction(zone.status)) && zone.actionableDevices.length > 0

  return (
    <div className="space-y-4">
      <div>
        <div className={cn('text-xs font-semibold uppercase', meta.text)}>{meta.label}</div>
        <h2 className="mt-1 text-lg font-semibold text-gray-900 dark:text-white">{zone.label}</h2>
        <p className="text-xs text-gray-500">Faixa ideal: {zone.idealMin}°C a {zone.idealMax}°C</p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <PanelMetric label="Temperatura" value={zone.avgTemp != null ? formatTemp(zone.avgTemp) : '—'} />
        <PanelMetric label="Aparelhos" value={zone.devices.length} />
        <PanelMetric label="Sensores usados" value={zone.devices.filter((device: Device) => device.temperature != null).length} />
        <PanelMetric label="Ajustáveis" value={zone.actionableDevices.length} />
      </div>

      <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
        <div className="text-xs font-semibold uppercase text-gray-500">Ação recomendada</div>
        <div className="mt-1 text-sm text-gray-900 dark:text-white">{action}</div>
        <button
          type="button"
          disabled={!canApply}
          onClick={onApply}
          className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500 dark:disabled:bg-gray-800"
        >
          <Zap className="h-4 w-4" />
          Aplicar ajuste recomendado
        </button>
        {actionMessage && <div className="mt-2 text-xs text-gray-500">{actionMessage}</div>}
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Aparelhos vinculados</h3>
        <div className="mt-2 space-y-2">
          {zone.devices.map((device: Device) => (
            <div key={device.id} className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-mono text-xs text-blue-500">{device.brise_id}</div>
                  <div className="truncate text-sm font-medium text-gray-900 dark:text-white">{device.name}</div>
                  <div className="text-xs text-gray-500">Temp. {formatTemp(device.temperature)}</div>
                </div>
                <StatusBadge status={device.status} size="sm" />
              </div>
            </div>
          ))}
          {!zone.devices.length && <div className="py-6 text-center text-sm text-gray-500">Nenhum aparelho vinculado</div>}
        </div>
      </div>
    </div>
  )
}

function ThermalKpi({ title, value, tone }: { title: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-800 dark:bg-gray-900">
      <div className="text-xs font-medium uppercase text-gray-500">{title}</div>
      <div className={cn('mt-1 text-xl font-semibold text-gray-900 dark:text-white', tone)}>{value}</div>
    </div>
  )
}

function PanelMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3 dark:bg-gray-950">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 font-semibold text-gray-900 dark:text-white">{value}</div>
    </div>
  )
}

function classifyZone(temp: number | null, min: number, max: number): ThermalStatus {
  if (temp == null) return 'NO_READING'
  if (temp < min) return 'COLD'
  if (temp <= max) return 'COMFORT'
  if (temp <= max + 1.5) return 'WARM'
  if (temp <= max + 3.5) return 'HOT'
  return 'CRITICAL'
}

function recommendedControlAction(status: ThermalStatus) {
  if (status === 'HOT' || status === 'CRITICAL' || status === 'WARM') return 'temperature_down' as const
  if (status === 'COLD') return 'temperature_up' as const
  return null
}

function recommendedText(status: ThermalStatus) {
  if (status === 'COLD') return 'Aumentar 1°C no setpoint dos aparelhos ajustáveis da zona.'
  if (status === 'WARM') return 'Reduzir 1°C no setpoint e reavaliar após 10 a 15 minutos.'
  if (status === 'HOT' || status === 'CRITICAL') return 'Reduzir 1°C no setpoint dos aparelhos ajustáveis da zona.'
  if (status === 'NO_READING') return 'Verificar sensores/aparelhos sem comunicação antes de ajustar.'
  return 'Manter configuração atual.'
}

function average(values: number[]) {
  if (!values.length) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function newestDate(values: string[]) {
  if (!values.length) return null
  return values.sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0]
}

function formatFloor(floor: number) {
  return `${floor}º andar`
}

function buildZonePanelShape() {
  return {
    ...ZONES[0],
    devices: [] as Device[],
    actionableDevices: [] as Device[],
    avgTemp: null as number | null,
    status: 'NO_READING' as ThermalStatus,
  }
}
