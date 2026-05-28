import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, ArrowLeft, Bot, ChevronDown, ChevronUp, Clock,
  Eye, EyeOff, Layers, Lock, Minus, PlayCircle, Plus, RefreshCw,
  RotateCcw, Shield, ShieldOff, SlidersHorizontal,
  Thermometer, TrendingDown, TrendingUp, Wind, Wrench, Zap,
} from 'lucide-react'
import { automationApi, customZonesApi, devicesApi, digitalTwinApi, storesApi, zonesApi } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import DeviceMarker from '../components/map/DeviceMarker'
import ZoneEditor from '../components/map/ZoneEditor'
import { cn, formatDateTime, formatRelativeTime, formatTemp, formatTime } from '../lib/utils'
import { useAuthStore } from '../store/useAuthStore'
import type { AutomationStatus, Device, DigitalTwinZone, Sector, ZoneAutomationState, ZoneMode, ZonePriority, ZoneType } from '../types'

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
  zone_type: ZoneType
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

type ZoneState = ZoneDefinition & {
  devices: Device[]
  actionableDevices: Device[]
  avgTemp: number | null
  status: ThermalStatus
}

const VIEWBOX = { w: 800, h: 556 }

/** Pixels SVG por metro — escala aproximada para o Escritório Matriz */
const M_TO_SVG = 14

/** Resolução da grade IDW em pixels SVG */
const GRID_CELL = 12

