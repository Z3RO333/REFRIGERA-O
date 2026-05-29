/**
 * ZoneEditor — Editor visual de zonas térmicas no mapa SVG.
 * Geometria salva em % da planta (unit: "percent"), independente de resolução.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Search, Trash2, X } from 'lucide-react'
import { customZonesApi, storesApi, zonesApi } from '../../api/client'
import { cn, formatTemp } from '../../lib/utils'
import type { CustomZone, Device, Sector, ZoneGeometry } from '../../types'

const ZONE_COLORS = ['#3B82F6','#8B5CF6','#10B981','#F59E0B','#EF4444','#EC4899','#06B6D4','#84CC16']
const STATUS_COLOR: Record<string,string> = { COLD:'#2563EB', COMFORT:'#22C55E', WARM:'#EAB308', HOT:'#F97316', CRITICAL:'#EF4444', NO_READING:'#6B7280' }

type DrawMode = 'rect' | 'polygon'
type PercentPoint = { x: number; y: number }

interface Props {
  storeId: string; floor: number; editMode: boolean
  svgRef: React.RefObject<SVGSVGElement>
  viewbox: { w: number; h: number }
  transform: { x: number; y: number; scale: number }
  onZoneClick?: (zoneKey: string) => void
}

function clamp(n: number, min = 0, max = 100) {
  return Math.min(max, Math.max(min, n))
}
function roundPct(n: number) {
  return Math.round(clamp(n) * 100) / 100
}
function toPercent(svgX: number, svgY: number, vb: { w: number; h: number }) {
  return { x: roundPct(svgX / vb.w * 100), y: roundPct(svgY / vb.h * 100) }
}
function fromPercent(px: number, py: number, vb: { w: number; h: number }) {
  return { x: px / 100 * vb.w, y: py / 100 * vb.h }
}
/** Canvas 100×100 reutilizável para Path2D + isPointInPath em coords percentuais */
const _pipCtx: CanvasRenderingContext2D | null = (() => {
  if (typeof document === 'undefined') return null
  const c = document.createElement('canvas')
  c.width = 100; c.height = 100
  return c.getContext('2d')
})()

/** Cria Path2D em coordenadas percentuais (0-100) */
function makePercentPath(pts: PercentPoint[]): Path2D {
  const p = new Path2D()
  if (!pts.length) return p
  p.moveTo(pts[0].x, pts[0].y)
  for (let i = 1; i < pts.length; i++) p.lineTo(pts[i].x, pts[i].y)
  p.closePath()
  return p
}

/** PIP inclusivo: usa Path2D (interior) + verificação de fronteira (ST_Covers) */
function pointInPolygon(px: number, py: number, pts: PercentPoint[]): boolean {
  if (!pts.length) return false
  // 1. Fronteira
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const { x: ax, y: ay } = pts[j], { x: bx, y: by } = pts[i]
    const cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if (Math.abs(cross) < 1e-9) {
      const dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
      const lenSq = (bx - ax) ** 2 + (by - ay) ** 2
      if (dot >= 0 && dot <= lenSq) return true
    }
  }
  // 2. Interior via Path2D (evita ray-casting manual)
  if (_pipCtx) {
    return _pipCtx.isPointInPath(makePercentPath(pts), px, py)
  }
  // Fallback: ray casting
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const { x: xi, y: yi } = pts[i], { x: xj, y: yj } = pts[j]
    if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) inside = !inside
  }
  return inside
}
function geoBounds(pts: PercentPoint[]) {
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y)
  return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) }
}
function movePointsWithinBounds(pts: PercentPoint[], dx: number, dy: number) {
  const b = geoBounds(pts)
  const safeDx = Math.min(100 - b.maxX, Math.max(-b.minX, dx))
  const safeDy = Math.min(100 - b.maxY, Math.max(-b.minY, dy))
  return pts.map(p => ({ x: roundPct(p.x + safeDx), y: roundPct(p.y + safeDy) }))
}
function geoKey(geo: ZoneGeometry) {
  return geo.points.map(p => `${p.x}:${p.y}`).join('|')
}
function geoToSVGPoints(geo: ZoneGeometry, vb: { w: number; h: number }) {
  return geo.points.map(p => { const s = fromPercent(p.x, p.y, vb); return `${s.x},${s.y}` }).join(' ')
}

