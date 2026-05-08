import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Eye, EyeOff, SlidersHorizontal, Thermometer, Wind, Zap } from 'lucide-react'
import { devicesApi, storesApi } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import DeviceMarker from '../components/map/DeviceMarker'
import { cn, formatRelativeTime, formatTemp } from '../lib/utils'
import type { Device, Sector } from '../types'

type ThermalStatus = 'COLD' | 'COMFORT' | 'WARM' | 'HOT' | 'CRITICAL' | 'NO_READING'
type SourceType = 'zone' | 'brise' | 'sensor' | 'merged'

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

interface HeatPoint {
  key: string
  label: string
  x: number
  y: number
  radius: number
  radiusM: number
  temp: number | null
  status: ThermalStatus
  opacity: number
  sourceType: SourceType
  lastUpdated?: string | null
  deviceId?: string
  mergedSources?: { label: string; temp: number; type: 'brise' | 'sensor' }[]
}

const VIEWBOX = { w: 800, h: 556 }

/** Pixels SVG por metro — escala aproximada para o Escritório Matriz */
const M_TO_SVG = 14

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
  { key: 'farmacia',    sectorNames: ['Farmácia'],    label: 'Farmácia',    x: 480, y: 110, w: 90,  h: 92,  idealMin: 20, idealMax: 22 },
  { key: 'presidencia', sectorNames: ['Presidência'], label: 'Presidência', x: 140, y: 145, w: 130, h: 80,  idealMin: 21, idealMax: 25 },
]

const STATUS_META: Record<ThermalStatus, { label: string; color: string; fill: string; text: string }> = {
  COLD:       { label: 'Frio demais',   color: '#2563EB', fill: 'rgba(37, 99, 235, 0.48)',  text: 'text-blue-600 dark:text-blue-400' },
  COMFORT:    { label: 'Confortável',   color: '#22C55E', fill: 'rgba(34, 197, 94, 0.38)',  text: 'text-green-600 dark:text-green-400' },
  WARM:       { label: 'Aquecendo',     color: '#EAB308', fill: 'rgba(234, 179, 8, 0.45)',  text: 'text-yellow-600 dark:text-yellow-400' },
  HOT:        { label: 'Quente',        color: '#F97316', fill: 'rgba(249, 115, 22, 0.48)', text: 'text-orange-600 dark:text-orange-400' },
  CRITICAL:   { label: 'Muito quente',  color: '#EF4444', fill: 'rgba(239, 68, 68, 0.52)',  text: 'text-red-600 dark:text-red-400' },
  NO_READING: { label: 'Sem leitura',   color: '#6B7280', fill: 'rgba(107, 114, 128, 0.28)',text: 'text-gray-500' },
}