// ── Definição de zonas com tipo (ABERTA | SALA_FECHADA) ──────────────────────
// Coordenadas baseadas na planta 1.png (viewbox 800×556).
// ABERTA: área ampla sem barreiras relevantes — interpolação térmica contínua.
// SALA_FECHADA: sala com paredes — isolamento térmico, borda tracejada no mapa.
const ZONES: ZoneDefinition[] = [
  // ── Escritório Matriz ─────────────────────────────────────────────────────────
  { key: 'convivencia',   sectorNames: ['Convivência','Refeitório','Salas de Descanso'], label: 'Convivência',           x: 125, y: 8,   w: 250, h: 105, idealMin: 22, idealMax: 24, zone_type: 'ABERTA' },
  { key: 'sac',           sectorNames: ['SAC'],                                          label: 'SAC',                   x: 70,  y: 128, w: 245, h: 112, idealMin: 22, idealMax: 24, zone_type: 'ABERTA' },
  { key: 'conta-bemol',   sectorNames: ['Conta Bemol'],                                  label: 'Conta Bemol',           x: 340, y: 140, w: 118, h: 92,  idealMin: 22, idealMax: 24, zone_type: 'ABERTA' },
  { key: 'auditorio',     sectorNames: ['Auditório'],                                    label: 'Auditório',             x: 105, y: 250, w: 220, h: 82,  idealMin: 22, idealMax: 24, zone_type: 'ABERTA' },
  { key: 'comercial',     sectorNames: ['Comercial'],                                    label: 'Comercial',             x: 515, y: 155, w: 210, h: 92,  idealMin: 22, idealMax: 24, zone_type: 'ABERTA' },
  { key: 'marketing',     sectorNames: ['Marketing','Marketplace'],                      label: 'Marketing / Marketplace', x: 545, y: 265, w: 210, h: 92, idealMin: 22, idealMax: 24, zone_type: 'ABERTA' },
  { key: 'contabilidade', sectorNames: ['Contabilidade','Gestão de Risco'],              label: 'Contabilidade / Risco', x: 520, y: 365, w: 235, h: 90,  idealMin: 22, idealMax: 24, zone_type: 'ABERTA' },
  { key: 'bemol-online',  sectorNames: ['Bemol Online','Televendas'],                   label: 'Online / Televendas',   x: 128, y: 360, w: 245, h: 128, idealMin: 22, idealMax: 24, zone_type: 'ABERTA' },
  { key: 'geral',         sectorNames: ['Geral','Recepção','CAB'],                       label: 'Área central',          x: 330, y: 250, w: 145, h: 150, idealMin: 22, idealMax: 24, zone_type: 'ABERTA' },
  { key: 'farmacia',      sectorNames: ['Farmácia'],                                     label: 'Farmácia',              x: 480, y: 110, w: 90,  h: 92,  idealMin: 20, idealMax: 22, zone_type: 'ABERTA' },
  { key: 'presidencia',   sectorNames: ['Presidência'],                                  label: 'Presidência',           x: 140, y: 145, w: 130, h: 80,  idealMin: 21, idealMax: 25, zone_type: 'ABERTA' },

  // ── Farma Flores (planta 1376×768 → SVG 800×556, escala 0.58, y-offset 55) ──
  // Prédio: x 20–782, y 102–462. Salão=14.1m, fundo=3.2m (12m largura).
  { key: 'farma-vendas',      sectorNames: ['Área de Vendas'],  label: 'Salão de Vendas', x: 20,  y: 102, w: 480, h: 360, idealMin: 20, idealMax: 24, zone_type: 'ABERTA'      },
  { key: 'farma-dispensario', sectorNames: ['Dispensário'],     label: 'Dispensário',     x: 500, y: 102, w: 90,  h: 360, idealMin: 20, idealMax: 22, zone_type: 'SALA_FECHADA' },
  { key: 'farma-admin',       sectorNames: ['Administrativa'],  label: 'Administrativa',  x: 590, y: 102, w: 192, h: 200, idealMin: 22, idealMax: 24, zone_type: 'SALA_FECHADA' },
  { key: 'farma-escritorio',  sectorNames: ['Escritório'],      label: 'Escritório',      x: 590, y: 302, w: 192, h: 160, idealMin: 22, idealMax: 24, zone_type: 'SALA_FECHADA' },
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
  const [searchParams] = useSearchParams()
  const [selectedFloor, setSelectedFloor] = useState(1)
  const [selectedZoneKey, setSelectedZoneKey] = useState<string | null>(null)
  const [layers, setLayers] = useState({
    plant:    true,
    heatmap:  true,
    zones:    true,
    sensors:  true,
    devices:  false,
    alerts:   true,
  })
  const [showLayers, setShowLayers] = useState(false)
  const toggleLayer = (k: keyof typeof layers) => setLayers(l => ({ ...l, [k]: !l[k] }))

  const editModeRef = useRef(false)
  const { role } = useAuthStore()
  const [editMode, setEditMode] = useState(false)
  const handleSetEditMode = useCallback((v: boolean | ((prev: boolean) => boolean)) => {
    const next = typeof v === 'function' ? v(editModeRef.current) : v
    editModeRef.current = next
    setEditMode(next)
  }, [])
  const { transform, containerRef, hasMoved, zoom, resetView, containerHandlers } = useMapTransform(editModeRef)
  const svgRef = useRef<SVGSVGElement>(null)

  const [statusFilter, setStatusFilter] = useState<ThermalStatus | 'ALL'>('ALL')
  const [actionMessage, setActionMessage] = useState('')

  useEffect(() => {
    if (searchParams.get('editZones') !== '1') return
    handleSetEditMode(true)
    const zoneKey = searchParams.get('zone')
    if (zoneKey) setSelectedZoneKey(zoneKey)
    setActionMessage('Modo edição ativo: arraste na planta para criar uma zona ou clique em uma zona existente para editar.')
  }, [searchParams, handleSetEditMode])
  const [hoveredPoint, setHoveredPoint] = useState<HeatPoint | null>(null)

  const { data: devices = [], refetch: refetchDevices } = useQuery({
    queryKey: ['store-devices', storeId],
    queryFn: () => storesApi.devices(storeId!),
    enabled: !!storeId,
    refetchInterval: 30000,
  })

  // Zonas customizadas do backend (com geometry)
  const { data: customZones = [] } = useQuery<import('../types').CustomZone[]>({
    queryKey: ['custom-zones', storeId],
    queryFn: () => customZonesApi.list(storeId!),
    enabled: !!storeId,
    refetchInterval: 60_000,
  })

  const { data: sectors = [] } = useQuery({
    queryKey: ['store-sectors', storeId],
    queryFn: () => storesApi.sectors(storeId!),
    enabled: !!storeId,
  })

  const { data: zonesData = [], refetch: refetchZones } = useQuery<ZoneAutomationState[]>({
    queryKey: ['zones-automation', storeId],
    queryFn: () => zonesApi.list(storeId!),
    enabled: !!storeId,
    refetchInterval: 60_000,
  })

  const { data: autoStatus, refetch: refetchAutoStatus } = useQuery<AutomationStatus>({
    queryKey: ['automation-status'],
    queryFn: () => automationApi.status(),
    refetchInterval: 30_000,
  })

  const { data: twinData = [] } = useQuery<DigitalTwinZone[]>({
    queryKey: ['digital-twin', storeId],
    queryFn: () => digitalTwinApi.store(storeId!),
    enabled: !!storeId,
    refetchInterval: 60_000,
    staleTime: 45_000,
  })

  const [togglingKillSwitch, setTogglingKillSwitch] = useState(false)

  const handleKillSwitch = async (activate: boolean) => {
    setTogglingKillSwitch(true)
    setActionMessage('')
    try {
      await automationApi.setKillSwitch(activate)
      await refetchAutoStatus()
      await refetchZones()
    } catch {
      setActionMessage('Não foi possível alterar o kill switch.')
    } finally {
      setTogglingKillSwitch(false)
    }
  }

  const floorPlanUrl = sectors.find((s: Sector) => s.floor === selectedFloor && s.floor_plan_url)?.floor_plan_url ?? null
  const sectorsById = new Map<string, Sector>(sectors.map((s: Sector) => [s.id, s]))
  const floorDevices = devices.filter((d: Device) => sectorsById.get(d.sector_id || '')?.floor === selectedFloor)
  const positionedDevices = floorDevices.filter((d: Device) => d.position_x != null && d.position_y != null)

  // Zonas customizadas deste andar com geometry
  const floorCustomZones = useMemo(
    () => customZones.filter(z => z.floor === selectedFloor && z.geometry != null),
    [customZones, selectedFloor]
  )

  // ── Apenas zonas customizadas — hardcoded removido ──────────────────────────
  const zoneStates = useMemo(() => floorCustomZones.map(cz => {
    const zoneDevices = devices.filter((d: Device) => cz.device_ids.includes(d.id))
    const temperatureDevices = zoneDevices.filter((d: Device) => d.temperature != null)
    const avgTemp = temperatureDevices.length
      ? temperatureDevices.reduce((sum: number, d: Device) => sum + Number(d.temperature), 0) / temperatureDevices.length
      : null
    const status = classifyZone(avgTemp, cz.ideal_min, cz.ideal_max)
    const actionableDevices = zoneDevices.filter((d: Device) => !['SEM_LEITURA', 'LEITURA_STALE', 'AGUARDANDO_LEITURA', 'DESLIGADO', 'COMPRESSOR_CYCLING'].includes(d.status))
    return {
      key: cz.zone_key, label: cz.name,
      x: 0, y: 0, w: 0, h: 0,
      idealMin: cz.ideal_min, idealMax: cz.ideal_max,
      zone_type: cz.zone_type as ZoneType,
      sectorNames: [] as string[],
      devices: zoneDevices, actionableDevices, avgTemp, status,
    }
  }), [floorCustomZones, devices])

  // Bug 9: contadores usam o array final (inclui custom zones)
  const visibleZones = statusFilter === 'ALL'
    ? zoneStates
    : zoneStates.filter(z => z.status === statusFilter)
  const legacyRectZones = visibleZones.filter(z => z.w > 0 && z.h > 0)

  // ── Heat points ────────────────────────────────────────────────────────────
  const heatPoints = useMemo(() => {
    const sectorIdealByName = new Map<string, Pick<ZoneDefinition, 'idealMin' | 'idealMax'>>()
    zoneStates.forEach(z => z.sectorNames.forEach(name => sectorIdealByName.set(name, z)))

    const sectorGroups = new Map<string, { acs: Device[]; sensors: Device[] }>()
    positionedDevices.forEach((d: Device) => {
      if (!d.sector_id || d.temperature == null) return
      if (!sectorGroups.has(d.sector_id)) sectorGroups.set(d.sector_id, { acs: [], sensors: [] })
      const g = sectorGroups.get(d.sector_id)!
      d.is_external_sensor ? g.sensors.push(d) : g.acs.push(d)
    })

    const mergedSensorIds = new Set<string>()

    // Zonas customizadas têm w=0/h=0 — excluídas do heatmap (usam geometry via ZoneEditor)
    const zonePoints: HeatPoint[] = visibleZones
      .filter(zone => zone.w > 0 && zone.h > 0)
      .map(zone => ({
        key: `zone-${zone.key}`,
        label: zone.label,
        x: zone.x + zone.w / 2,
        y: zone.y + zone.h / 2,
        radius: Math.max(zone.w, zone.h) / 2,
        radiusM: Math.round(Math.max(zone.w, zone.h) / 2 / M_TO_SVG),
        temp: zone.avgTemp,
        status: zone.status,
        opacity: 0.55,
        sourceType: 'zone' as SourceType,
      }))

    // ACs sempre alimentam o IDW — layers.devices só controla ícones e labels
    const brisePoints: HeatPoint[] = positionedDevices
      .filter((d: Device) => !d.is_external_sensor && d.temperature != null)
      .map((d: Device): HeatPoint => {
        const radiusM = d.influence_radius_m ?? 8
        const radiusPx = radiusM * M_TO_SVG
        const ideal = sectorIdealByName.get(d.sector_name || '')
        const sensorsInSector = layers.sensors
          ? (sectorGroups.get(d.sector_id ?? '')?.sensors ?? [])
          : []

        if (sensorsInSector.length > 0) {
          const allTemps = [Number(d.temperature), ...sensorsInSector.map(s => Number(s.temperature))]
          const avgTemp = allTemps.reduce((a, b) => a + b, 0) / allTemps.length
          sensorsInSector.forEach(s => mergedSensorIds.add(s.id))
          return {
            key: `merged-${d.id}`,
            label: d.name,
            x: Number(d.position_x),
            y: Number(d.position_y),
            radius: radiusPx,
            radiusM,
            temp: avgTemp,
            status: classifyZone(avgTemp, ideal?.idealMin ?? 22, ideal?.idealMax ?? 24),
            opacity: 0.85,
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
          radius: radiusPx,
          radiusM,
          temp: Number(d.temperature),
          status: classifyZone(Number(d.temperature), ideal?.idealMin ?? 22, ideal?.idealMax ?? 24),
          opacity: 0.85,
          sourceType: 'brise',
          lastUpdated: d.updated_at,
          deviceId: d.id,
        }
      })

    const sensorPoints: HeatPoint[] = layers.sensors
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
  }, [positionedDevices, layers.devices, layers.sensors, statusFilter, visibleZones, zoneStates])

  const selectedZone = zoneStates.find(z => z.key === selectedZoneKey) ?? zoneStates[0] ?? null
  const avgStoreTemp = average(zoneStates.map(z => z.avgTemp).filter((v): v is number => v != null))

  const floorConfig = useMemo(() => getFloorConfig(selectedFloor), [selectedFloor])

  // Polígonos SVG para cada zona — com banda ideal e freshness_ratio do twin
  const zonePolygons = useMemo<ZonePoly[]>(() => {
    const twinByKey = new Map(twinData.map(t => [t.zone_key, t]))
    const polys: ZonePoly[] = []
    for (const cz of floorCustomZones) {
      const g = cz.geometry
      if (g?.unit === 'percent' && g.points?.length >= 3) {
        polys.push({
          poly: g.points.map(p => ({ x: p.x / 100 * VIEWBOX.w, y: p.y / 100 * VIEWBOX.h })),
          idealMin: cz.ideal_min,
          idealMax: cz.ideal_max,
          freshnessRatio: twinByKey.get(cz.zone_key)?.freshness_ratio ?? 1.0,
        })
      }
    }
    for (const z of legacyRectZones) {
      if (z.w > 0 && z.h > 0) {
        polys.push({
          poly: [
            { x: z.x,       y: z.y       },
            { x: z.x + z.w, y: z.y       },
            { x: z.x + z.w, y: z.y + z.h },
            { x: z.x,       y: z.y + z.h },
          ],
          idealMin: z.idealMin,
          idealMax: z.idealMax,
          freshnessRatio: twinByKey.get(z.key)?.freshness_ratio ?? 1.0,
        })
      }
    }
    return polys
  }, [floorCustomZones, legacyRectZones, twinData])

  const thermalGrid = useMemo(
    () => buildThermalGrid(heatPoints, avgStoreTemp, zonePolygons),
    [heatPoints, avgStoreTemp, zonePolygons],
  )

  const lastUpdate = newestDate(floorDevices.map((d: Device) => d.updated_at).filter(Boolean) as string[])
  const externalSensorsOnFloor = floorDevices.filter((d: Device) => d.is_external_sensor)
  const positionedSensors = externalSensorsOnFloor.filter((d: Device) => d.position_x != null)

  const activeZoneKey = selectedZone?.key ?? null
  const zoneAutomation = zonesData.find(z => z.zone_key === activeZoneKey)
  const activeTwin = twinData.find(z => z.zone_key === activeZoneKey)

  const handleModeChange = async (mode: ZoneMode) => {
    if (!storeId || !activeZoneKey) return
    setActionMessage('Alterando modo da zona...')
    try {
      await zonesApi.setMode(storeId, activeZoneKey, { mode })
      setActionMessage('Modo da zona atualizado.')
      await refetchZones()
    } catch {
      setActionMessage('Não foi possível alterar o modo da zona.')
    }
  }

  const handleTrigger = async () => {
    if (!storeId || !activeZoneKey) return
    setActionMessage('Disparando avaliação...')
    try {
      await zonesApi.trigger(storeId, activeZoneKey)
      setActionMessage('Avaliação concluída.')
      await refetchDevices()
      await refetchZones()
    } catch {
      setActionMessage('Erro ao disparar avaliação.')
    }
  }

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
          {[1, 2, 3, 4].map(floor => (
            <button key={floor} type="button" onClick={() => setSelectedFloor(floor)}
              className={cn('rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
                selectedFloor === floor ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800'
              )}>
              {formatFloor(floor)}
            </button>
          ))}

          {/* Layers dropdown */}
          <div className="relative">
            <button type="button" onClick={() => setShowLayers(v => !v)}
              className={cn('inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
                showLayers ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800'
              )}>
              <Layers className="h-3.5 w-3.5" />
              Camadas
            </button>
            {showLayers && (
              <div className="absolute right-0 top-9 z-50 min-w-[180px] rounded-xl border border-gray-200 bg-white p-2 shadow-xl dark:border-gray-700 dark:bg-gray-900">
                {([
                  { key: 'plant',   label: 'Planta base',      icon: <SlidersHorizontal className="h-3 w-3" /> },
                  { key: 'heatmap', label: 'Mapa de calor',     icon: <Wind className="h-3 w-3" /> },
                  { key: 'zones',   label: 'Zonas térmicas',    icon: <Layers className="h-3 w-3" /> },
                  { key: 'sensors', label: 'Sensores',          icon: <Thermometer className="h-3 w-3" /> },
                  { key: 'devices', label: 'Equipamentos (AC)', icon: <Wind className="h-3 w-3" /> },
                ] as const).map(({ key, label, icon }) => (
                  <button key={key} type="button"
                    onClick={() => toggleLayer(key)}
                    className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800">
                    {layers[key]
                      ? <Eye className="h-3.5 w-3.5 text-blue-500" />
                      : <EyeOff className="h-3.5 w-3.5 text-gray-400" />}
                    <span className={layers[key] ? 'text-gray-900 dark:text-white' : 'text-gray-400'}>{label}</span>
                    <span className="ml-auto">{icon}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => handleSetEditMode(v => !v)}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors',
              editMode
                ? 'border-violet-500 bg-violet-600 text-white hover:bg-violet-500'
                : 'border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800',
            )}>
            ✏ {editMode ? 'Sair do editor' : 'Editar zonas'}
          </button>

          <button type="button" onClick={() => navigate(`/lojas/${storeId}/mapa`)}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800">
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Posicionamento
          </button>

          {/* Bug 21: kill switch só aparece para ADMIN */}
          {role === 'ADMIN' && <button
            type="button"
            disabled={togglingKillSwitch}
            onClick={() => handleKillSwitch(!autoStatus?.kill_switch_active)}
            title={autoStatus?.kill_switch_active ? 'Reativar automação' : 'Pausar toda a automação agora'}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors',
              autoStatus?.kill_switch_active
                ? 'border-red-500 bg-red-500 text-white hover:bg-red-600'
                : 'border-gray-200 text-gray-600 hover:border-red-300 hover:bg-red-50 hover:text-red-600 dark:border-gray-800 dark:text-gray-400',
            )}
          >
            {autoStatus?.kill_switch_active
              ? <><ShieldOff className="h-3.5 w-3.5" /> Auto PAUSADA</>
              : <><Shield className="h-3.5 w-3.5" /> Kill switch</>
            }
          </button>}
        </div>
      </div>

      {/* ── Banner kill switch ── */}
      {autoStatus?.kill_switch_active && (
        <div className="flex items-center gap-3 rounded-lg border border-red-300 bg-red-50 px-4 py-2.5 dark:border-red-800 dark:bg-red-950/40">
          <ShieldOff className="h-4 w-4 flex-shrink-0 text-red-600 dark:text-red-400" />
          <div className="flex-1 min-w-0">
            <span className="text-sm font-semibold text-red-700 dark:text-red-400">Automação global pausada</span>
            <span className="ml-2 text-xs text-red-500">
              Nenhum ajuste automático será executado até reativar.
              {autoStatus.kill_switch_activated_by && ` Pausado por: ${autoStatus.kill_switch_activated_by}.`}
            </span>
          </div>
          <button type="button" onClick={() => handleKillSwitch(false)}
            className="flex-shrink-0 rounded-md bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-500">
            Reativar
          </button>
        </div>
      )}

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
        {/* SVG do mapa — pan/zoom interativo */}
        <div
          ref={containerRef}
          className="relative overflow-hidden rounded-xl border border-gray-200 bg-gray-950 shadow-inner dark:border-gray-800"
          style={{ touchAction: 'none' }}
          {...containerHandlers}
          onClick={e => { if (hasMoved.current) { hasMoved.current = false; e.stopPropagation() } }}
        >
          {!floorPlanUrl && (
            <div className="absolute inset-0 z-10 flex items-center justify-center text-sm text-gray-500">
              Planta não cadastrada para este andar
            </div>
          )}

          {/* Controles de zoom */}
          <div className="absolute right-2 top-2 z-20 flex flex-col gap-1">
            <button type="button" onClick={e => { e.stopPropagation(); zoom(1.25) }}
              className="flex h-7 w-7 items-center justify-center rounded-lg bg-gray-800/80 text-gray-300 backdrop-blur hover:bg-gray-700 hover:text-white">
              <Plus className="h-3.5 w-3.5" />
            </button>
            <button type="button" onClick={e => { e.stopPropagation(); resetView() }}
              title="Resetar zoom"
              className="flex h-7 w-7 items-center justify-center rounded-lg bg-gray-800/80 text-gray-300 backdrop-blur hover:bg-gray-700 hover:text-white">
              <RotateCcw className="h-3 w-3" />
            </button>
            <button type="button" onClick={e => { e.stopPropagation(); zoom(0.8) }}
              className="flex h-7 w-7 items-center justify-center rounded-lg bg-gray-800/80 text-gray-300 backdrop-blur hover:bg-gray-700 hover:text-white">
              <Minus className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* Indicador de zoom */}
          {transform.scale !== 1 && (
            <div className="absolute bottom-2 right-2 z-20 rounded-md bg-gray-800/80 px-2 py-0.5 text-[10px] text-gray-400 backdrop-blur">
              {Math.round(transform.scale * 100)}%
            </div>
          )}

          <svg
            ref={svgRef}
            viewBox={`0 0 ${VIEWBOX.w} ${VIEWBOX.h}`}
            className="h-full w-full"
            style={{
              transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
              transformOrigin: '0 0',
              cursor: transform.dragging ? 'grabbing' : 'grab',
              willChange: 'transform',
            }}
          >
            <defs>
              <clipPath id="floor-clip">
                <rect x={floorConfig.imageX} y={floorConfig.imageY}
                  width={floorConfig.imageW} height={floorConfig.imageH} />
              </clipPath>
              {/* IDW overlay: blur suaviza transições entre células; clipPath limita à zona da planta */}
              <filter id="thermal-blur" x="-8%" y="-8%" width="116%" height="116%" colorInterpolationFilters="sRGB">
                <feGaussianBlur stdDeviation="5" result="blurred" />
                <feComponentTransfer in="blurred">
                  <feFuncA type="linear" slope="1" />
                </feComponentTransfer>
              </filter>
            </defs>

            {/* 1. Fundo escuro */}
            <rect width={VIEWBOX.w} height={VIEWBOX.h} fill="#0F172A" />

            {/* 2. Grade térmica IDW — opacidade por freshness_ratio; blur suaviza transições */}
            {layers.heatmap && (
              <g clipPath="url(#floor-clip)" filter="url(#thermal-blur)">
                {thermalGrid.map((cell, i) => (
                  <rect key={i} x={cell.x} y={cell.y}
                    width={GRID_CELL + 1} height={GRID_CELL + 1}
                    fill={cell.color} opacity={cell.opacity * 0.90} />
                ))}
              </g>
            )}

            {/* 3. Planta por cima do calor */}
            {layers.plant && floorPlanUrl && (
              <image href={floorPlanUrl}
                x={floorConfig.imageX} y={floorConfig.imageY}
                width={floorConfig.imageW} height={floorConfig.imageH}
                preserveAspectRatio="none"
                opacity={0.58}
              />
            )}

            {/* 4. Zonas legadas — custom zones são desenhadas pelo ZoneEditor */}
            {layers.zones && legacyRectZones.map(zone => {
              const meta = STATUS_META[zone.status]
              const isSelected = zone.key === selectedZoneKey
              return (
                <g key={zone.key}
                  onClick={() => { setSelectedZoneKey(zone.key); setActionMessage('') }}
                  style={{ cursor: 'pointer' }}>
                  {/* Borda colorida da zona */}
                  <rect x={zone.x} y={zone.y} width={zone.w} height={zone.h}
                    fill={isSelected ? `${meta.color}22` : 'transparent'}
                    stroke={isSelected ? meta.color : `${meta.color}88`}
                    strokeWidth={isSelected ? 2 : 1}
                    strokeDasharray={zone.zone_type === 'SALA_FECHADA' ? '4 2' : undefined}
                    rx={3}
                    pointerEvents="all" />
                  {/* Label da zona */}
                  <text
                    x={zone.x + zone.w / 2} y={zone.y + 12}
                    textAnchor="middle" fontSize={9} fontWeight="600"
                    fill={meta.color} opacity={0.9}
                    style={{ pointerEvents: 'none', userSelect: 'none' }}>
                    {zone.label}
                  </text>
                  {zone.avgTemp != null && (
                    <text
                      x={zone.x + zone.w / 2} y={zone.y + 23}
                      textAnchor="middle" fontSize={10} fontWeight="700"
                      fill="#F1F5F9" opacity={0.85}
                      style={{ pointerEvents: 'none', userSelect: 'none' }}>
                      {formatTemp(zone.avgTemp)}
                    </text>
                  )}
                  <title>{zone.label} — {zone.avgTemp != null ? formatTemp(zone.avgTemp) : 'Sem leitura'} — {meta.label}</title>
                </g>
              )
            })}

            {/* 5. Mensagem quando sem leituras */}
            {heatPoints.length === 0 && floorPlanUrl && (
              <g pointerEvents="none">
                <rect width={VIEWBOX.w} height={VIEWBOX.h} fill="rgba(15,23,42,0.55)" />
                <text x={VIEWBOX.w / 2} y={VIEWBOX.h / 2} textAnchor="middle" fontSize={14} fontWeight={700} fill="#94A3B8">
                  Sem leituras para gerar o campo térmico
                </text>
              </g>
            )}

            {/* 6. Ícones (ACs e sensores) */}
            {layers.devices && positionedDevices.map((d: Device) => (
              <DeviceMarker key={d.id} device={d} onClick={() => undefined} scale={0.78} />
            ))}

            {/* 7. Labels de temperatura */}
            <g pointerEvents="none">
              {heatPoints
                .filter(p => p.sourceType !== 'zone' && p.temp != null
                  && (p.sourceType === 'sensor' ? layers.sensors : layers.devices))
                .map(point => {
                  const label = `${point.temp!.toFixed(1)}°`
                  const tw = label.length * 5.8 + 10
                  const tx = point.x - tw / 2
                  const ty = point.y - 18
                  const dot = point.sourceType === 'sensor' ? '#F59E0B' : point.sourceType === 'merged' ? '#A78BFA' : '#60A5FA'
                  return (
                    <g key={`lbl-${point.key}`} transform={`translate(${tx},${ty})`}>
                      <rect width={tw} height={16} rx={4} fill="rgba(15,23,42,0.82)" />
                      <circle cx={6} cy={8} r={2.5} fill={dot} />
                      <text x={tw / 2 + 2} y={11.5} textAnchor="middle" fontSize={9} fontWeight="600" fill="#F1F5F9" fontFamily="ui-monospace,monospace">
                        {label}
                      </text>
                    </g>
                  )
                })}
            </g>

            {/* 8. Áreas de hit para tooltip */}
            {heatPoints
              .filter(p => p.sourceType !== 'zone'
                && (p.sourceType === 'sensor' ? layers.sensors : layers.devices))
              .map(point => (
                <circle
                  key={`hit-${point.key}`}
                  cx={point.x} cy={point.y} r={32}
                  fill="transparent"
                  style={{ cursor: 'crosshair' }}
                  onMouseEnter={() => setHoveredPoint(point)}
                  onMouseLeave={() => setHoveredPoint(null)}
                />
              ))}

            {/* 9. Tooltip SVG */}
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

            {/* 10. Zonas customizadas + editor */}
            {storeId && (
              <ZoneEditor
                storeId={storeId}
                floor={selectedFloor}
                editMode={editMode}
                svgRef={svgRef}
                viewbox={VIEWBOX}
                transform={transform}
                onZoneClick={key => { setSelectedZoneKey(key); setActionMessage('') }}
              />
            )}
          </svg>
        </div>

        {/* Painel lateral */}
        <aside className="overflow-y-auto rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900 space-y-4">
          <ZoneAlertsSummary
            zones={zoneStates}
            selectedZoneKey={selectedZoneKey}
            onZoneSelect={(key) => { setSelectedZoneKey(key); setActionMessage('') }}
            onRefetch={() => { refetchDevices(); refetchZones() }}
          />
          {selectedZone ? (
            <>
              <ZonePanel
                key={selectedZone.key}
                zone={selectedZone}
                storeId={storeId!}
                automation={zoneAutomation}
                actionMessage={actionMessage}
                onModeChange={handleModeChange}
                onTrigger={handleTrigger}
                onRefetch={() => { refetchDevices(); refetchZones() }}
              />
              <DigitalTwinPanel twin={activeTwin} />
            </>
          ) : (
            <div className="rounded-lg bg-gray-50 px-3 py-6 dark:bg-gray-950 text-center text-sm text-gray-500">
              Clique em uma zona no mapa para ver detalhes e automação
            </div>
          )}
        </aside>
      </div>

      {/* Legenda — escala divergente por zona */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
        <span className="font-medium text-gray-400">Desvio da faixa ideal:</span>
        <div className="flex items-center gap-1.5"><div className="h-2.5 w-6 rounded" style={{ background: '#1D4ED8' }} />≤ −3° Muito frio</div>
        <div className="flex items-center gap-1.5"><div className="h-2.5 w-6 rounded" style={{ background: '#93C5FD' }} />−1° Levem. frio</div>
        <div className="flex items-center gap-1.5"><div className="h-2.5 w-6 rounded" style={{ background: '#16A34A' }} />0° Confortável</div>
        <div className="flex items-center gap-1.5"><div className="h-2.5 w-6 rounded" style={{ background: '#FACC15' }} />+1° Aquecendo</div>
        <div className="flex items-center gap-1.5"><div className="h-2.5 w-6 rounded" style={{ background: '#FB923C' }} />+2° Quente</div>
        <div className="flex items-center gap-1.5"><div className="h-2.5 w-6 rounded" style={{ background: '#DC2626' }} />≥ +3° Crítico</div>
        <span className="ml-auto text-gray-400">IDW {GRID_CELL}px/célula · desvio relativo à zona</span>
      </div>
    </div>
  )
}