export default function ZoneEditor({ storeId, floor, editMode, svgRef, viewbox, onZoneClick }: Props) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<CustomZone | null>(null)
  const [drawMode, setDrawMode] = useState<DrawMode>('rect')
  const [showForm, setShowForm] = useState(false)
  const [pendingGeo, setPendingGeo] = useState<ZoneGeometry | null>(null)
  const [rectStart, setRectStart] = useState<PercentPoint | null>(null)
  const [rectCur, setRectCur] = useState<PercentPoint | null>(null)
  const [polyPoints, setPolyPoints] = useState<PercentPoint[]>([])
  const [polyCur, setPolyCur] = useState<PercentPoint | null>(null)
  const [livePos, setLivePos] = useState<Record<string, PercentPoint[]>>({})
  const livePosRef = useRef(livePos)  // ref para evitar stale closure no useEffect
  livePosRef.current = livePos
  const [dragging, setDragging] = useState<{ zoneKey: string; startPts: PercentPoint[]; startMouse: PercentPoint } | null>(null)
  const draggingRef = useRef(dragging)
  draggingRef.current = dragging
  const hasMoved = useRef(false)
  const suppressClick = useRef(false)

  const [formName, setFormName] = useState('')
  const [formMin, setFormMin] = useState(20)
  const [formMax, setFormMax] = useState(24)
  const [formSpMin, setFormSpMin] = useState(18)  // limite operacional do setpoint (mín.)
  const [formSpMax, setFormSpMax] = useState(28)  // limite operacional do setpoint (máx.)
  const [formRecoveryEnabled, setFormRecoveryEnabled] = useState(true)
  const [formRecoveryMin, setFormRecoveryMin] = useState(18)
  const [formRecoveryTarget, setFormRecoveryTarget] = useState(22)
  const [formRecoveryDuration, setFormRecoveryDuration] = useState(60)
  const [formType, setFormType] = useState<'ABERTA'|'SALA_FECHADA'>('ABERTA')
  const [formColor, setFormColor] = useState(ZONE_COLORS[0])
  const [formDevices, setFormDevices] = useState<string[]>([])
  const [formSearch, setFormSearch] = useState('')
  const [formError, setFormError] = useState<string|null>(null)
  const [autoLinkedGeoKey, setAutoLinkedGeoKey] = useState<string | null>(null)

  const { data: customZones = [] } = useQuery<CustomZone[]>({
    queryKey: ['custom-zones', storeId],
    queryFn: () => customZonesApi.list(storeId),
    refetchInterval: 30000,
  })
  const { data: storeDevices = [], isFetched: devicesFetched } = useQuery<Device[]>({
    queryKey: ['store-devices', storeId],
    queryFn: () => storesApi.devices(storeId),
    enabled: editMode || showForm,
  })
  const { data: sectors = [], isFetched: sectorsFetched } = useQuery<Sector[]>({
    queryKey: ['store-sectors', storeId],
    queryFn: () => storesApi.sectors(storeId),
    enabled: editMode || showForm,
  })
  // Automations da loja — usadas para ler/escrever setpoint_min/max ao editar zona
  const { data: storeAutomations = [] } = useQuery<any[]>({
    queryKey: ['zones-automation', storeId],
    queryFn: () => zonesApi.list(storeId),
    enabled: editMode || showForm,
  })

  const invalidate = () => {
    ['custom-zones','zones-automation','digital-twin','store-devices'].forEach(k =>
      qc.invalidateQueries({ queryKey: [k, storeId] }))
  }

  const createMutation = useMutation({
    mutationFn: (d: Parameters<typeof customZonesApi.create>[1]) => customZonesApi.create(storeId, d),
    onSuccess: () => { invalidate(); closeForm() },
    onError: (e: any) => setFormError(e?.response?.data?.detail ?? 'Erro ao criar zona.'),
  })
  const updateMutation = useMutation({
    mutationFn: ({ key, data }: { key: string; data: Parameters<typeof customZonesApi.update>[2] }) =>
      customZonesApi.update(storeId, key, data),
    onSuccess: () => invalidate(),
    onError: (e: any) => setFormError(e?.response?.data?.detail ?? 'Erro ao salvar zona.'),
  })
  const deleteMutation = useMutation({
    mutationFn: (key: string) => customZonesApi.delete(storeId, key),
    onSuccess: () => { invalidate(); setSelected(null); closeForm() },
  })

  const floorZones = customZones.filter(z => z.floor === floor && z.geometry != null)
  const sectorFloorById = useMemo(
    () => new Map(sectors.map((s: Sector) => [s.id, s.floor])),
    [sectors],
  )
  const acDevicesOnFloor = useMemo(
    () => storeDevices.filter((d: Device) => {
      const isSelectedInForm = formDevices.includes(d.id)
      return !d.is_external_sensor && (sectorFloorById.get(d.sector_id || '') === floor || isSelectedInForm)
    }),
    [storeDevices, sectorFloorById, floor, formDevices],
  )
  const filteredFormDevices = useMemo(() => {
    const q = formSearch.trim().toLowerCase()
    if (!q) return acDevicesOnFloor
    return acDevicesOnFloor.filter((d: Device) =>
      d.name.toLowerCase().includes(q)
      || d.brise_id.toLowerCase().includes(q)
      || (d.sector_name ?? '').toLowerCase().includes(q)
    )
  }, [acDevicesOnFloor, formSearch])

  const screenToPct = useCallback((clientX: number, clientY: number) => {
    const el = svgRef.current
    if (!el) return { x: 0, y: 0 }
    // getScreenCTM() corretamente lida com viewBox, preserveAspectRatio e CSS transform (pan/zoom)
    // Isso resolve o offset causado pelo letterboxing quando o container não tem proporção 800×556
    try {
      const pt = el.createSVGPoint()
      pt.x = clientX
      pt.y = clientY
      const svgPt = pt.matrixTransform(el.getScreenCTM()!.inverse())
      return toPercent(svgPt.x, svgPt.y, viewbox)
    } catch {
      // Fallback para navegadores mais antigos
      const rect = el.getBoundingClientRect()
      return toPercent(
        (clientX - rect.left) * viewbox.w / rect.width,
        (clientY - rect.top)  * viewbox.h / rect.height,
        viewbox,
      )
    }
  }, [svgRef, viewbox])

  const devicesInsideGeo = useCallback((geo: ZoneGeometry) =>
    storeDevices.filter((d: Device) => {
      if (d.is_external_sensor) return false
      if (sectorFloorById.get(d.sector_id || '') !== floor) return false
      if (d.position_x == null || d.position_y == null) return false
      const p = toPercent(Number(d.position_x), Number(d.position_y), viewbox)
      return pointInPolygon(p.x, p.y, geo.points)
    }).map((d: Device) => d.id)
  , [storeDevices, sectorFloorById, floor, viewbox])

  /** IDs dos devices que cairiam dentro do polígono/rect que está a ser desenhado */
  const previewDeviceIds = useMemo((): Set<string> => {
    if (!editMode) return new Set()
    let geo: ZoneGeometry | null = null
    if (rectStart && rectCur) {
      const x = Math.min(rectStart.x, rectCur.x), y = Math.min(rectStart.y, rectCur.y)
      const w = Math.abs(rectCur.x - rectStart.x), h = Math.abs(rectCur.y - rectStart.y)
      if (w > 1 && h > 1)
        geo = { type: 'polygon', unit: 'percent', points: [{x,y},{x:x+w,y},{x:x+w,y:y+h},{x,y:y+h}] }
    } else if (polyPoints.length >= 3) {
      geo = { type: 'polygon', unit: 'percent', points: polyPoints }
    }
    if (!geo) return new Set()
    return new Set(devicesInsideGeo(geo))
  }, [editMode, rectStart, rectCur, polyPoints, devicesInsideGeo])

  const openForm = useCallback((zone?: CustomZone, geo?: ZoneGeometry) => {
    if (zone) {
      setFormName(zone.name); setFormMin(zone.ideal_min); setFormMax(zone.ideal_max)
      setFormType(zone.zone_type as any); setFormColor(zone.color ?? ZONE_COLORS[0])
      setFormDevices(zone.device_ids)
      // Limite operacional vem da ZoneAutomation, não da CustomZone — busca pela key
      const auto = storeAutomations.find((a: any) => a.zone_key === zone.zone_key)
      setFormSpMin(auto?.setpoint_min ?? 18)
      setFormSpMax(auto?.setpoint_max ?? 28)
      setFormRecoveryEnabled(auto?.recovery_enabled ?? true)
      setFormRecoveryMin(auto?.recovery_min_setpoint ?? 18)
      setFormRecoveryTarget(auto?.recovery_target_setpoint ?? 22)
      setFormRecoveryDuration(auto?.recovery_max_duration_minutes ?? 60)
      setAutoLinkedGeoKey(null)
    } else {
      setFormName(''); setFormMin(20); setFormMax(24); setFormType('ABERTA')
      setFormColor(ZONE_COLORS[0])
      setFormSpMin(18); setFormSpMax(28)
      setFormRecoveryEnabled(true); setFormRecoveryMin(18); setFormRecoveryTarget(22); setFormRecoveryDuration(60)
      setFormDevices(geo ? devicesInsideGeo(geo) : [])
      setAutoLinkedGeoKey(null)
    }
    setFormSearch('')
    setFormError(null); setShowForm(true)
  }, [devicesInsideGeo, storeAutomations])

  const closeForm = useCallback(() => {
    setShowForm(false); setPendingGeo(null); setSelected(null); setFormError(null); setFormSearch(''); setAutoLinkedGeoKey(null)
  }, [])

  useEffect(() => {
    if (!showForm || selected || !pendingGeo) return
    if (!devicesFetched || !sectorsFetched) return
    const key = geoKey(pendingGeo)
    if (autoLinkedGeoKey === key) return
    setFormDevices(devicesInsideGeo(pendingGeo))
    setAutoLinkedGeoKey(key)
  }, [showForm, selected, pendingGeo, devicesFetched, sectorsFetched, autoLinkedGeoKey, devicesInsideGeo])

  const handleSave = useCallback(async () => {
    const name = formName.trim()
    if (!name) { setFormError('Nome obrigatório'); return }
    if (formMin >= formMax) { setFormError('Mín ideal deve ser < Máx ideal'); return }
    if (formSpMin >= formSpMax) { setFormError('Mín operacional deve ser < Máx operacional'); return }
    if (formRecoveryMin >= formRecoveryTarget) { setFormError('Mín recuperação deve ser < alvo recuperação'); return }
    if (formMin < formSpMin || formMax > formSpMax) {
      setFormError('Faixa ideal precisa estar dentro do limite operacional')
      return
    }
    setFormError(null)
    if (selected) {
      // 1. Atualiza dados da custom zone (nome, ideal, devices...)
      updateMutation.mutate({ key: selected.zone_key,
        data: { name, ideal_min: formMin, ideal_max: formMax, zone_type: formType, color: formColor, device_ids: formDevices } })
      // 2. Atualiza limite operacional da automation (mode preservado)
      const auto = storeAutomations.find((a: any) => a.zone_key === selected.zone_key)
      if (auto && (
        auto.setpoint_min !== formSpMin
        || auto.setpoint_max !== formSpMax
        || auto.recovery_enabled !== formRecoveryEnabled
        || auto.recovery_min_setpoint !== formRecoveryMin
        || auto.recovery_target_setpoint !== formRecoveryTarget
        || auto.recovery_max_duration_minutes !== formRecoveryDuration
      )) {
        try {
          await zonesApi.setMode(storeId, selected.zone_key, {
            mode: auto.mode ?? 'manual',
            priority: auto.priority,
            setpoint_min: formSpMin,
            setpoint_max: formSpMax,
            recovery_enabled: formRecoveryEnabled,
            recovery_min_setpoint: formRecoveryMin,
            recovery_target_setpoint: formRecoveryTarget,
            recovery_max_duration_minutes: formRecoveryDuration,
          })
          invalidate()
        } catch (e: any) {
          setFormError(e?.response?.data?.detail ?? 'Erro ao salvar limite operacional.')
        }
      }
    } else if (pendingGeo) {
      createMutation.mutate({ name, ideal_min: formMin, ideal_max: formMax, zone_type: formType,
        color: formColor, device_ids: formDevices, floor, geometry: pendingGeo },
        {
          onSuccess: async (created: any) => {
            // Aplica limite operacional na automation recém-criada (defaults backend = 18-28)
            if (
              formSpMin !== 18 || formSpMax !== 28
              || !formRecoveryEnabled || formRecoveryMin !== 18
              || formRecoveryTarget !== 22 || formRecoveryDuration !== 60
            ) {
              try {
                await zonesApi.setMode(storeId, created.zone_key, {
                  mode: 'manual',
                  setpoint_min: formSpMin,
                  setpoint_max: formSpMax,
                  recovery_enabled: formRecoveryEnabled,
                  recovery_min_setpoint: formRecoveryMin,
                  recovery_target_setpoint: formRecoveryTarget,
                  recovery_max_duration_minutes: formRecoveryDuration,
                })
                invalidate()
              } catch { /* já criou, falha silenciosa no setpoint custom */ }
            }
          },
        },
      )
    }
  }, [formName, formMin, formMax, formSpMin, formSpMax, formRecoveryEnabled, formRecoveryMin,
      formRecoveryTarget, formRecoveryDuration, formType, formColor, formDevices,
      selected, pendingGeo, floor, createMutation, updateMutation, storeAutomations, storeId])

  const cancelDrawing = useCallback(() => {
    setRectStart(null)
    setRectCur(null)
    setPolyPoints([])
    setPolyCur(null)
    setDragging(null)
    hasMoved.current = false
    suppressClick.current = false
  }, [])

  useEffect(() => {
    cancelDrawing()
    if (!editMode) closeForm()
  }, [drawMode, editMode, cancelDrawing, closeForm])

  useEffect(() => {
    if (!editMode) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showForm) closeForm()
        else cancelDrawing()
      }
      if (e.key === 'Enter' && drawMode === 'polygon' && polyPoints.length >= 3 && !showForm) {
        const geo: ZoneGeometry = { type:'polygon', unit:'percent', points: polyPoints }
        setPolyPoints([]); setPolyCur(null); setPendingGeo(geo); openForm(undefined, geo)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [editMode, showForm, closeForm, cancelDrawing, drawMode, polyPoints, openForm])

  // Listeners globais — pointer events (mouse + touch + stylus)
  useEffect(() => {
    if (!editMode) return
    const onMove = (e: PointerEvent) => {
      const pct = screenToPct(e.clientX, e.clientY)
      if (rectStart) setRectCur(pct)
      if (polyPoints.length > 0) setPolyCur(pct)
      const dr = draggingRef.current
      if (dr) {
        hasMoved.current = true
        suppressClick.current = true
        const dx = pct.x - dr.startMouse.x, dy = pct.y - dr.startMouse.y
        setLivePos(lp => ({ ...lp, [dr.zoneKey]: movePointsWithinBounds(dr.startPts, dx, dy) }))
      }
    }
    const onUp = (e: PointerEvent) => {
      const dr = draggingRef.current
      if (dr) {
        const live = livePosRef.current[dr.zoneKey]
        if (live && hasMoved.current)
          updateMutation.mutate({ key: dr.zoneKey, data: { geometry: { type:'polygon', unit:'percent', points: live } } })
        setDragging(null); hasMoved.current = false
      }
      if (rectStart) {
        const pct = screenToPct(e.clientX, e.clientY)
        const x = Math.min(rectStart.x, pct.x), y = Math.min(rectStart.y, pct.y)
        const w = Math.abs(pct.x - rectStart.x), h = Math.abs(pct.y - rectStart.y)
        setRectStart(null); setRectCur(null)
        if (w > 2 && h > 2) {
          const geo: ZoneGeometry = { type:'polygon', unit:'percent', points:[{x,y},{x:x+w,y},{x:x+w,y:y+h},{x,y:y+h}] }
          setPendingGeo(geo); openForm(undefined, geo)
        }
      }
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    return () => { window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUp) }
  }, [editMode, rectStart, polyPoints, screenToPct, updateMutation, openForm])

  const onBgPointerDown = useCallback((e: React.PointerEvent<SVGRectElement>) => {
    if (!editMode || showForm || dragging || drawMode !== 'rect') return
    if (e.button !== 0 && e.pointerType === 'mouse') return
    e.stopPropagation()
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    const pct = screenToPct(e.clientX, e.clientY)
    setRectStart(pct); setRectCur(pct); hasMoved.current = false
  }, [editMode, showForm, dragging, drawMode, screenToPct])

  const onBgClick = useCallback((e: React.MouseEvent<SVGRectElement>) => {
    if (!editMode || showForm || drawMode !== 'polygon') return
    if (e.detail > 1) return
    e.stopPropagation()
    setPolyPoints(prev => [...prev, screenToPct(e.clientX, e.clientY)])
  }, [editMode, showForm, drawMode, screenToPct])

  const onBgDblClick = useCallback((e: React.MouseEvent) => {
    if (!editMode || drawMode !== 'polygon' || polyPoints.length < 3) return
    e.stopPropagation()
    const geo: ZoneGeometry = { type:'polygon', unit:'percent', points: polyPoints }
    setPolyPoints([]); setPolyCur(null); setPendingGeo(geo); openForm(undefined, geo)
  }, [editMode, drawMode, polyPoints, openForm])

  const onZonePointerDown = useCallback((e: React.PointerEvent, zone: CustomZone) => {
    if (!editMode || !zone.geometry) return
    if (e.button !== 0 && e.pointerType === 'mouse') return
    e.stopPropagation()
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    hasMoved.current = false
    const pct = screenToPct(e.clientX, e.clientY)
    setLivePos(lp => ({ ...lp, [zone.zone_key]: zone.geometry!.points }))
    setDragging({ zoneKey: zone.zone_key, startPts: zone.geometry.points, startMouse: pct })
  }, [editMode, screenToPct])

  const handleZoneClick = useCallback((e: React.MouseEvent, zone: CustomZone) => {
    e.stopPropagation()
    if (suppressClick.current) { suppressClick.current = false; return }
    if (hasMoved.current) return
    if (editMode) { setSelected(zone); openForm(zone) }
    else onZoneClick?.(zone.zone_key)
  }, [editMode, openForm, onZoneClick])

  const toggleDevice = (id: string) =>
    setFormDevices(prev => prev.includes(id) ? prev.filter(d => d !== id) : [...prev, id])

  const rectPreview = rectStart && rectCur ? (() => {
    const s = fromPercent(rectStart.x, rectStart.y, viewbox)
    const c = fromPercent(rectCur.x, rectCur.y, viewbox)
    return { x: Math.min(s.x,c.x), y: Math.min(s.y,c.y), w: Math.abs(c.x-s.x), h: Math.abs(c.y-s.y) }
  })() : null

  return (
    <g onDoubleClick={onBgDblClick as any}>
      {editMode && (
        <rect x={0} y={0} width={viewbox.w} height={viewbox.h}
          fill="transparent" style={{ cursor: 'crosshair' }}
          onPointerDown={onBgPointerDown} onClick={onBgClick} />
      )}

      {/* Zonas salvas */}
      {floorZones.map(zone => {
        const pts = livePos[zone.zone_key] ?? zone.geometry!.points
        const geo: ZoneGeometry = { ...zone.geometry!, points: pts }
        const svgPts = geoToSVGPoints(geo, viewbox)
        const color = zone.color ?? '#3B82F6'
        const statusColor = STATUS_COLOR[zone.temp_status] ?? color
        const isSelected = selected?.zone_key === zone.zone_key
        const b = geoBounds(geo.points)
        const cx = fromPercent((b.minX+b.maxX)/2, (b.minY+b.maxY)/2, viewbox)
        return (
          <g key={zone.zone_key} data-zone={zone.zone_key}>
            <polygon points={svgPts}
              fill={`${statusColor}18`}
              stroke={isSelected ? '#A78BFA' : `${statusColor}99`}
              strokeWidth={isSelected ? 2.5 : 1.5}
              strokeDasharray={zone.zone_type === 'SALA_FECHADA' ? '5 3' : undefined}
              style={{ cursor: editMode ? 'move' : 'pointer', touchAction:'none' }}
              onPointerDown={e => onZonePointerDown(e, zone)}
              onClick={e => handleZoneClick(e, zone)} />
            <text x={cx.x} y={cx.y-6} textAnchor="middle" fontSize={9} fontWeight="600"
              fill={statusColor} style={{ pointerEvents:'none', userSelect:'none' }}>
              {zone.name}
            </text>
            {zone.current_temp != null && (
              <text x={cx.x} y={cx.y+7} textAnchor="middle" fontSize={10} fontWeight="700"
                fill="#F1F5F9" opacity={0.85} style={{ pointerEvents:'none', userSelect:'none' }}>
                {formatTemp(zone.current_temp)}
              </text>
            )}
          </g>
        )
      })}

      {/* Preview rect */}
      {rectPreview && (
        <rect x={rectPreview.x} y={rectPreview.y} width={rectPreview.w} height={rectPreview.h}
          fill="rgba(139,92,246,0.15)" stroke="#A78BFA" strokeWidth={1.5}
          strokeDasharray="5 3" rx={4} style={{ pointerEvents:'none' }} />
      )}

      {/* Preview polygon */}
      {polyPoints.length > 0 && (() => {
        const allPts = [...polyPoints, polyCur ?? polyPoints[polyPoints.length-1]]
        const pts = allPts.map(p => { const s = fromPercent(p.x,p.y,viewbox); return `${s.x},${s.y}` }).join(' ')
        return (
          <>
            <polyline points={pts} fill="rgba(139,92,246,0.12)" stroke="#A78BFA"
              strokeWidth={1.5} strokeDasharray="5 3" style={{ pointerEvents:'none' }} />
            {polyPoints.map((p,i) => {
              const s = fromPercent(p.x,p.y,viewbox)
              return <circle key={i} cx={s.x} cy={s.y} r={5}
                fill={i===0?'#A78BFA':'white'} stroke="#A78BFA" strokeWidth={1.5}
                style={{ pointerEvents:'none' }} />
            })}

            {/* Botão "Fechar zona" — aparece quando tem 3+ pontos */}
            {polyPoints.length >= 3 && (() => {
              const bw = 130, bh = 28, bx = (viewbox.w - bw) / 2, by = viewbox.h - 42
              return (
                <g style={{ cursor:'pointer' }} onClick={e => {
                  e.stopPropagation()
                  const geo: ZoneGeometry = { type:'polygon', unit:'percent', points: polyPoints }
                  setPolyPoints([]); setPolyCur(null); setPendingGeo(geo); openForm(undefined, geo)
                }}>
                  <rect x={bx} y={by} width={bw} height={bh} rx={8}
                    fill="#7C3AED" stroke="#A78BFA" strokeWidth={1.5} />
                  <text x={bx + bw/2} y={by + 18} textAnchor="middle"
                    fontSize={11} fontWeight="700" fill="white" style={{ userSelect:'none' }}>
                    ✓ Fechar zona ({polyPoints.length} pontos)
                  </text>
                </g>
              )
            })()}

            {/* Botão cancelar */}
            {(() => {
              const bx = viewbox.w - 70, by = viewbox.h - 42
              return (
                <g style={{ cursor:'pointer' }} onClick={e => {
                  e.stopPropagation()
                  setPolyPoints([]); setPolyCur(null)
                }}>
                  <rect x={bx} y={by} width={60} height={28} rx={8}
                    fill="rgba(17,24,39,0.85)" stroke="#6B7280" strokeWidth={1} />
                  <text x={bx+30} y={by+18} textAnchor="middle"
                    fontSize={10} fill="#9CA3AF" style={{ userSelect:'none' }}>✕ Cancelar</text>
                </g>
              )
            })()}

            {/* Instrução */}
            <g pointerEvents="none">
              <rect x={(viewbox.w-200)/2} y={8} width={200} height={20} rx={6}
                fill="rgba(124,58,237,0.8)" />
              <text x={viewbox.w/2} y={21} textAnchor="middle"
                fontSize={9} fill="white" fontWeight="600" style={{ userSelect:'none' }}>
                Clique para adicionar pontos · {polyPoints.length} marcado{polyPoints.length !== 1 ? 's' : ''}
              </text>
            </g>
          </>
        )
      })()}

      {/* Highlight de devices que entrarão na zona em desenho */}
      {previewDeviceIds.size > 0 && (
        <g style={{ pointerEvents: 'none' }}>
          {acDevicesOnFloor
            .filter((d: Device) => previewDeviceIds.has(d.id) && d.position_x != null && d.position_y != null)
            .map((d: Device) => {
              const s = fromPercent(
                Number(d.position_x) / viewbox.w * 100,
                Number(d.position_y) / viewbox.h * 100,
                viewbox,
              )
              return (
                <g key={d.id}>
                  <circle cx={s.x} cy={s.y} r={14}
                    fill="rgba(167,139,250,0.18)" stroke="#A78BFA" strokeWidth={1.5} strokeDasharray="4 2" />
                  <circle cx={s.x} cy={s.y} r={3} fill="#A78BFA" />
                </g>
              )
            })}
          {previewDeviceIds.size > 0 && (
            <g>
              <rect x={4} y={4} width={130} height={18} rx={4} fill="rgba(124,58,237,0.75)" />
              <text x={8} y={16} fontSize={8} fill="white" fontWeight="600" style={{ userSelect:'none' }}>
                {previewDeviceIds.size} equipamento{previewDeviceIds.size !== 1 ? 's' : ''} na zona
              </text>
            </g>
          )}
        </g>
      )}

      {/* Toolbar modo de desenho — só aparece quando não há polígono em andamento */}
      {editMode && !showForm && polyPoints.length === 0 && (
        <g>
          <rect x={viewbox.w-92} y={8} width={84} height={26} rx={6}
            fill="rgba(17,24,39,0.9)" stroke="#4B5563" strokeWidth={1} />
          <text x={viewbox.w-88} y={24} fontSize={8} fill="#9CA3AF">Modo:</text>
          {(['rect','polygon'] as DrawMode[]).map((m,i) => {
            const bx = viewbox.w - 55 + i * 22
            return (
              <g key={m} onClick={() => setDrawMode(m)} style={{ cursor:'pointer' }}>
                <rect x={bx} y={11} width={18} height={18} rx={3}
                  fill={drawMode===m?'#7C3AED':'transparent'}
                  stroke={drawMode===m?'#A78BFA':'#6B7280'} strokeWidth={1} />
                <text x={bx+9} y={23} textAnchor="middle" fontSize={10}
                  fill={drawMode===m?'white':'#9CA3AF'}>{m==='rect'?'□':'⬡'}</text>
              </g>
            )
          })}
        </g>
      )}

      {/* Painel de propriedades */}
      {showForm && (
        <foreignObject x={10} y={10} width={300} height={536}>
          <div className="max-h-[520px] overflow-y-auto rounded-xl border border-violet-500/30 bg-gray-900/96 p-3 shadow-2xl backdrop-blur text-xs text-gray-300 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-white text-sm">{selected ? 'Editar zona' : 'Nova zona'}</span>
              <div className="flex gap-1">
                {selected && (
                  <button onClick={() => { if (window.confirm(`Excluir "${selected.name}"?`)) deleteMutation.mutate(selected.zone_key) }}
                    className="rounded-md p-1 text-red-400 hover:bg-red-900/40">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
                <button onClick={closeForm} className="rounded-md p-1 hover:bg-gray-700"><X className="h-3.5 w-3.5" /></button>
              </div>
            </div>
            {formError && <p className="rounded bg-red-900/40 px-2 py-1 text-red-400">{formError}</p>}
            <input value={formName} onChange={e => setFormName(e.target.value)} placeholder="Nome da zona"
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-violet-500 focus:outline-none" />
            <div>
              <div className="mb-0.5 flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wide text-violet-300">Faixa ideal</span>
                <span className="text-[10px] text-gray-500">temperatura ambiente esperada</span>
              </div>
              <div className="flex gap-2">
                {[['Mín °C', formMin, setFormMin],['Máx °C', formMax, setFormMax]].map(([label, val, setter]) => (
                  <div key={String(label)} className="flex-1">
                    <label className="block mb-0.5 text-gray-400">{String(label)}</label>
                    <input type="number" value={val as number} min={16} max={30}
                      onChange={e => (setter as Function)(Number(e.target.value))}
                      className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-violet-500 focus:outline-none" />
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-0.5 flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wide text-orange-300">Limite operacional</span>
                <span className="text-[10px] text-gray-500">até onde a IA pode mexer no setpoint</span>
              </div>
              <div className="flex gap-2">
                {[['Mín °C', formSpMin, setFormSpMin],['Máx °C', formSpMax, setFormSpMax]].map(([label, val, setter]) => (
                  <div key={`sp-${label}`} className="flex-1">
                    <label className="block mb-0.5 text-gray-400">{String(label)}</label>
                    <input type="number" value={val as number} min={16} max={30}
                      onChange={e => (setter as Function)(Number(e.target.value))}
                      className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-orange-500 focus:outline-none" />
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-md border border-cyan-900/70 bg-cyan-950/20 p-2">
              <label className="mb-2 flex items-center justify-between gap-2">
                <span className="text-[10px] uppercase tracking-wide text-cyan-300">Recuperação térmica</span>
                <input
                  type="checkbox"
                  checked={formRecoveryEnabled}
                  onChange={e => setFormRecoveryEnabled(e.target.checked)}
                  className="h-3.5 w-3.5 accent-cyan-500"
                />
              </label>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="block mb-0.5 text-gray-400">Mín °C</label>
                  <input type="number" value={formRecoveryMin} min={16} max={30}
                    onChange={e => setFormRecoveryMin(Number(e.target.value))}
                    className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-cyan-500 focus:outline-none" />
                </div>
                <div>
                  <label className="block mb-0.5 text-gray-400">Alvo °C</label>
                  <input type="number" value={formRecoveryTarget} min={16} max={30}
                    onChange={e => setFormRecoveryTarget(Number(e.target.value))}
                    className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-cyan-500 focus:outline-none" />
                </div>
                <div>
                  <label className="block mb-0.5 text-gray-400">Min</label>
                  <input type="number" value={formRecoveryDuration} min={5} max={240}
                    onChange={e => setFormRecoveryDuration(Number(e.target.value))}
                    className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-cyan-500 focus:outline-none" />
                </div>
              </div>
            </div>
            <select value={formType} onChange={e => setFormType(e.target.value as any)}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-violet-500 focus:outline-none">
              <option value="ABERTA">Ambiente aberto</option>
              <option value="SALA_FECHADA">Sala fechada</option>
            </select>
            <div className="flex gap-1.5">
              {ZONE_COLORS.map(c => (
                <button key={c} type="button" onClick={() => setFormColor(c)}
                  className={cn('h-5 w-5 rounded-full transition-transform', formColor===c && 'ring-2 ring-white ring-offset-1 ring-offset-gray-900 scale-110')}
                  style={{ background: c }} />
              ))}
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-gray-400">Equipamentos</span>
                <span className="text-[10px] text-violet-400">{formDevices.length} vinculados</span>
              </div>
              <div className="mb-1.5 flex items-center gap-1">
                <div className="relative min-w-0 flex-1">
                  <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-gray-500" />
                  <input
                    value={formSearch}
                    onChange={e => setFormSearch(e.target.value)}
                    placeholder="Buscar AC"
                    className="w-full rounded-md border border-gray-700 bg-gray-800 py-1.5 pl-7 pr-2 text-xs text-white placeholder-gray-500 focus:border-violet-500 focus:outline-none"
                  />
                </div>
                {pendingGeo && !selected && (
                  <button
                    type="button"
                    onClick={() => setFormDevices(devicesInsideGeo(pendingGeo))}
                    className="rounded-md border border-violet-500/50 px-2 py-1.5 text-[10px] font-semibold text-violet-300 hover:bg-violet-900/40"
                  >
                    Dentro
                  </button>
                )}
                {formDevices.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setFormDevices([])}
                    className="rounded-md border border-gray-700 px-2 py-1.5 text-[10px] font-semibold text-gray-400 hover:bg-gray-800"
                  >
                    Limpar
                  </button>
                )}
              </div>
              <div className="max-h-28 overflow-y-auto rounded-md border border-gray-700 bg-gray-800 p-1 space-y-0.5">
                {filteredFormDevices.map((d: Device) => (
                  <label key={d.id} className="flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 hover:bg-gray-700">
                    <input type="checkbox" checked={formDevices.includes(d.id)}
                      onChange={() => toggleDevice(d.id)} className="accent-violet-500 h-3 w-3" />
                    <span className="truncate text-[11px] text-gray-300">{d.name}</span>
                    {d.temperature != null && <span className="ml-auto text-[10px] text-gray-500">{formatTemp(d.temperature)}</span>}
                  </label>
                ))}
                {filteredFormDevices.length === 0 && (
                  <div className="px-2 py-3 text-center text-[11px] text-gray-500">
                    {formSearch.trim() ? 'Nenhum resultado.' : 'Nenhum AC neste andar.'}
                  </div>
                )}
              </div>
            </div>
            <button type="button" disabled={!formName.trim()||formMin>=formMax||formSpMin>=formSpMax||formRecoveryMin>=formRecoveryTarget||formMin<formSpMin||formMax>formSpMax||createMutation.isPending||updateMutation.isPending}
              onClick={handleSave}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed">
              <Check className="h-3.5 w-3.5" />{selected ? 'Salvar' : 'Criar zona'}
            </button>
          </div>
        </foreignObject>
      )}
    </g>
  )
}