export default function ThermalComfortMap() {
  const { storeId } = useParams<{ storeId: string }>()
  const navigate = useNavigate()
  const [selectedFloor, setSelectedFloor] = useState(1)
  const [selectedZoneKey, setSelectedZoneKey] = useState<string | null>(null)
  const [showEquipment, setShowEquipment] = useState(false)
  const [showBriseLyr, setShowBriseLyr] = useState(true)
  const [showSensorLyr, setShowSensorLyr] = useState(true)
  const [statusFilter, setStatusFilter] = useState<ThermalStatus | 'ALL'>('ALL')
  const [actionMessage, setActionMessage] = useState('')
  const [hoveredPoint, setHoveredPoint] = useState<HeatPoint | null>(null)

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

  const floorPlanUrl = sectors.find((s: Sector) => s.floor === selectedFloor && s.floor_plan_url)?.floor_plan_url ?? null
  const sectorsById = new Map<string, Sector>(sectors.map((s: Sector) => [s.id, s]))
  const floorDevices = devices.filter((d: Device) => sectorsById.get(d.sector_id || '')?.floor === selectedFloor)
  const positionedDevices = floorDevices.filter((d: Device) => d.position_x != null && d.position_y != null)

  const zoneStates = useMemo(() => ZONES.map(zone => {
    const zoneDevices = floorDevices.filter((d: Device) => zone.sectorNames.includes(d.sector_name || ''))
    const temperatureDevices = zoneDevices.filter((d: Device) => d.temperature != null)
    const avgTemp = temperatureDevices.length
      ? temperatureDevices.reduce((sum: number, d: Device) => sum + Number(d.temperature), 0) / temperatureDevices.length
      : null
    const status = classifyZone(avgTemp, zone.idealMin, zone.idealMax)
    const actionableDevices = zoneDevices.filter((d: Device) => !['SEM_LEITURA', 'DESLIGADO'].includes(d.status))
    return { ...zone, devices: zoneDevices, actionableDevices, avgTemp, status }
  }), [floorDevices])

  const visibleZones = statusFilter === 'ALL' ? zoneStates : zoneStates.filter(z => z.status === statusFilter)

  const heatPoints = useMemo(() => {
    const sectorIdealByName = new Map<string, Pick<ZoneDefinition, 'idealMin' | 'idealMax'>>()
    zoneStates.forEach(z => z.sectorNames.forEach(name => sectorIdealByName.set(name, z)))

    // Monta grupos por setor: sectorId → { acs, sensors }
    const sectorGroups = new Map<string, { acs: Device[]; sensors: Device[] }>()
    positionedDevices.forEach((d: Device) => {
      if (!d.sector_id || d.temperature == null) return
      if (!sectorGroups.has(d.sector_id)) sectorGroups.set(d.sector_id, { acs: [], sensors: [] })
      const g = sectorGroups.get(d.sector_id)!
      d.is_external_sensor ? g.sensors.push(d) : g.acs.push(d)
    })

    // IDs de sensores que foram fundidos com um AC (não geram blob independente)
    const mergedSensorIds = new Set<string>()

    // Pontos de zona (fundo)
    const zonePoints: HeatPoint[] = visibleZones.map(zone => ({
      key: `zone-${zone.key}`,
      label: zone.label,
      x: zone.x + zone.w / 2,
      y: zone.y + zone.h / 2,
      radius: Math.max(zone.w, zone.h) * 0.78,
      radiusM: Math.round(Math.max(zone.w, zone.h) * 0.78 / M_TO_SVG),
      temp: zone.avgTemp,
      status: zone.status,
      opacity: 0.55,
      sourceType: 'zone' as SourceType,
    }))

    // Pontos Brise — se ambas camadas ativas e há sensor no mesmo setor → funde
    const brisePoints: HeatPoint[] = showBriseLyr
      ? positionedDevices
          .filter((d: Device) => !d.is_external_sensor && d.temperature != null)
          .map((d: Device): HeatPoint => {
            const radiusM = d.influence_radius_m ?? 8
            const ideal = sectorIdealByName.get(d.sector_name || '')
            const sensorsInSector = showSensorLyr
              ? (sectorGroups.get(d.sector_id ?? '')?.sensors ?? [])
              : []

            if (sensorsInSector.length > 0) {
              // Funde: média de todas as temperaturas (AC + sensores do setor)
              const allTemps = [Number(d.temperature), ...sensorsInSector.map(s => Number(s.temperature))]
              const avgTemp = allTemps.reduce((a, b) => a + b, 0) / allTemps.length
              sensorsInSector.forEach(s => mergedSensorIds.add(s.id))
              return {
                key: `merged-${d.id}`,
                label: d.name,
                x: Number(d.position_x),
                y: Number(d.position_y),
                radius: radiusM * M_TO_SVG,
                radiusM,
                temp: avgTemp,
                status: classifyZone(avgTemp, ideal?.idealMin ?? 22, ideal?.idealMax ?? 24),
                opacity: 0.95,
                sourceType: 'merged',
                lastUpdated: d.updated_at,
                deviceId: d.id,
                mergedSources: [
                  { label: d.name, temp: Number(d.temperature), type: 'brise' },
                  ...sensorsInSector.map(s => ({ label: s.name, temp: Number(s.temperature), type: 'sensor' as const })),
                ],
              }
            }

            return {
              key: `brise-${d.id}`,
              label: d.name,
              x: Number(d.position_x),
              y: Number(d.position_y),
              radius: radiusM * M_TO_SVG,
              radiusM,
              temp: Number(d.temperature),
              status: classifyZone(Number(d.temperature), ideal?.idealMin ?? 22, ideal?.idealMax ?? 24),
              opacity: 0.95,
              sourceType: 'brise',
              lastUpdated: d.updated_at,
              deviceId: d.id,
            }
          })
      : []

    // Pontos de sensores não fundidos (sozinhos no setor ou camada Brise desligada)
    const sensorPoints: HeatPoint[] = showSensorLyr
      ? positionedDevices
          .filter((d: Device) => d.is_external_sensor && d.temperature != null && !mergedSensorIds.has(d.id))
          .map((d: Device): HeatPoint => {
            const radiusM = d.influence_radius_m ?? 8
            const ideal = sectorIdealByName.get(d.sector_name || '')
            return {
              key: `sensor-${d.id}`,
              label: d.name,
              x: Number(d.position_x),
              y: Number(d.position_y),
              radius: radiusM * M_TO_SVG,
              radiusM,
              temp: Number(d.temperature),
              status: classifyZone(Number(d.temperature), ideal?.idealMin ?? 22, ideal?.idealMax ?? 24),
              opacity: 0.90,
              sourceType: 'sensor',
              lastUpdated: d.updated_at,
              deviceId: d.id,
            }
          })
      : []

    const hasRealPoints = brisePoints.length > 0 || sensorPoints.length > 0
    const finalZonePoints = hasRealPoints ? zonePoints.map(z => ({ ...z, opacity: 0.42 })) : zonePoints

    const all = [...finalZonePoints, ...brisePoints, ...sensorPoints]
    return statusFilter === 'ALL' ? all : all.filter(p => p.status === statusFilter)
  }, [positionedDevices, showBriseLyr, showSensorLyr, statusFilter, visibleZones, zoneStates])

  const selectedZone = zoneStates.find(z => z.key === selectedZoneKey) ?? zoneStates[0] ?? null
  const avgStoreTemp = average(zoneStates.map(z => z.avgTemp).filter((v): v is number => v != null))
  const lastUpdate = newestDate(floorDevices.map((d: Device) => d.updated_at).filter(Boolean) as string[])
  const externalSensorsOnFloor = floorDevices.filter((d: Device) => d.is_external_sensor)
  const positionedSensors = externalSensorsOnFloor.filter((d: Device) => d.position_x != null)

  const applyRecommendedAdjustment = async () => {
    if (!selectedZone) return
    const action = recommendedControlAction(selectedZone.status)
    if (!action) return
    setActionMessage('Aplicando ajuste...')
    const targets = selectedZone.actionableDevices.slice(0, 8)
    try {
      await Promise.all(targets.map((d: Device) => devicesApi.control(d.id, action, 1)))
      setActionMessage(`Ajuste enviado para ${targets.length} aparelho${targets.length === 1 ? '' : 's'}.`)
      await refetchDevices()
    } catch {
      setActionMessage('Não foi possível aplicar ajuste em todos os aparelhos.')
    }
  }

  return (
    <div className="flex h-full flex-col gap-4">
      {/* ── Cabeçalho ── */}
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
          {/* Seletor de andar */}
          {[1, 2, 3, 4].map(floor => (
            <button key={floor} type="button" onClick={() => setSelectedFloor(floor)}
              className={cn('rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
                selectedFloor === floor ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800'
              )}>
              {formatFloor(floor)}
            </button>
          ))}

          {/* Camada Brise */}
          <button type="button" onClick={() => setShowBriseLyr(v => !v)}
            className={cn('inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
              showBriseLyr ? 'border-blue-500/40 bg-blue-500/10 text-blue-600 dark:text-blue-400' : 'border-gray-200 text-gray-400 hover:bg-gray-100 dark:border-gray-800 dark:hover:bg-gray-800'
            )}>
            <Wind className="h-3.5 w-3.5" />
            Brise
            {showBriseLyr ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
          </button>

          {/* Camada Termômetros */}
          <button type="button" onClick={() => setShowSensorLyr(v => !v)}
            className={cn('inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
              showSensorLyr ? 'border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'border-gray-200 text-gray-400 hover:bg-gray-100 dark:border-gray-800 dark:hover:bg-gray-800'
            )}>
            <Thermometer className="h-3.5 w-3.5" />
            Termômetros
            {showSensorLyr ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
          </button>

          {/* Ícones no mapa */}
          <button type="button" onClick={() => setShowEquipment(v => !v)}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800">
            {showEquipment ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            Ícones
          </button>

          <button type="button" onClick={() => navigate(`/lojas/${storeId}/mapa`)}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800">
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Posicionamento
          </button>
        </div>
      </div>

      {/* ── KPIs ── */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <ThermalKpi title="Temp. média" value={avgStoreTemp != null ? formatTemp(avgStoreTemp) : '—'} />
        <ThermalKpi title="Quentes"     value={zoneStates.filter(z => z.status === 'HOT' || z.status === 'CRITICAL').length} tone="text-orange-500" />
        <ThermalKpi title="Frias"       value={zoneStates.filter(z => z.status === 'COLD').length}    tone="text-blue-500" />
        <ThermalKpi title="Confortáveis" value={zoneStates.filter(z => z.status === 'COMFORT').length} tone="text-green-500" />
        <ThermalKpi title="Sem leitura" value={zoneStates.filter(z => z.status === 'NO_READING').length} tone="text-gray-500" />
        <ThermalKpi title="ACs no mapa" value={positionedDevices.filter((d: Device) => !d.is_external_sensor).length} />
        <ThermalKpi title="Sensores"    value={externalSensorsOnFloor.length} />
        <ThermalKpi title="Sens. no mapa" value={positionedSensors.length} />
      </div>

      {/* ── Filtros de status ── */}
      <div className="flex flex-wrap gap-2">
        {(['ALL', 'COLD', 'COMFORT', 'WARM', 'HOT', 'CRITICAL', 'NO_READING'] as const).map(s => (
          <button key={s} type="button" onClick={() => setStatusFilter(s)}
            className={cn('rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
              statusFilter === s ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800'
            )}>
            {s === 'ALL' ? 'Todos' : STATUS_META[s].label}
          </button>
        ))}
      </div>

      {/* ── Conteúdo principal ── */}
      <div className="grid flex-1 min-h-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        {/* SVG do mapa */}
        <div className="relative overflow-hidden rounded-xl border border-gray-200 bg-gray-100 shadow-inner dark:border-gray-800 dark:bg-gray-950">
          {!floorPlanUrl && (
            <div className="absolute inset-0 z-10 flex items-center justify-center text-sm text-gray-500">
              Planta não cadastrada para este andar
            </div>
          )}
          <svg viewBox={`0 0 ${VIEWBOX.w} ${VIEWBOX.h}`} className="h-full w-full">
            <defs>
              <filter id="thermal-blur" x="-30%" y="-30%" width="160%" height="160%" colorInterpolationFilters="sRGB">
                <feGaussianBlur stdDeviation="24" />
              </filter>
              {heatPoints.map(point => {
                const color = thermalColor(point.temp)
                return (
                  <radialGradient key={point.key} id={`tg-${point.key}`} cx="50%" cy="50%" r="50%">
                    <stop offset="0%"   stopColor={color} stopOpacity={point.opacity} />
                    <stop offset="40%"  stopColor={color} stopOpacity={point.opacity * 0.55} />
                    <stop offset="100%" stopColor={color} stopOpacity={0} />
                  </radialGradient>
                )
              })}
            </defs>

            {/* Fundo */}
            <rect width={VIEWBOX.w} height={VIEWBOX.h} fill="#F8FAFC" />

            {/* Planta */}
            {floorPlanUrl && (
              <image href={floorPlanUrl} x={0} y={0} width={VIEWBOX.w} height={VIEWBOX.h}
                preserveAspectRatio="xMidYMid meet" opacity={0.82} />
            )}

            {/* Camada térmica (blurred) */}
            <g filter="url(#thermal-blur)" style={{ mixBlendMode: 'multiply' }} opacity={0.80}>
              {heatPoints.map(point => (
                <circle key={point.key} cx={point.x} cy={point.y} r={point.radius} fill={`url(#tg-${point.key})`} />
              ))}
            </g>

            {/* Zonas clicáveis (transparentes) */}
            {visibleZones.map(zone => {
              const meta = STATUS_META[zone.status]
              return (
                <g key={zone.key} onClick={() => { setSelectedZoneKey(zone.key); setActionMessage('') }} style={{ cursor: 'pointer' }}>
                  <rect x={zone.x} y={zone.y} width={zone.w} height={zone.h} fill="transparent" pointerEvents="all" />
                  <title>{zone.label} — {zone.avgTemp != null ? formatTemp(zone.avgTemp) : 'Sem leitura'} — {meta.label}</title>
                </g>
              )
            })}

            {/* Sem leituras */}
            {heatPoints.length === 0 && floorPlanUrl && (
              <g pointerEvents="none">
                <rect width={VIEWBOX.w} height={VIEWBOX.h} fill="rgba(107,114,128,0.16)" />
                <text x={VIEWBOX.w / 2} y={VIEWBOX.h / 2} textAnchor="middle" fontSize={14} fontWeight={700} fill="#4B5563">
                  Sem leituras para gerar o campo térmico
                </text>
              </g>
            )}

            {/* Ícones (ACs e sensores) */}
            {showEquipment && positionedDevices.map((d: Device) => (
              <DeviceMarker key={d.id} device={d} onClick={() => undefined} scale={0.78} />
            ))}

            {/* Áreas de hit invisíveis para tooltip — sobre tudo, sem blur */}
            {heatPoints
              .filter(p => p.sourceType !== 'zone')
              .map(point => (
                <circle
                  key={`hit-${point.key}`}
                  cx={point.x}
                  cy={point.y}
                  r={32}
                  fill="transparent"
                  style={{ cursor: 'crosshair' }}
                  onMouseEnter={() => setHoveredPoint(point)}
                  onMouseLeave={() => setHoveredPoint(null)}
                />
              ))}

            {/* Tooltip SVG */}
            {hoveredPoint && (() => {
              const isMerged = hoveredPoint.sourceType === 'merged'
              const sources = hoveredPoint.mergedSources ?? []
              const boxH = isMerged ? 60 + sources.length * 16 : 80
              const tx = Math.min(hoveredPoint.x + 20, VIEWBOX.w - 182)
              const ty = Math.max(hoveredPoint.y - boxH - 4, 4)
              const srcLabel = isMerged ? 'Média (AC + Sensor)' : hoveredPoint.sourceType === 'sensor' ? 'Termômetro' : 'Brise'
              const srcColor = isMerged ? '#A78BFA' : hoveredPoint.sourceType === 'sensor' ? '#F59E0B' : '#3B82F6'
              return (
                <g transform={`translate(${tx},${ty})`} pointerEvents="none">
                  <rect width={178} height={boxH} rx={7} fill="rgba(15,23,42,0.95)" />
                  <rect width={4} height={boxH} rx={2} fill={srcColor} />
                  <text fill="#F1F5F9" fontSize={11} x={12} y={18} fontWeight="600">{hoveredPoint.label}</text>
                  <text fill={srcColor} fontSize={9} x={12} y={30} fontWeight="600">{srcLabel}</text>
                  <text fill="#94A3B8" fontSize={10} x={12} y={44}>
                    {hoveredPoint.temp != null ? `${hoveredPoint.temp.toFixed(1)}°C` : 'Sem leitura'}
                    {' '}• raio {hoveredPoint.radiusM}m
                  </text>
                  {isMerged && sources.map((src, i) => (
                    <text key={src.label} fill={src.type === 'brise' ? '#60A5FA' : '#FCD34D'} fontSize={9} x={12} y={58 + i * 16}>
                      {src.type === 'brise' ? '⬡' : '○'} {src.label}: {src.temp.toFixed(1)}°C
                    </text>
                  ))}
                  {!isMerged && (
                    <text fill="#64748B" fontSize={9} x={12} y={58}>
                      {formatRelativeTime(hoveredPoint.lastUpdated ?? null)}
                    </text>
                  )}
                  <text fill={thermalColor(hoveredPoint.temp)} fontSize={9} x={12} y={boxH - 7} fontWeight="600">
                    {hoveredPoint.status !== 'NO_READING' ? STATUS_META[hoveredPoint.status].label : 'Sem leitura'}
                  </text>
                </g>
              )
            })()}
          </svg>
        </div>

        {/* Painel lateral */}
        <aside className="overflow-y-auto rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900">
          {selectedZone ? (
            <ZonePanel zone={selectedZone} actionMessage={actionMessage} onApply={applyRecommendedAdjustment} />
          ) : (
            <div className="py-10 text-center text-sm text-gray-500">Selecione uma zona</div>
          )}
        </aside>
      </div>

      {/* Legenda de escala */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-gray-500">
        <div className="flex items-center gap-1.5">
          <div className="h-3 w-3 rounded-full" style={{ background: '#1D4ED8' }} />≤19°C
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-3 w-3 rounded-full" style={{ background: '#00A6D6' }} />21°C
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-3 w-3 rounded-full" style={{ background: '#16A34A' }} />23°C
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-3 w-3 rounded-full" style={{ background: '#FACC15' }} />25°C
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-3 w-3 rounded-full" style={{ background: '#FB923C' }} />27°C
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-3 w-3 rounded-full" style={{ background: '#DC2626' }} />&gt;27°C
        </div>
        <span className="ml-auto">Raio padrão: 8m — {M_TO_SVG}px/m</span>
      </div>
    </div>
  )
}

/* ── Componentes auxiliares ── */

function ZonePanel({ zone, actionMessage, onApply }: { zone: any; actionMessage: string; onApply: () => void }) {
  const meta = STATUS_META[zone.status as ThermalStatus]
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
        <PanelMetric label="Aparelhos"   value={zone.devices.length} />
        <PanelMetric label="Sensores"    value={zone.devices.filter((d: Device) => d.temperature != null).length} />
        <PanelMetric label="Ajustáveis"  value={zone.actionableDevices.length} />
      </div>

      <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
        <div className="text-xs font-semibold uppercase text-gray-500">Ação recomendada</div>
        <div className="mt-1 text-sm text-gray-900 dark:text-white">{action}</div>
        <button type="button" disabled={!canApply} onClick={onApply}
          className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500 dark:disabled:bg-gray-800">
          <Zap className="h-4 w-4" />
          Aplicar ajuste recomendado
        </button>
        {actionMessage && <div className="mt-2 text-xs text-gray-500">{actionMessage}</div>}
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">Aparelhos vinculados</h3>
        <div className="mt-2 space-y-2">
          {zone.devices.map((d: Device) => (
            <div key={d.id} className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1 font-mono text-xs">
                    {d.is_external_sensor
                      ? <><Thermometer className="h-3 w-3 text-amber-500" /><span className="text-amber-500">Sensor</span></>
                      : <span className="text-blue-500">{d.brise_id}</span>
                    }
                  </div>
                  <div className="truncate text-sm font-medium text-gray-900 dark:text-white">{d.name}</div>
                  <div className="text-xs text-gray-500">Temp. {formatTemp(d.temperature)}</div>
                </div>
                <StatusBadge status={d.status} size="sm" />
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

/* ── Funções puras ── */

function classifyZone(temp: number | null, min: number, max: number): ThermalStatus {
  if (temp == null)       return 'NO_READING'
  if (temp < min)         return 'COLD'
  if (temp <= max)        return 'COMFORT'
  if (temp <= max + 1.5)  return 'WARM'
  if (temp <= max + 3.5)  return 'HOT'
  return 'CRITICAL'
}

function thermalColor(temp: number | null) {
  if (temp == null)  return '#9CA3AF'
  if (temp <= 19)    return '#1D4ED8'
  if (temp <= 21)    return '#00A6D6'
  if (temp <= 23.5)  return '#16A34A'
  if (temp <= 25.5)  return '#FACC15'
  if (temp <= 27.5)  return '#FB923C'
  return '#DC2626'
}

function recommendedControlAction(status: ThermalStatus) {
  if (status === 'HOT' || status === 'CRITICAL' || status === 'WARM') return 'temperature_down' as const
  if (status === 'COLD') return 'temperature_up' as const
  return null
}

function recommendedText(status: ThermalStatus) {
  if (status === 'COLD')       return 'Aumentar 1°C no setpoint dos aparelhos ajustáveis da zona.'
  if (status === 'WARM')       return 'Reduzir 1°C no setpoint e reavaliar após 10 a 15 minutos.'
  if (status === 'HOT' || status === 'CRITICAL') return 'Reduzir 1°C no setpoint dos aparelhos ajustáveis da zona.'
  if (status === 'NO_READING') return 'Verificar sensores/aparelhos sem comunicação antes de ajustar.'
  return 'Manter configuração atual.'
}

function average(values: number[]) {
  if (!values.length) return null
  return values.reduce((s, v) => s + v, 0) / values.length
}

function newestDate(values: string[]) {
  if (!values.length) return null
  return values.sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0]
}

function formatFloor(floor: number) {
  return `${floor}º andar`
}