/* ── Componentes auxiliares ── */

const ALERT_SEVERITY: ThermalStatus[] = ['CRITICAL', 'HOT', 'WARM', 'COLD']

function ZoneAlertsSummary({
  zones, selectedZoneKey, onZoneSelect, onRefetch,
}: {
  zones: ZoneState[]
  selectedZoneKey: string | null
  onZoneSelect: (key: string) => void
  onRefetch: () => void
}) {
  const problematic = zones
    .filter(z => ALERT_SEVERITY.includes(z.status))
    .sort((a, b) => ALERT_SEVERITY.indexOf(a.status) - ALERT_SEVERITY.indexOf(b.status))

  if (!problematic.length) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-green-50 px-3 py-2.5 dark:bg-green-950/30">
        <span className="h-2 w-2 rounded-full bg-green-500 flex-shrink-0" />
        <span className="text-xs font-medium text-green-700 dark:text-green-400">Todas as zonas dentro da faixa confortável</span>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-orange-200 dark:border-orange-900/60 overflow-hidden">
      <div className="flex items-center gap-2 bg-orange-50 px-3 py-2 dark:bg-orange-950/30">
        <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 text-orange-500" />
        <span className="text-xs font-semibold text-orange-700 dark:text-orange-400">
          {problematic.length} zona{problematic.length !== 1 ? 's' : ''} precisam de atenção
        </span>
        <span className="ml-auto text-xs text-orange-400">clique para ajustar</span>
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {problematic.map(zone => (
          <ZoneAlertRow
            key={zone.key}
            zone={zone}
            isSelected={zone.key === selectedZoneKey}
            onSelect={() => onZoneSelect(zone.key)}
            onRefetch={onRefetch}
          />
        ))}
      </div>
    </div>
  )
}

