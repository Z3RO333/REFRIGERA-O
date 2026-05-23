/**
 * ZoneEditor — Editor visual de zonas térmicas no mapa SVG.
 * Geometria salva em % da planta (unit: "percent"), independente de resolução.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Trash2, X } from 'lucide-react'
import { customZonesApi, storesApi } from '../../api/client'
import { cn, formatTemp } from '../../lib/utils'
import type { CustomZone, Device, ZoneGeometry } from '../../types'

const ZONE_COLORS = ['#3B82F6','#8B5CF6','#10B981','#F59E0B','#EF4444','#EC4899','#06B6D4','#84CC16']
const STATUS_COLOR: Record<string,string> = { COLD:'#2563EB', COMFORT:'#22C55E', WARM:'#EAB308', HOT:'#F97316', CRITICAL:'#EF4444', NO_READING:'#6B7280' }

type DrawMode = 'rect' | 'polygon'

interface Props {
  storeId: string; floor: number; editMode: boolean
  svgRef: React.RefObject<SVGSVGElement>
  viewbox: { w: number; h: number }
  transform: { x: number; y: number; scale: number }
  onZoneClick?: (zoneKey: string) => void
}

function toPercent(svgX: number, svgY: number, vb: { w: number; h: number }) {
  return { x: Math.round(svgX / vb.w * 10000) / 100, y: Math.round(svgY / vb.h * 10000) / 100 }
}
function fromPercent(px: number, py: number, vb: { w: number; h: number }) {
  return { x: px / 100 * vb.w, y: py / 100 * vb.h }
}
function pointInPolygon(px: number, py: number, pts: { x: number; y: number }[]) {
  let inside = false
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const { x: xi, y: yi } = pts[i], { x: xj, y: yj } = pts[j]
    if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) inside = !inside
  }
  return inside
}
function geoBounds(pts: { x: number; y: number }[]) {
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y)
  return { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) }
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
  const [rectStart, setRectStart] = useState<{ x: number; y: number } | null>(null)
  const [rectCur, setRectCur] = useState<{ x: number; y: number } | null>(null)
  const [polyPoints, setPolyPoints] = useState<{ x: number; y: number }[]>([])
  const [polyCur, setPolyCur] = useState<{ x: number; y: number } | null>(null)
  const [livePos, setLivePos] = useState<Record<string, { x: number; y: number }[]>>({})
  const livePosRef = useRef(livePos)  // ref para evitar stale closure no useEffect
  livePosRef.current = livePos
  const [dragging, setDragging] = useState<{ zoneKey: string; startPts: { x: number; y: number }[]; startMouse: { x: number; y: number } } | null>(null)
  const draggingRef = useRef(dragging)
  draggingRef.current = dragging
  const hasMoved = useRef(false)

  const [formName, setFormName] = useState('')
  const [formMin, setFormMin] = useState(20)
  const [formMax, setFormMax] = useState(24)
  const [formType, setFormType] = useState<'ABERTA'|'SALA_FECHADA'>('ABERTA')
  const [formColor, setFormColor] = useState(ZONE_COLORS[0])
  const [formDevices, setFormDevices] = useState<string[]>([])
  const [formError, setFormError] = useState<string|null>(null)

  const { data: customZones = [] } = useQuery<CustomZone[]>({
    queryKey: ['custom-zones', storeId],
    queryFn: () => customZonesApi.list(storeId),
    refetchInterval: 30000,
  })
  const { data: storeDevices = [] } = useQuery<Device[]>({
    queryKey: ['store-devices', storeId],
    queryFn: () => storesApi.devices(storeId),
    enabled: showForm,
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
      if (d.position_x == null || d.position_y == null) return false
      const p = toPercent(Number(d.position_x), Number(d.position_y), viewbox)
      return pointInPolygon(p.x, p.y, geo.points)
    }).map((d: Device) => d.id)
  , [storeDevices, viewbox])

  const openForm = useCallback((zone?: CustomZone, geo?: ZoneGeometry) => {
    if (zone) {
      setFormName(zone.name); setFormMin(zone.ideal_min); setFormMax(zone.ideal_max)
      setFormType(zone.zone_type as any); setFormColor(zone.color ?? ZONE_COLORS[0])
      setFormDevices(zone.device_ids)
    } else {
      setFormName(''); setFormMin(20); setFormMax(24); setFormType('ABERTA')
      setFormColor(ZONE_COLORS[0])
      setFormDevices(geo ? devicesInsideGeo(geo) : [])
    }
    setFormError(null); setShowForm(true)
  }, [devicesInsideGeo])

  const closeForm = useCallback(() => {
    setShowForm(false); setPendingGeo(null); setSelected(null); setFormError(null)
  }, [])

  const handleSave = useCallback(() => {
    const name = formName.trim()
    if (!name) { setFormError('Nome obrigatório'); return }
    if (formMin >= formMax) { setFormError('Mín deve ser < Máx'); return }
    setFormError(null)
    if (selected) {
      updateMutation.mutate({ key: selected.zone_key,
        data: { name, ideal_min: formMin, ideal_max: formMax, zone_type: formType, color: formColor, device_ids: formDevices } })
    } else if (pendingGeo) {
      createMutation.mutate({ name, ideal_min: formMin, ideal_max: formMax, zone_type: formType,
        color: formColor, device_ids: formDevices, floor, geometry: pendingGeo })
    }
  }, [formName, formMin, formMax, formType, formColor, formDevices, selected, pendingGeo, floor, createMutation, updateMutation])

  // Listeners globais
  useEffect(() => {
    if (!editMode) return
    const onMove = (e: MouseEvent) => {
      const pct = screenToPct(e.clientX, e.clientY)
      if (rectStart) setRectCur(pct)
      if (polyPoints.length > 0) setPolyCur(pct)
      const dr = draggingRef.current
      if (dr) {
        hasMoved.current = true
        const dx = pct.x - dr.startMouse.x, dy = pct.y - dr.startMouse.y
        setLivePos(lp => ({ ...lp, [dr.zoneKey]: dr.startPts.map(p => ({ x: p.x + dx, y: p.y + dy })) }))
      }
    }
    const onUp = (e: MouseEvent) => {
      const dr = draggingRef.current
      if (dr) {
        const live = livePosRef.current[dr.zoneKey]  // usa ref para evitar stale closure
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
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
  }, [editMode, rectStart, polyPoints, livePos, screenToPct, updateMutation, openForm])

  const onBgMouseDown = useCallback((e: React.MouseEvent<SVGRectElement>) => {
    if (!editMode || showForm || dragging || drawMode !== 'rect') return
    e.stopPropagation()
    const pct = screenToPct(e.clientX, e.clientY)
    setRectStart(pct); setRectCur(pct); hasMoved.current = false
  }, [editMode, showForm, dragging, drawMode, screenToPct])

  const onBgClick = useCallback((e: React.MouseEvent<SVGRectElement>) => {
    if (!editMode || showForm || drawMode !== 'polygon') return
    e.stopPropagation()
    setPolyPoints(prev => [...prev, screenToPct(e.clientX, e.clientY)])
  }, [editMode, showForm, drawMode, screenToPct])

  const onBgDblClick = useCallback((e: React.MouseEvent) => {
    if (!editMode || drawMode !== 'polygon' || polyPoints.length < 3) return
    e.stopPropagation()
    const geo: ZoneGeometry = { type:'polygon', unit:'percent', points: polyPoints }
    setPolyPoints([]); setPolyCur(null); setPendingGeo(geo); openForm(undefined, geo)
  }, [editMode, drawMode, polyPoints, openForm])

  const onZoneMouseDown = useCallback((e: React.MouseEvent, zone: CustomZone) => {
    if (!editMode || !zone.geometry) return
    e.stopPropagation()
    hasMoved.current = false
    const pct = screenToPct(e.clientX, e.clientY)
    setLivePos(lp => ({ ...lp, [zone.zone_key]: zone.geometry!.points }))
    setDragging({ zoneKey: zone.zone_key, startPts: zone.geometry.points, startMouse: pct })
  }, [editMode, screenToPct])

  const handleZoneClick = useCallback((e: React.MouseEvent, zone: CustomZone) => {
    e.stopPropagation()
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
          onMouseDown={onBgMouseDown} onClick={onBgClick} />
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
              onMouseDown={e => onZoneMouseDown(e, zone)}
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
        <foreignObject x={10} y={10} width={265} height={470}>
          <div className="rounded-xl border border-violet-500/30 bg-gray-900/96 p-3 shadow-2xl backdrop-blur text-xs text-gray-300 space-y-2">
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
              <div className="max-h-28 overflow-y-auto rounded-md border border-gray-700 bg-gray-800 p-1 space-y-0.5">
                {storeDevices.filter((d: Device) => !d.is_external_sensor).map((d: Device) => (
                  <label key={d.id} className="flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 hover:bg-gray-700">
                    <input type="checkbox" checked={formDevices.includes(d.id)}
                      onChange={() => toggleDevice(d.id)} className="accent-violet-500 h-3 w-3" />
                    <span className="truncate text-[11px] text-gray-300">{d.name}</span>
                    {d.temperature != null && <span className="ml-auto text-[10px] text-gray-500">{formatTemp(d.temperature)}</span>}
                  </label>
                ))}
              </div>
            </div>
            <button type="button" disabled={!formName.trim()||formMin>=formMax||createMutation.isPending||updateMutation.isPending}
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