type RowPhase = 'idle' | 'loading' | 'done' | 'error'

function ZoneAlertRow({
  zone, isSelected, onSelect, onRefetch,
}: {
  zone: ZoneState
  isSelected: boolean
  onSelect: () => void
  onRefetch: () => void
}) {
  const [phase, setPhase] = useState<RowPhase>('idle')
  const [lockedUntil, setLockedUntil] = useState(0)
  const isLocked = Date.now() < lockedUntil
  const meta = STATUS_META[zone.status]
  const action = recommendedControlAction(zone.status)
  const acDevices = zone.actionableDevices.filter((d: Device) => !d.is_external_sensor)
  const offAcDevices = zone.devices.filter((d: Device) => !d.is_external_sensor && d.status === 'DESLIGADO')
  const hotOffAcDevices = offAcDevices.filter((d: Device) => d.temperature != null && d.temperature > zone.idealMax)
  const powerOnTargets = hotOffAcDevices.length > 0 ? hotOffAcDevices : offAcDevices
  const shouldPowerOn = action === 'temperature_down' && powerOnTargets.length > 0 && (hotOffAcDevices.length > 0 || acDevices.length === 0)
  const canPowerOn = shouldPowerOn && !isLocked && phase !== 'loading'
  const canAdjust = action != null && acDevices.length > 0 && !isLocked && phase !== 'loading'

  const quickAdjust = async () => {
    if (!action || !canAdjust) return
    setPhase('loading')
    try {
      // Só ajusta ACs cuja temperatura individual confirma que estão fora da faixa
      const hot = acDevices.filter((d: Device) => {
        if (d.temperature == null) return false
        return action === 'temperature_down' ? d.temperature > zone.idealMax : d.temperature < zone.idealMin
      })
      const targets = (hot.length > 0 ? hot : acDevices.filter((d: Device) => d.temperature == null)).slice(0, 8)
      if (!targets.length) { setPhase('idle'); return }
      await Promise.all(targets.map((d: Device) => devicesApi.control(d.id, action, 1)))
      setPhase('done')
      setLockedUntil(Date.now() + 2 * 60 * 1000)
      onRefetch()
      setTimeout(() => setPhase('idle'), 8000)
    } catch {
      setPhase('error')
      setTimeout(() => setPhase('idle'), 4000)
    }
  }

  const quickPowerOn = async () => {
    if (!canPowerOn) return
    setPhase('loading')
    try {
      const targets = powerOnTargets.slice(0, 4)
      await Promise.all(targets.map((d: Device) => devicesApi.control(d.id, 'power_on', 1)))
      setPhase('done')
      setLockedUntil(Date.now() + 2 * 60 * 1000)
      onRefetch()
      setTimeout(() => setPhase('idle'), 8000)
    } catch {
      setPhase('error')
      setTimeout(() => setPhase('idle'), 4000)
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => e.key === 'Enter' && onSelect()}
      className={cn(
        'flex items-center gap-3 px-3 py-2.5 text-left transition-colors cursor-pointer',
        isSelected ? 'bg-blue-50 dark:bg-blue-950/30' : 'hover:bg-gray-50 dark:hover:bg-gray-800/50',
      )}
    >
      <span className="h-2.5 w-2.5 flex-shrink-0 rounded-full" style={{ background: meta.color }} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-gray-900 dark:text-white">{zone.label}</span>
          {isSelected && (
            <span className="flex-shrink-0 rounded bg-blue-100 px-1 py-0.5 text-[10px] text-blue-600 dark:bg-blue-900/50 dark:text-blue-400">
              ativo
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className={meta.text}>{meta.label}</span>
          {zone.avgTemp != null && <span className="text-gray-500">· {formatTemp(zone.avgTemp)}</span>}
          {acDevices.length > 0 && (
            <span className="text-gray-400">· {acDevices.length} AC{acDevices.length !== 1 ? 's' : ''}</span>
          )}
          {acDevices.length === 0 && offAcDevices.length > 0 && (
            <span className="text-blue-400">· {offAcDevices.length} desligado{offAcDevices.length !== 1 ? 's' : ''}</span>
          )}
        </div>
      </div>
      {action && (
        <button
          type="button"
          title={
            canPowerOn
              ? `Ligar ${powerOnTargets.length} AC(s) desligado(s) em ${zone.label}`
              : action === 'temperature_down'
              ? `Reduzir 1°C em ${acDevices.length} AC(s) de ${zone.label}`
              : `Aumentar 1°C em ${acDevices.length} AC(s) de ${zone.label}`
          }
          onClick={(e) => { e.stopPropagation(); canPowerOn ? void quickPowerOn() : void quickAdjust() }}
          disabled={!canAdjust && !canPowerOn}
          className={cn(
            'flex-shrink-0 inline-flex items-center justify-center rounded-md px-2.5 py-1 text-xs font-semibold transition-colors min-w-[52px]',
            phase === 'done'
              ? 'bg-green-100 text-green-700 dark:bg-green-950/50 dark:text-green-400'
              : phase === 'error'
              ? 'bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-400'
              : isLocked
              ? 'cursor-not-allowed bg-gray-100 text-gray-400 dark:bg-gray-800'
              : canPowerOn
              ? 'bg-blue-100 text-blue-700 hover:bg-blue-200 dark:bg-blue-950/50 dark:text-blue-400'
              : !canAdjust
              ? 'cursor-not-allowed bg-gray-100 text-gray-400 dark:bg-gray-800'
              : action === 'temperature_down'
              ? 'bg-orange-100 text-orange-700 hover:bg-orange-200 dark:bg-orange-950/50 dark:text-orange-400'
              : 'bg-blue-100 text-blue-700 hover:bg-blue-200 dark:bg-blue-950/50 dark:text-blue-400',
          )}
        >
          {phase === 'loading'
            ? <RefreshCw className="h-3 w-3 animate-spin" />
            : phase === 'done'
            ? '✓ OK'
            : phase === 'error'
            ? '✗ Erro'
            : isLocked
            ? 'esperar'
            : canPowerOn
            ? '⏻ Ligar'
            : acDevices.length === 0
            ? 'sem AC'
            : action === 'temperature_down'
            ? '↓ 1°C'
            : '↑ 1°C'
          }
        </button>
      )}
    </div>
  )
}

const ZONE_MODES: { key: ZoneMode; label: string; description: string; adminOnly?: boolean }[] = [
  { key: 'manual',      label: 'Manual',      description: 'Sem automação — só sugestões visuais.' },
  { key: 'suggestion',  label: 'Sugestão',    description: 'Registra sugestões, aguarda aprovação.' },
  { key: 'semi',        label: 'Semi-auto',   description: 'Executa 1 ajuste/ciclo com verificação.' },
  { key: 'auto',        label: 'Automático',  description: 'Avalia e executa automaticamente.', adminOnly: true },
  { key: 'maintenance', label: 'Manutenção',  description: 'Bloqueia toda automação até liberação explícita.', adminOnly: true },
]

const ZONE_PRIORITIES: { key: ZonePriority; label: string; description: string }[] = [
  { key: 'conforto',     label: 'Conforto',   description: 'Conforto térmico com proteção contra desperdício.' },
  { key: 'estabilidade', label: 'Balanceado', description: 'Equilibra conforto, consumo e poucos comandos.' },
  { key: 'economia',     label: 'Econômico',  description: 'Opera perto do limite superior da faixa ideal.' },
  { key: 'critico',      label: 'Crítico',    description: 'Resposta rápida para área sensível, ainda em passos seguros.' },
]

const ACTION_STATUS_META: Record<string, { label: string; color: string }> = {
  suggestion:           { label: 'Sugestão',          color: 'text-blue-500' },
  pending_verification: { label: 'Verificando…',      color: 'text-yellow-500' },
  executed:             { label: 'Executado',          color: 'text-green-500' },
  blocked:              { label: 'Bloqueado',          color: 'text-gray-500' },
  verified_success:     { label: 'Eficaz ✓',          color: 'text-green-600' },
  verified_failure:     { label: 'Sem efeito ✗',      color: 'text-red-500' },
}

type ManualPhase = 'idle' | 'confirming' | 'sending' | 'done' | 'error'

function ZonePanel({
  zone, storeId, automation, actionMessage, onModeChange, onTrigger, onRefetch,
}: {
  zone: any
  storeId: string
  automation: ZoneAutomationState | undefined
  actionMessage: string
  onModeChange: (mode: ZoneMode) => Promise<void>
  onTrigger: () => Promise<void>
  onRefetch: () => void
}) {
  const [changingMode, setChangingMode] = useState(false)
  const [changingPriority, setChangingPriority] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [manualPhase, setManualPhase] = useState<ManualPhase>('idle')
  const [manualLockedUntil, setManualLockedUntil] = useState(0)
  const [manualResult, setManualResult] = useState<{ kind: 'setpoint' | 'power_on'; targetSp?: number; count: number } | null>(null)
  const [manualError, setManualError] = useState<string | null>(null)
  const [maintenanceReason, setMaintenanceReason] = useState('')
  const [maintenanceUntil, setMaintenanceUntil] = useState('')
  const [showMaintenanceForm, setShowMaintenanceForm] = useState(false)

  const { role } = useAuthStore()
  const isAdmin  = role === 'ADMIN'
  const isEditor = role === 'EDITOR' || isAdmin
  const canWrite = isEditor  // VIEWER não pode escrever nada

  const meta = STATUS_META[zone.status as ThermalStatus]

  const acDevices: Device[] = zone.actionableDevices.filter((d: Device) => !d.is_external_sensor)
  const offAcDevices: Device[] = zone.devices.filter((d: Device) => !d.is_external_sensor && d.status === 'DESLIGADO')
  const hotOffAcDevices: Device[] = offAcDevices.filter((d: Device) => d.temperature != null && d.temperature > zone.idealMax)
  const powerOnTargets: Device[] = hotOffAcDevices.length > 0 ? hotOffAcDevices : offAcDevices
  // Prefere dispositivo com setpoint disponível + maior delta; se nenhum tem setpoint, usa o de maior delta mesmo
  const bestDevice: Device | null =
    ([...acDevices].filter(d => d.setpoint_cool != null)
      .sort((a, b) => Math.abs(b.delta_temp ?? 0) - Math.abs(a.delta_temp ?? 0))[0])
    ?? ([...acDevices].sort((a, b) => Math.abs(b.delta_temp ?? 0) - Math.abs(a.delta_temp ?? 0))[0])
    ?? null

  const currentSpRaw: number | null = bestDevice?.current_setpoint ?? bestDevice?.setpoint_cool ?? null
  const setpointStale = !!bestDevice?.setpoint_stale
  const currentSp: number | null = setpointStale ? null : currentSpRaw
  const minAllowedSp = bestDevice?.min_allowed_setpoint ?? 18
  const maxAllowedSp = bestDevice?.max_allowed_setpoint ?? 28
  const ctrlAction = recommendedControlAction(zone.status)

  const targetSp: number | null =
    ctrlAction === 'temperature_down' && currentSp != null ? Math.max(minAllowedSp, currentSp - 1)
    : ctrlAction === 'temperature_up' && currentSp != null ? Math.min(maxAllowedSp, currentSp + 1)
    : null

  // Quando setpoint desconhecido/stale, ainda envia o comando direcional; o backend revalida na Brise.
  const actualAction: 'temperature_up' | 'temperature_down' | null =
    targetSp != null && currentSp != null && targetSp !== currentSp
      ? targetSp > currentSp ? 'temperature_up' : 'temperature_down'
      : ctrlAction ?? null

  const step = targetSp != null && currentSp != null ? Math.abs(targetSp - currentSp) : 1
  const atLimit = currentSp != null && targetSp === currentSp
  const isLocked = Date.now() < manualLockedUntil
  const shouldPowerOn = ctrlAction === 'temperature_down' && powerOnTargets.length > 0 && (hotOffAcDevices.length > 0 || acDevices.length === 0)
  const canShowPowerOn = canWrite && shouldPowerOn && !isLocked
  const canShowManual = acDevices.length > 0 && !!ctrlAction && !isLocked && !shouldPowerOn

  // Só ajusta ACs cuja temperatura individual está realmente fora da faixa
  const needsAdjust = (d: Device) => {
    if (d.temperature == null) return false
    return ctrlAction === 'temperature_down' ? d.temperature > zone.idealMax : d.temperature < zone.idealMin
  }
  const hotDevices = ctrlAction ? acDevices.filter(needsAdjust) : []
  // Fallback: sem leitura de temperatura → inclui para não ignorar cegamente
  const adjustTargets = hotDevices.length > 0
    ? hotDevices
    : acDevices.filter(d => d.temperature == null)
  const allAlreadyOk = adjustTargets.length === 0 && acDevices.length > 0

  const confirmApply = async () => {
    const action = actualAction ?? ctrlAction
    if (!action || allAlreadyOk) return
    setManualPhase('sending')
    setManualError(null)
    try {
      const targets = adjustTargets.slice(0, 8)
      await Promise.all(targets.map(d => devicesApi.control(d.id, action, step)))
      setManualResult({ kind: 'setpoint', targetSp: targetSp ?? (currentSp ?? 0) + (action === 'temperature_up' ? 1 : -1), count: targets.length })
      setManualPhase('done')
      setManualLockedUntil(Date.now() + 2 * 60 * 1000)
      onRefetch()
    } catch {
      setManualError('Falha ao enviar o comando para a Brise API.')
      setManualPhase('error')
    }
  }

  const handlePowerOnManual = async () => {
    if (!canShowPowerOn) return
    setManualPhase('sending')
    setManualError(null)
    try {
      const targets = powerOnTargets.slice(0, 4)
      await Promise.all(targets.map(d => devicesApi.control(d.id, 'power_on', 1)))
      setManualResult({ kind: 'power_on', count: targets.length })
      setManualPhase('done')
      setManualLockedUntil(Date.now() + 2 * 60 * 1000)
      onRefetch()
    } catch {
      setManualError('Falha ao ligar o aparelho pela Brise API.')
      setManualPhase('error')
    }
  }

  const currentMode: ZoneMode = automation?.mode ?? 'manual'
  const currentPriority: ZonePriority = automation?.priority ?? 'conforto'
  const lastAction = automation?.last_action ?? null
  const cooldownS = automation?.cooldown_remaining_s ?? null
  const consecFail = automation?.consecutive_failures ?? 0
  const isInMaintenance = currentMode === 'maintenance'

  const onDevices = zone.devices.filter((d: Device) => !d.is_external_sensor && d.state === true)
  const estimatedKw = onDevices.reduce((sum: number, d: Device) => {
    const fromTelemetry = d.consumption_estimated_kw ?? null
    if (fromTelemetry != null) return sum + fromTelemetry
    return sum + Math.max(0.5, ((d.btu || 12000) / 12000) * 1.1)
  }, 0)
  const lowSetpointCount = onDevices.filter((d: Device) => {
    const sp = d.current_setpoint ?? d.setpoint_cool
    return sp != null && sp < Math.ceil(zone.idealMin)
  }).length
  const comfortable = zone.status === 'COMFORT'
  const economyOpportunity =
    comfortable && (estimatedKw >= 4 || lowSetpointCount > 0 || (onDevices.length >= 3 && zone.avgTemp != null && zone.avgTemp <= zone.idealMin + 0.4))

  const handleMode = async (mode: ZoneMode) => {
    if (!canWrite) return
    if (mode === 'maintenance') {
      setShowMaintenanceForm(true)
      return
    }
    setChangingMode(true)
    await onModeChange(mode).finally(() => setChangingMode(false))
  }

  const handlePriority = async (priority: ZonePriority) => {
    if (!canWrite) return
    setChangingPriority(true)
    await zonesApi.setMode(storeId, zone.key, { mode: currentMode, priority }).finally(() => {
      setChangingPriority(false)
      onRefetch()
    })
  }

  const handleMaintenanceConfirm = async () => {
    if (!maintenanceReason.trim()) return
    setChangingMode(true)
    setShowMaintenanceForm(false)
    await zonesApi.setMode(storeId, zone.key, {
      mode: 'maintenance',
      blocked_reason: maintenanceReason.trim(),
      blocked_until: maintenanceUntil || null,
    }).finally(() => {
      setChangingMode(false)
      setMaintenanceReason('')
      setMaintenanceUntil('')
      onRefetch()
    })
  }

  const handleTrigger = async () => {
    setTriggering(true)
    await onTrigger().finally(() => setTriggering(false))
  }

  return (
    <div className="space-y-4">
      {/* Cabeçalho da zona */}
      <div>
        <div className={cn('text-xs font-semibold uppercase', meta.text)}>{meta.label}</div>
        <h2 className="mt-1 text-lg font-semibold text-gray-900 dark:text-white">{zone.label}</h2>
        <p className="text-xs text-gray-500">Faixa ideal: {zone.idealMin}°C a {zone.idealMax}°C</p>
      </div>

      {/* Métricas */}
      <div className="grid grid-cols-2 gap-3">
        <PanelMetric label="Temperatura" value={zone.avgTemp != null ? formatTemp(zone.avgTemp) : '—'} />
        <PanelMetric label="Ligados" value={onDevices.length} />
        <PanelMetric label="Potência est." value={`${estimatedKw.toFixed(1)} kW`} />
        <PanelMetric label="Setpoints baixos" value={lowSetpointCount} />
      </div>

      <div className={cn(
        'rounded-lg border p-3',
        economyOpportunity
          ? 'border-amber-200 bg-amber-50 dark:border-amber-900/70 dark:bg-amber-950/20'
          : 'border-emerald-200 bg-emerald-50 dark:border-emerald-900/70 dark:bg-emerald-950/20',
      )}>
        <div className="flex items-start gap-2">
          <Zap className={cn('mt-0.5 h-4 w-4', economyOpportunity ? 'text-amber-500' : 'text-emerald-500')} />
          <div className="min-w-0">
            <div className={cn('text-xs font-semibold uppercase', economyOpportunity ? 'text-amber-700 dark:text-amber-300' : 'text-emerald-700 dark:text-emerald-300')}>
              {economyOpportunity ? 'Oportunidade de economia' : 'Consumo compatível'}
            </div>
            <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
              {economyOpportunity
                ? 'Zona confortável com consumo ou setpoint abaixo do necessário. A automação deve preferir elevar 1°C ou reduzir redundância.'
                : 'Sem indicação de ação extra: mantém conforto evitando ligar ou reduzir setpoint sem necessidade.'}
            </p>
          </div>
        </div>
      </div>

      {/* ── Automação Inteligente ── */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
        <div className="flex items-center gap-2 bg-gray-50 px-3 py-2 dark:bg-gray-950">
          <Bot className="h-3.5 w-3.5 text-purple-500" />
          <span className="text-xs font-semibold uppercase text-gray-600 dark:text-gray-400">Automação Inteligente</span>
        </div>

        <div className="p-3 space-y-3">
          {/* Seletor de modo */}
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs text-gray-500">Modo de operação</span>
              {!canWrite && (
                <span className="flex items-center gap-1 text-xs text-gray-400">
                  <Lock className="h-3 w-3" /> Somente leitura
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-1">
              {ZONE_MODES.filter(m => !m.adminOnly || isAdmin).map(m => {
                const isActive = currentMode === m.key
                const isDisabled = changingMode || !canWrite
                const tooltipText = !canWrite
                  ? 'Sem permissão para alterar modos'
                  : m.description
                return (
                  <button
                    key={m.key}
                    type="button"
                    disabled={isDisabled}
                    onClick={() => handleMode(m.key)}
                    title={tooltipText}
                    className={cn(
                      'rounded-md px-2 py-1.5 text-xs font-medium transition-colors text-center',
                      isActive
                        ? m.key === 'maintenance'
                          ? 'bg-orange-500 text-white'
                          : 'bg-purple-600 text-white'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700',
                      isDisabled && 'opacity-40 cursor-not-allowed',
                    )}
                  >
                    {m.key === 'maintenance' && <Wrench className="mr-1 inline h-3 w-3" />}
                    {m.label}
                  </button>
                )
              })}
            </div>
            {ZONE_MODES.find(m => m.key === currentMode) && (
              <p className="mt-1 text-xs text-gray-400">{ZONE_MODES.find(m => m.key === currentMode)!.description}</p>
            )}
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs text-gray-500">Estratégia energética</span>
              {changingPriority && <RefreshCw className="h-3 w-3 animate-spin text-gray-400" />}
            </div>
            <div className="grid grid-cols-2 gap-1">
              {ZONE_PRIORITIES.map(p => {
                const isActive = currentPriority === p.key
                const isDisabled = changingPriority || !canWrite
                return (
                  <button
                    key={p.key}
                    type="button"
                    disabled={isDisabled}
                    title={p.description}
                    onClick={() => handlePriority(p.key)}
                    className={cn(
                      'rounded-md px-2 py-1.5 text-xs font-medium transition-colors text-center',
                      isActive
                        ? 'bg-emerald-600 text-white'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700',
                      isDisabled && 'opacity-40 cursor-not-allowed',
                    )}
                  >
                    {p.label}
                  </button>
                )
              })}
            </div>
            <p className="mt-1 text-xs text-gray-400">
              {ZONE_PRIORITIES.find(p => p.key === currentPriority)?.description}
            </p>
          </div>

          {/* Banner de manutenção */}
          {isInMaintenance && automation && (
            <div className="rounded-lg border border-orange-300 bg-orange-50 p-2.5 dark:border-orange-800 dark:bg-orange-950/30">
              <div className="flex items-start gap-2">
                <Wrench className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-orange-500" />
                <div className="min-w-0 flex-1 space-y-0.5">
                  <p className="text-xs font-semibold text-orange-700 dark:text-orange-300">Zona em manutenção</p>
                  {automation.blocked_reason && (
                    <p className="text-xs text-orange-600 dark:text-orange-400">{automation.blocked_reason}</p>
                  )}
                  {automation.blocked_by_user_name && (
                    <p className="text-xs text-orange-500 dark:text-orange-500">Por: {automation.blocked_by_user_name}</p>
                  )}
                  {automation.blocked_until && (
                    <p className="text-xs text-orange-500 dark:text-orange-500">
                      Até: {formatDateTime(automation.blocked_until)}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Formulário de manutenção */}
          {showMaintenanceForm && (
            <div className="rounded-lg border border-orange-300 bg-orange-50 p-3 dark:border-orange-800 dark:bg-orange-950/30 space-y-2">
              <p className="text-xs font-semibold text-orange-700 dark:text-orange-300 flex items-center gap-1.5">
                <Wrench className="h-3.5 w-3.5" /> Bloquear zona para manutenção
              </p>
              <div className="space-y-1.5">
                <input
                  type="text"
                  placeholder="Motivo (obrigatório)"
                  value={maintenanceReason}
                  onChange={e => setMaintenanceReason(e.target.value)}
                  className="w-full rounded-md border border-orange-300 bg-white px-2 py-1.5 text-xs text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-orange-400 dark:border-orange-700 dark:bg-gray-900 dark:text-gray-200"
                />
                <input
                  type="datetime-local"
                  value={maintenanceUntil}
                  onChange={e => setMaintenanceUntil(e.target.value)}
                  className="w-full rounded-md border border-orange-300 bg-white px-2 py-1.5 text-xs text-gray-800 focus:outline-none focus:ring-1 focus:ring-orange-400 dark:border-orange-700 dark:bg-gray-900 dark:text-gray-200"
                  title="Liberação automática (opcional)"
                />
                <p className="text-xs text-orange-500">Liberação automática — deixe em branco para manutenção indefinida.</p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={!maintenanceReason.trim() || changingMode}
                  onClick={handleMaintenanceConfirm}
                  className="flex-1 rounded-md bg-orange-500 px-2 py-1.5 text-xs font-medium text-white hover:bg-orange-400 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Confirmar bloqueio
                </button>
                <button
                  type="button"
                  onClick={() => { setShowMaintenanceForm(false); setMaintenanceReason(''); setMaintenanceUntil('') }}
                  className="rounded-md bg-gray-200 px-2 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-300 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
                >
                  Cancelar
                </button>
              </div>
            </div>
          )}

          {/* Guardrails */}
          {automation && (
            <GuardrailsPanel
              automation={automation}
              storeId={storeId}
              zoneKey={zone.key}
              onUpdated={onRefetch}
            />
          )}

          {/* Stats */}
          <div className="grid grid-cols-3 gap-2">
            <div className="rounded bg-gray-50 dark:bg-gray-950 p-2 text-center">
              <div className="text-xs text-gray-500">Ações hoje</div>
              <div className="text-sm font-semibold text-gray-900 dark:text-white">
                {automation?.daily_count ?? 0}
              </div>
            </div>
            <div className="rounded bg-gray-50 dark:bg-gray-950 p-2 text-center">
              <div className="text-xs text-gray-500">Falhas</div>
              <div className={cn('text-sm font-semibold', consecFail >= 3 ? 'text-red-500' : 'text-gray-900 dark:text-white')}>
                {consecFail}
              </div>
            </div>
            <div className="rounded bg-gray-50 dark:bg-gray-950 p-2 text-center">
              <div className="text-xs text-gray-500">Cooldown</div>
              <div className={cn('text-sm font-semibold', cooldownS ? 'text-amber-500' : 'text-green-500')}>
                {cooldownS ? `${Math.ceil(cooldownS / 60)}m` : 'Livre'}
              </div>
            </div>
          </div>

          {/* Última ação */}
          {lastAction && (() => {
            const aMeta = ACTION_STATUS_META[lastAction.status] ?? { label: lastAction.status, color: 'text-gray-500' }
            return (
              <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-2.5 space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">Última ação</span>
                  <span className={cn('text-xs font-semibold', aMeta.color)}>{aMeta.label}</span>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400">
                  {lastAction.direction === 'down'
                    ? <ChevronDown className="h-3 w-3 text-orange-500" />
                    : <ChevronUp className="h-3 w-3 text-blue-500" />
                  }
                  <span>
                    {lastAction.device_name ?? '—'}
                    {lastAction.setpoint_before != null && lastAction.setpoint_after != null
                      && lastAction.setpoint_before !== lastAction.setpoint_after && (
                      <> · {lastAction.setpoint_before}°→{lastAction.setpoint_after}°C</>
                    )}
                    {lastAction.setpoint_before != null
                      && lastAction.setpoint_before === lastAction.setpoint_after
                      && lastAction.direction === 'down' && (
                      <> · ⏻ Ligou</>
                    )}
                  </span>
                </div>
                {lastAction.temp_before != null && (
                  <div className="text-xs text-gray-500">
                    {lastAction.temp_before.toFixed(1)}°C antes
                    {lastAction.temp_after != null && <> → {lastAction.temp_after.toFixed(1)}°C depois</>}
                    {lastAction.confidence != null && <> · conf. {Math.round(lastAction.confidence * 100)}%</>}
                  </div>
                )}
                {lastAction.block_reason && (
                  <div className="text-xs text-red-400 italic">{lastAction.block_reason}</div>
                )}
                <div className="flex items-center gap-1 text-xs text-gray-400">
                  <Clock className="h-3 w-3" />
                  {formatRelativeTime(lastAction.created_at)}
                </div>
              </div>
            )
          })()}

          {/* Disparar avaliação */}
          {currentMode !== 'manual' && (
            <button
              type="button"
              disabled={triggering || !!cooldownS}
              onClick={handleTrigger}
              className={cn(
                'inline-flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors',
                cooldownS
                  ? 'cursor-not-allowed bg-gray-100 text-gray-400 dark:bg-gray-800'
                  : 'bg-purple-600 text-white hover:bg-purple-500 disabled:opacity-60',
              )}
            >
              {triggering
                ? <><RefreshCw className="h-3.5 w-3.5 animate-spin" /> Avaliando…</>
                : cooldownS
                ? <><Clock className="h-3.5 w-3.5" /> Em cooldown ({Math.ceil(cooldownS / 60)}min)</>
                : <><PlayCircle className="h-3.5 w-3.5" /> Reavaliar agora</>
              }
            </button>
          )}
        </div>
      </div>

      {/* Ajuste manual rápido */}
      <div className="rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
        <div className="flex items-center gap-2 bg-gray-50 px-3 py-2 dark:bg-gray-950">
          <Zap className="h-3.5 w-3.5 text-blue-500" />
          <span className="text-xs font-semibold uppercase text-gray-600 dark:text-gray-400">Ajuste manual</span>
        </div>

        <div className="p-3">
          {!canShowManual && !canWrite && (
            <p className="text-sm text-gray-500">Somente leitura — sem permissão para ajustar.</p>
          )}

          {/* ACs desligados — zona precisa resfriar */}
          {!canShowManual && canShowPowerOn && (
            <div className="space-y-2">
              <p className="text-xs text-blue-600 dark:text-blue-400">
                {hotOffAcDevices.length > 0
                  ? `${hotOffAcDevices.length} AC${hotOffAcDevices.length !== 1 ? 's' : ''} desligado${hotOffAcDevices.length !== 1 ? 's' : ''} no ponto quente. Ligue para resfriar esse canto.`
                  : `${powerOnTargets.length} AC${powerOnTargets.length !== 1 ? 's' : ''} desligado${powerOnTargets.length !== 1 ? 's' : ''} nesta zona. Ligue para iniciar o resfriamento.`}
              </p>
              <div className="space-y-1.5">
                {powerOnTargets.slice(0, 4).map(d => (
                  <div key={d.id} className="flex items-center gap-2 text-xs text-gray-500">
                    <span className="h-1.5 w-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                    <span className="truncate">{d.name}</span>
                    {d.temperature != null && <span className="ml-auto">{formatTemp(d.temperature)}</span>}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={handlePowerOnManual}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500"
                >
                  <Wind className="h-4 w-4" />
                  Ligar {powerOnTargets.length} AC{powerOnTargets.length !== 1 ? 's' : ''}
                </button>
              </div>
            </div>
          )}

          {!canShowManual && canWrite && !canShowPowerOn && (
            <p className="text-sm text-gray-500">
              {isLocked
                ? 'Aguarde antes de reaplicar (cooldown de 2 min).'
                : acDevices.length === 0 && offAcDevices.length > 0
                ? `${offAcDevices.length} AC${offAcDevices.length !== 1 ? 's' : ''} desligado${offAcDevices.length !== 1 ? 's' : ''} — zona dentro da faixa, nenhum ajuste necessário.`
                : acDevices.length === 0
                ? 'Nenhum aparelho com leitura ativa nesta zona.'
                : 'Zona dentro da faixa confortável — nenhum ajuste necessário.'}
            </p>
          )}

          {canShowManual && manualPhase === 'idle' && bestDevice && (
            <div className="space-y-3">
              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <Wind className="h-3.5 w-3.5 flex-shrink-0 text-blue-500" />
                  <span className="truncate text-sm font-medium text-gray-900 dark:text-white">{bestDevice.name}</span>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-gray-500">
                  <span>{bestDevice.sector_name ?? zone.label}</span>
                  {bestDevice.temperature != null && <span>Ambiente: {formatTemp(bestDevice.temperature)}</span>}
                  {currentSp != null && <span>Setpoint atual real: <strong className="text-gray-700 dark:text-gray-300">{currentSp}°C</strong></span>}
                  {currentSp == null && currentSpRaw != null && <span className="text-amber-600 dark:text-amber-400">Setpoint desatualizado: {currentSpRaw}°C</span>}
                  {currentSp == null && currentSpRaw == null && <span className="text-amber-600 dark:text-amber-400">Sem leitura de setpoint</span>}
                  <span>Limite operacional: {minAllowedSp}–{maxAllowedSp}°C</span>
                  <span className="font-mono text-gray-400">{bestDevice.brise_id}</span>
                </div>
                <p className="text-xs text-gray-600 dark:text-gray-400">
                  {allAlreadyOk
                    ? `Todos os ${acDevices.length} ACs já estão dentro da faixa (${zone.idealMin}–${zone.idealMax}°C). Nenhum ajuste necessário.`
                    : atLimit
                    ? `Setpoint real já no limite operacional (${currentSp}°C = ${ctrlAction === 'temperature_down' ? 'mín' : 'máx'}. ${ctrlAction === 'temperature_down' ? minAllowedSp : maxAllowedSp}°C).`
                    : currentSp == null
                    ? ctrlAction === 'temperature_down'
                      ? `Zona aquecida — será enviado comando de redução. Setpoint real indisponível ou desatualizado; backend revalidará na Brise. Faixa ideal: ${zone.idealMin}–${zone.idealMax}°C.`
                      : `Zona fria — será enviado comando de aumento. Setpoint real indisponível ou desatualizado; backend revalidará na Brise. Faixa ideal: ${zone.idealMin}–${zone.idealMax}°C.`
                    : ctrlAction === 'temperature_down'
                    ? `Zona aquecida — setpoint real ${currentSp}°C, reduzir para ${targetSp}°C. Faixa ideal da zona: ${zone.idealMin}–${zone.idealMax}°C.`
                    : `Zona fria — setpoint real ${currentSp}°C, aumentar para ${targetSp}°C. Faixa ideal da zona: ${zone.idealMin}–${zone.idealMax}°C.`
                  }
                  {!allAlreadyOk && adjustTargets.length > 0 && adjustTargets.length < acDevices.length && (
                    <> <span className="font-medium text-orange-600 dark:text-orange-400">
                      Somente {adjustTargets.length} de {acDevices.length} ACs fora da faixa serão ajustados.
                    </span></>
                  )}
                  {!allAlreadyOk && adjustTargets.length > 1 && adjustTargets.length === acDevices.length && ` Aplicar em ${adjustTargets.length} aparelhos.`}
                </p>
              </div>
              <button
                type="button"
                disabled={atLimit || allAlreadyOk}
                onClick={() => setManualPhase('confirming')}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-gray-200 disabled:text-gray-400 dark:disabled:bg-gray-800 dark:disabled:text-gray-600"
              >
                <Zap className="h-4 w-4" />
                {allAlreadyOk
                  ? 'Todos já confortáveis'
                  : atLimit
                  ? `Setpoint no limite operacional (${currentSp}°C)`
                  : targetSp != null
                  ? `Ajustar para ${targetSp}°C${adjustTargets.length > 1 ? ` (${adjustTargets.length} ACs)` : ''}`
                  : ctrlAction === 'temperature_down'
                  ? `Reduzir setpoint${adjustTargets.length > 1 ? ` (${adjustTargets.length} ACs)` : ''}`
                  : `Aumentar setpoint${adjustTargets.length > 1 ? ` (${adjustTargets.length} ACs)` : ''}`
                }
              </button>
            </div>
          )}

          {canShowManual && manualPhase === 'confirming' && (
            <div className="space-y-3">
              <div className="rounded-lg bg-blue-50 p-3 dark:bg-blue-950/30 space-y-1.5">
                <p className="text-xs font-semibold text-blue-700 dark:text-blue-400">Confirmar envio de comando</p>
                <div className="space-y-0.5 text-xs text-blue-900 dark:text-blue-300">
                  <div className="flex items-center gap-1.5">
                    <Wind className="h-3 w-3" />
                    <span className="font-medium">{bestDevice?.name}</span>
                    <span className="text-blue-500">({bestDevice?.brise_id})</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span>Setor: {bestDevice?.sector_name ?? zone.label}</span>
                  </div>
                  {currentSp != null && targetSp != null && (
                    <div className="flex items-center gap-2 font-mono">
                      <span>Setpoint:</span>
                      <span className="text-gray-500">{currentSp}°C</span>
                      <span>→</span>
                      <span className="font-bold text-blue-700 dark:text-blue-300">{targetSp}°C</span>
                    </div>
                  )}
                  <div className="text-blue-600 dark:text-blue-400">
                    Faixa ideal: {zone.idealMin}–{zone.idealMax}°C · limite operacional: {minAllowedSp}–{maxAllowedSp}°C
                    {adjustTargets.length > 1 && ` · ${adjustTargets.length} aparelho${adjustTargets.length !== 1 ? 's' : ''} fora da faixa`}
                  </div>
                  {adjustTargets.length < acDevices.length && adjustTargets.length > 0 && (
                    <div className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-700 dark:bg-amber-950/30 dark:text-amber-400">
                      {acDevices.length - adjustTargets.length} AC{acDevices.length - adjustTargets.length !== 1 ? 's' : ''} já confortável{acDevices.length - adjustTargets.length !== 1 ? 'is' : ''} — não serão tocados.
                    </div>
                  )}
                </div>
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={() => setManualPhase('idle')}
                  className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-800">
                  Cancelar
                </button>
                <button type="button" onClick={confirmApply}
                  className="flex-1 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500">
                  Confirmar
                </button>
              </div>
            </div>
          )}

          {manualPhase === 'sending' && (
            <div className="flex items-center justify-center gap-2 py-4 text-sm text-gray-500">
              <RefreshCw className="h-4 w-4 animate-spin" />
              Enviando comando…
            </div>
          )}

          {manualPhase === 'done' && manualResult && (
            <div className="space-y-2">
              <div className="rounded-lg bg-green-50 p-3 dark:bg-green-950/30 space-y-1">
                <p className="text-xs font-semibold text-green-700 dark:text-green-400">✓ Comando enviado</p>
                <p className="text-xs text-green-800 dark:text-green-300">
                  {manualResult.kind === 'power_on'
                    ? <>Ligando {manualResult.count} aparelho{manualResult.count !== 1 ? 's' : ''} desligado{manualResult.count !== 1 ? 's' : ''}.</>
                    : <>Setpoint ajustado para <strong>{manualResult.targetSp}°C</strong> em {manualResult.count} aparelho{manualResult.count !== 1 ? 's' : ''}.</>}
                </p>
                <p className="text-xs text-green-600 dark:text-green-500">
                  Reavaliar em 10–15 minutos para verificar o efeito.
                </p>
              </div>
              <p className="text-xs text-gray-400">Próximo ajuste disponível em 2 minutos.</p>
            </div>
          )}

          {manualPhase === 'error' && (
            <div className="space-y-2">
              <div className="rounded-lg bg-red-50 p-3 dark:bg-red-950/30">
                <p className="text-xs font-semibold text-red-700 dark:text-red-400">Falha no envio</p>
                <p className="text-xs text-red-600 dark:text-red-400">{manualError}</p>
              </div>
              <button type="button" onClick={() => setManualPhase('idle')}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50 dark:border-gray-700 dark:text-gray-400">
                Tentar novamente
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Aparelhos vinculados */}
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
          {!zone.devices.length && (
            <div className="py-6 text-center text-sm text-gray-500">Nenhum aparelho vinculado</div>
          )}
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

function toTimeStr(hour: number, minute: number) {
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

function GuardrailsPanel({
  automation, storeId, zoneKey, onUpdated,
}: {
  automation: ZoneAutomationState
  storeId: string
  zoneKey: string
  onUpdated: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [startTime, setStartTime] = useState(toTimeStr(automation.allowed_start_hour, automation.allowed_start_minute))
  const [endTime, setEndTime] = useState(toTimeStr(automation.allowed_end_hour, automation.allowed_end_minute))
  const [isCritical, setIsCritical] = useState(automation.is_critical_zone)
  const [saving, setSaving] = useState(false)

  const isInvalid = startTime >= endTime

  const save = async () => {
    if (isInvalid) return
    setSaving(true)
    await zonesApi.updateGuardrails(storeId, zoneKey, {
      allowed_start_time: startTime,
      allowed_end_time: endTime,
      is_critical_zone: isCritical,
    }).finally(() => setSaving(false))
    setEditing(false)
    onUpdated()
  }

  const displayStart = toTimeStr(automation.allowed_start_hour, automation.allowed_start_minute)
  const displayEnd = toTimeStr(automation.allowed_end_hour, automation.allowed_end_minute)

  return (
    <div className="space-y-1.5">
      {automation.guardrail_active && automation.guardrail_reason && (
        <div className="flex items-start gap-1.5 rounded-md bg-amber-50 px-2.5 py-2 dark:bg-amber-950/30">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-500" />
          <span className="text-xs text-amber-700 dark:text-amber-400">{automation.guardrail_reason}</span>
        </div>
      )}
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
          {automation.is_critical_zone && (
            <span className="inline-flex items-center gap-0.5 rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-600 dark:bg-red-950/50 dark:text-red-400">
              <Shield className="h-2.5 w-2.5" /> Crítica
            </span>
          )}
          <span>Horário: {displayStart}–{displayEnd} (Manaus)</span>
        </div>
        <button type="button" onClick={() => setEditing(v => !v)}
          className="flex-shrink-0 text-xs text-purple-500 underline hover:text-purple-700 dark:hover:text-purple-300">
          {editing ? 'Fechar' : 'Configurar'}
        </button>
      </div>

      {editing && (
        <div className="rounded-lg border border-purple-200 dark:border-purple-900 p-3 space-y-3">
          <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-700 dark:text-gray-300">
            <input type="checkbox" checked={isCritical} onChange={e => setIsCritical(e.target.checked)}
              className="h-3.5 w-3.5 rounded accent-red-500" />
            Zona crítica — bloqueia auto e semi-auto
          </label>
          <div>
            <div className="mb-1.5 text-xs text-gray-500">Janela de horário (horário de Manaus)</div>
            <div className="flex items-center gap-2">
              <input type="time" value={startTime} onChange={e => setStartTime(e.target.value)}
                className="rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
              <span className="text-xs text-gray-400">até</span>
              <input type="time" value={endTime} onChange={e => setEndTime(e.target.value)}
                className="rounded border border-gray-300 px-2 py-1 text-xs dark:border-gray-700 dark:bg-gray-900 dark:text-white" />
            </div>
            {isInvalid && <p className="mt-1 text-xs text-red-500">Horário de início deve ser anterior ao de fim.</p>}
            <p className="mt-1 text-xs text-gray-400">Fora desta janela a automação não executa comandos.</p>
          </div>
          <button type="button" disabled={saving || isInvalid} onClick={save}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-500 disabled:opacity-60 disabled:cursor-not-allowed">
            {saving && <RefreshCw className="h-3 w-3 animate-spin" />}
            Salvar
          </button>
        </div>
      )}
    </div>
  )
}

/* ── Digital Twin Panel ── */

const RISK_META = {
  LOW:      { label: 'Baixo',   cls: 'text-green-600 dark:text-green-400',  bg: 'bg-green-50 dark:bg-green-950/30' },
  MEDIUM:   { label: 'Médio',   cls: 'text-yellow-600 dark:text-yellow-400', bg: 'bg-yellow-50 dark:bg-yellow-950/30' },
  HIGH:     { label: 'Alto',    cls: 'text-orange-600 dark:text-orange-400', bg: 'bg-orange-50 dark:bg-orange-950/30' },
  CRITICAL: { label: 'Crítico', cls: 'text-red-600 dark:text-red-400',       bg: 'bg-red-50 dark:bg-red-950/30' },
} as const

const SIM_LABELS: Record<string, string> = {
  no_action:       'Sem ajuste',
  setpoint_down_1: '↓ Reduzir 1°C',
  setpoint_up_1:   '↑ Aumentar 1°C',
}

function DigitalTwinPanel({ twin }: { twin: DigitalTwinZone | undefined }) {
  if (!twin) return (
    <div className="rounded-lg border border-violet-200 dark:border-violet-900/50 overflow-hidden">
      <div className="flex items-center gap-2 bg-violet-50 px-3 py-2 dark:bg-violet-950/30">
        <Activity className="h-3.5 w-3.5 text-violet-500" />
        <span className="text-xs font-semibold text-violet-700 dark:text-violet-400">Digital Twin</span>
      </div>
      <div className="p-3 text-xs text-gray-400">Calculando previsões…</div>
    </div>
  )

  const risk = RISK_META[twin.risk_level] ?? RISK_META.LOW
  const trend = twin.trend_c_per_hour
  const TrendIcon = trend != null && trend > 0.1 ? TrendingUp : trend != null && trend < -0.1 ? TrendingDown : null
  const trendColor = trend != null && trend > 0.1 ? 'text-orange-500' : 'text-blue-500'
  const trendStr = trend != null ? `${trend > 0 ? '+' : ''}${trend.toFixed(1)}°C/h` : '—'
  const confPct = Math.round(twin.confidence * 100)

  return (
    <div className="rounded-lg border border-violet-200 dark:border-violet-900/50 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 bg-violet-50 px-3 py-2 dark:bg-violet-950/30">
        <Activity className="h-3.5 w-3.5 text-violet-500 flex-shrink-0" />
        <span className="text-xs font-semibold text-violet-700 dark:text-violet-400">Digital Twin</span>
        <div className="ml-auto flex items-center gap-2 text-[10px]">
          {twin.stale_device_count > 0 && (
            <span className="text-amber-500" title={`${twin.stale_device_count} leitura(s) obsoleta(s)`}>
              {twin.stale_device_count} stale
            </span>
          )}
          <span className={twin.freshness_ratio < 0.5 ? 'text-amber-400' : 'text-violet-400'}>
            {Math.round(twin.freshness_ratio * 100)}% frescos · conf. {confPct}%
          </span>
        </div>
      </div>

      <div className="p-3 space-y-3">
        {/* Risco + Tendência */}
        <div className="grid grid-cols-2 gap-2">
          <div className={cn('rounded-md px-2 py-2 text-center', risk.bg)}>
            <div className="text-[10px] text-gray-500 dark:text-gray-400">Risco</div>
            <div className={cn('text-sm font-bold', risk.cls)}>{risk.label}</div>
          </div>
          <div className="rounded-md bg-gray-50 dark:bg-gray-950 px-2 py-2 text-center">
            <div className="text-[10px] text-gray-500">Tendência</div>
            <div className={cn('flex items-center justify-center gap-1 text-sm font-bold', trend != null ? trendColor : 'text-gray-400')}>
              {TrendIcon && <TrendIcon className="h-3.5 w-3.5" />}
              {trendStr}
            </div>
          </div>
        </div>

        {/* Previsões de temperatura */}
        <div>
          <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">Previsão de temperatura</div>
          <div className="grid grid-cols-3 gap-1.5">
            {([
              { label: '15 min', val: twin.predicted_temp_15m },
              { label: '30 min', val: twin.predicted_temp_30m },
              { label: '60 min', val: twin.predicted_temp_60m },
            ] as const).map(({ label, val }) => (
              <div key={label} className="rounded bg-gray-50 dark:bg-gray-950 px-1.5 py-2 text-center">
                <div className="text-[10px] text-gray-400">{label}</div>
                <div className="mt-0.5 text-xs font-semibold text-gray-800 dark:text-gray-200">
                  {val != null ? `${val.toFixed(1)}°C` : '—'}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Recomendação */}
        {twin.recommended_action !== 'NONE' && (
          <div className={cn('rounded-md px-2.5 py-2 space-y-0.5', risk.bg)}>
            <div className={cn('text-xs font-semibold', risk.cls)}>
              {twin.recommended_action.replace(/_/g, ' ')}
            </div>
            <div className="text-xs text-gray-600 dark:text-gray-400 leading-snug">
              {twin.explanation}
            </div>
          </div>
        )}

        {/* Simulações */}
        {twin.simulated_actions.length > 0 && (
          <div>
            <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">Simulações (heurístico)</div>
            <div className="space-y-1">
              {twin.simulated_actions.map(sim => (
                <div
                  key={sim.action}
                  className={cn(
                    'flex items-center gap-2 rounded px-2.5 py-1.5 text-xs',
                    sim.feasible
                      ? 'bg-gray-50 dark:bg-gray-950'
                      : 'bg-gray-100/60 dark:bg-gray-900/50 opacity-60',
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-gray-700 dark:text-gray-300">
                      {SIM_LABELS[sim.action] ?? sim.action}
                    </div>
                    {sim.block_reason && (
                      <div className="text-[10px] text-red-500">{sim.block_reason}</div>
                    )}
                  </div>
                  {sim.feasible && (
                    <div className="flex-shrink-0 text-right font-mono">
                      <div className="text-gray-500 text-[10px]">
                        30m <span className="text-gray-700 dark:text-gray-300">{sim.predicted_temp_30m?.toFixed(1) ?? '—'}°C</span>
                      </div>
                      <div className="text-gray-400 text-[10px]">
                        60m <span className="text-gray-600 dark:text-gray-400">{sim.predicted_temp_60m?.toFixed(1) ?? '—'}°C</span>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="text-[10px] text-gray-400">
          Calculado às {formatTime(twin.computed_at)}
          {' · '}confiança {confPct}% · heurístico, não executa comandos
        </div>
      </div>
    </div>
  )
}

/* ── useMapTransform — pan, zoom, touch ── */

function useMapTransform(editModeRef?: React.RefObject<boolean>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1, dragging: false })
  const cur = useRef(transform)
  cur.current = transform

  const startPos      = useRef({ x: 0, y: 0 })
  const hasMoved      = useRef(false)
  const pinchDist     = useRef(0)
  const activePointers = useRef<Map<number, { x: number; y: number }>>(new Map())

  const MIN = 0.3
  const MAX = 8

  const clamp = (s: number) => Math.min(MAX, Math.max(MIN, s))

  const zoomAt = useCallback((factor: number, cx: number, cy: number) => {
    setTransform(t => {
      const ns = clamp(t.scale * factor)
      const r  = ns / t.scale
      return { ...t, scale: ns, x: cx - (cx - t.x) * r, y: cy - (cy - t.y) * r }
    })
  }, [])

  const zoom = useCallback((factor: number) => {
    const el = containerRef.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    zoomAt(factor, width / 2, height / 2)
  }, [zoomAt])

  const resetView = useCallback(() =>
    setTransform({ x: 0, y: 0, scale: 1, dragging: false }), [])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const handler = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top)
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [zoomAt])

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    // Em modo edição, o ZoneEditor captura os eventos — não interferir
    if (editModeRef?.current && activePointers.current.size === 0) return
    activePointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (activePointers.current.size === 1) {
      hasMoved.current = false
      startPos.current = { x: e.clientX - cur.current.x, y: e.clientY - cur.current.y }
      setTransform(t => ({ ...t, dragging: true }))
    } else {
      const pts = [...activePointers.current.values()]
      const dx = pts[0].x - pts[1].x
      const dy = pts[0].y - pts[1].y
      pinchDist.current = Math.sqrt(dx * dx + dy * dy)
    }
  }, [editModeRef])

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!activePointers.current.has(e.pointerId)) return
    activePointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (activePointers.current.size === 2) {
      const pts = [...activePointers.current.values()]
      const dx = pts[0].x - pts[1].x
      const dy = pts[0].y - pts[1].y
      const dist = Math.sqrt(dx * dx + dy * dy)
      const el = containerRef.current
      if (el && pinchDist.current > 0) {
        const r = el.getBoundingClientRect()
        const mid = {
          x: (pts[0].x + pts[1].x) / 2 - r.left,
          y: (pts[0].y + pts[1].y) / 2 - r.top,
        }
        zoomAt(dist / pinchDist.current, mid.x, mid.y)
      }
      pinchDist.current = dist
      hasMoved.current = true
    } else if (activePointers.current.size === 1) {
      const nx = e.clientX - startPos.current.x
      const ny = e.clientY - startPos.current.y
      if (Math.abs(nx - cur.current.x) + Math.abs(ny - cur.current.y) > 3)
        hasMoved.current = true
      setTransform(t => ({ ...t, x: nx, y: ny }))
    }
  }, [zoomAt])

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    activePointers.current.delete(e.pointerId)
    if (activePointers.current.size === 0) {
      pinchDist.current = 0
      setTransform(t => ({ ...t, dragging: false }))
    }
  }, [])

  const onDoubleClick = useCallback((e: React.MouseEvent) => {
    const el = containerRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    zoomAt(2, e.clientX - r.left, e.clientY - r.top)
  }, [zoomAt])

  return {
    containerRef,
    transform,
    hasMoved,
    zoom,
    resetView,
    containerHandlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: onPointerUp,
      onDoubleClick,
    },
  }
}

/* ── Funções puras ── */

// ── Floor config ──────────────────────────────────────────────────────────────

interface FloorConfig {
  imageX: number
  imageY: number
  imageW: number
  imageH: number
}

function getFloorConfig(_floor: number): FloorConfig {
  // Padrão: ocupa o viewbox inteiro sem margens, eliminando faixas brancas.
  // Ajuste x/y/imageW/imageH por andar conforme as plantas forem calibradas.
  return { imageX: 0, imageY: 0, imageW: VIEWBOX.w, imageH: VIEWBOX.h }
}

// ── Point-in-polygon inclusivo (ST_Covers: interior OU na fronteira) ──────────

type Pt = { x: number; y: number }

function onSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): boolean {
  const cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
  if (Math.abs(cross) > 1e-9) return false
  const dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
  const lenSq = (bx - ax) ** 2 + (by - ay) ** 2
  return dot >= 0 && dot <= lenSq
}

function pointInPolygon(px: number, py: number, poly: Pt[]): boolean {
  // 1. Fronteira
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    if (onSegment(px, py, poly[j].x, poly[j].y, poly[i].x, poly[i].y)) return true
  }
  // 2. Interior — ray casting
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i].x, yi = poly[i].y, xj = poly[j].x, yj = poly[j].y
    if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi)
      inside = !inside
  }
  return inside
}

// ── IDW interpolation ─────────────────────────────────────────────────────────

function interpolateTemp(x: number, y: number, points: HeatPoint[]): number | null {
  const valid = points.filter(p => p.temp != null)
  if (!valid.length) return null

  let weightedSum = 0
  let weightTotal = 0

  for (const p of valid) {
    const dx = x - p.x
    const dy = y - p.y
    const dist = Math.sqrt(dx * dx + dy * dy)
    if (dist < 1) return p.temp!
    const w = 1 / (dist * dist)
    weightedSum += Number(p.temp) * w
    weightTotal += w
  }

  return weightedSum / weightTotal
}

interface ThermalCell { x: number; y: number; color: string; opacity: number }

/** Zona com polígono SVG, banda ideal e confiança de dados — usada pelo IDW */
interface ZonePoly {
  poly: Pt[]
  idealMin: number
  idealMax: number
  /** freshness_ratio 0–1 vindo do digital twin; 1 = todos os pontos frescos */
  freshnessRatio: number
}

function buildThermalGrid(
  points: HeatPoint[],
  fallbackTemp: number | null,
  zonePolys: ZonePoly[],
): ThermalCell[] {
  const valid = points.filter(p => p.temp != null)
  if (!valid.length && fallbackTemp == null) return []

  const hasPolys = zonePolys.length > 0
  const cells: ThermalCell[] = []

  for (let y = 0; y < VIEWBOX.h; y += GRID_CELL) {
    for (let x = 0; x < VIEWBOX.w; x += GRID_CELL) {
      const cx = x + GRID_CELL / 2
      const cy = y + GRID_CELL / 2

      const zone = hasPolys ? zonePolys.find(z => pointInPolygon(cx, cy, z.poly)) : null
      if (hasPolys && !zone) continue

      const temp = valid.length ? interpolateTemp(cx, cy, valid) : fallbackTemp
      if (temp == null) continue

      const color = zone
        ? thermalColorByDelta(tempDelta(temp, zone.idealMin, zone.idealMax))
        : thermalColor(temp)

      // Opacidade dimina quando os dados são maioritariamente stale (freshness baixa)
      const opacity = zone ? Math.max(0.25, zone.freshnessRatio) : 1.0

      cells.push({ x, y, color, opacity })
    }
  }
  return cells
}

/** Desvio de temp face à banda [min, max]: negativo=frio, 0=conforto, positivo=quente */
function tempDelta(temp: number, idealMin: number, idealMax: number): number {
  if (temp < idealMin) return temp - idealMin   // negativo
  if (temp > idealMax) return temp - idealMax   // positivo
  return 0
}

/** Escala divergente centrada na banda ideal da zona */
function thermalColorByDelta(delta: number): string {
  if (delta <= -3)   return '#1D4ED8'  // muito frio
  if (delta <= -1.5) return '#3B82F6'  // frio
  if (delta <= -0.5) return '#93C5FD'  // levemente frio
  if (delta <=  0.5) return '#16A34A'  // confortável
  if (delta <=  1.5) return '#FACC15'  // levemente quente
  if (delta <=  3)   return '#FB923C'  // quente
  return '#DC2626'                      // muito quente / crítico
}

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
