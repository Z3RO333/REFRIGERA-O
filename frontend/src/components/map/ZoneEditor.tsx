import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Trash2, X } from 'lucide-react'
import { customZonesApi, storesApi } from '../../api/client'
import { cn, formatTemp } from '../../lib/utils'
import type { CustomZone, Device } from '../../types'

const ZONE_COLORS = [
  '#3B82F6', '#8B5CF6', '#10B981', '#F59E0B',
  '#EF4444', '#EC4899', '#06B6D4', '#84CC16',
]

const STATUS_COLOR: Record<string, string> = {
  COLD: '#2563EB', COMFORT: '#22C55E', WARM: '#EAB308',
  HOT: '#F97316', CRITICAL: '#EF4444', NO_READING: '#6B7280',
}

interface DrawState {
  active: boolean
  startX: number
  startY: number
  curX: number
  curY: number
}

interface Props {
  storeId: string
  floor: number
  editMode: boolean
  svgRef: React.RefObject<SVGSVGElement>
  viewbox: { w: number; h: number }
  transform: { x: number; y: number; scale: number }
  onZoneClick?: (zoneKey: string) => void
}

export default function ZoneEditor({ storeId, floor, editMode, svgRef, viewbox, transform, onZoneClick }: Props) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<CustomZone | null>(null)
  const [drawState, setDrawState] = useState<DrawState>({ active: false, startX: 0, startY: 0, curX: 0, curY: 0 })
  const [showForm, setShowForm] = useState(false)
  const [pendingRect, setPendingRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null)
  // livePos: posição visual durante drag/resize (sem chamar API a cada pixel)
  const [livePos, setLivePos] = useState<Record<string, { x: number; y: number; w: number; h: number }>>({})
  const [dragging, setDragging] = useState<{ zoneKey: string; ox: number; oy: number; w: number; h: number } | null>(null)
  const [resizing, setResizing] = useState<{ zoneKey: string; handle: string; ox: number; oy: number; oz: CustomZone } | null>(null)
  const hasMoved = useRef(false)

  // Form state
  const [formName, setFormName] = useState('')
  const [formMin, setFormMin] = useState(20)
  const [formMax, setFormMax] = useState(24)
  const [formType, setFormType] = useState<'ABERTA' | 'SALA_FECHADA'>('ABERTA')
  const [formColor, setFormColor] = useState(ZONE_COLORS[0])
  const [formDevices, setFormDevices] = useState<string[]>([])
  const [formError, setFormError] = useState<string | null>(null)

  const { data: customZones = [] } = useQuery<CustomZone[]>({
    queryKey: ['custom-zones', storeId],
    queryFn: () => customZonesApi.list(storeId),
    refetchInterval: 30000,
  })

  const { data: storeDevices = [], isLoading: devicesLoading } = useQuery<Device[]>({
    queryKey: ['store-devices', storeId],
    queryFn: () => storesApi.devices(storeId),
    enabled: showForm,
  })

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof customZonesApi.create>[1]) =>
      customZonesApi.create(storeId, data),
    onMutate: () => setFormError(null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['custom-zones', storeId] })
      qc.invalidateQueries({ queryKey: ['zones-automation', storeId] })
      qc.invalidateQueries({ queryKey: ['digital-twin', storeId] })
      closeForm()
    },
    onError: (err: any) => {
      setFormError(err?.response?.data?.detail ?? 'Não foi possível criar a zona.')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ key, data }: { key: string; data: Parameters<typeof customZonesApi.update>[2] }) =>
      customZonesApi.update(storeId, key, data),
    onMutate: () => setFormError(null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['custom-zones', storeId] })
      qc.invalidateQueries({ queryKey: ['zones-automation', storeId] })
      qc.invalidateQueries({ queryKey: ['digital-twin', storeId] })
    },
    onError: (err: any) => {
      setFormError(err?.response?.data?.detail ?? 'Não foi possível salvar a zona.')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (key: string) => customZonesApi.delete(storeId, key),
    onMutate: () => setFormError(null),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['custom-zones', storeId] })
      qc.invalidateQueries({ queryKey: ['zones-automation', storeId] })
      qc.invalidateQueries({ queryKey: ['digital-twin', storeId] })
      setSelected(null)
      closeForm()
    },
    onError: (err: any) => {
      setFormError(err?.response?.data?.detail ?? 'Não foi possível excluir a zona.')
    },
  })

  const floorZones = customZones.filter(z => z.floor === floor)

  // Converte coordenadas da tela para SVG
  // getBoundingClientRect() já inclui o CSS transform (pan/zoom), então a fórmula é simples
  const screenToSVG = useCallback((clientX: number, clientY: number) => {
    const el = svgRef.current
    if (!el) return { x: 0, y: 0 }
    const rect = el.getBoundingClientRect()
    return {
      x: (clientX - rect.left) * viewbox.w / rect.width,
      y: (clientY - rect.top)  * viewbox.h / rect.height,
    }
  }, [svgRef, viewbox])

  const openForm = useCallback((zone?: CustomZone) => {
    if (zone) {
      setFormName(zone.name)
      setFormMin(zone.ideal_min)
      setFormMax(zone.ideal_max)
      setFormType(zone.zone_type as 'ABERTA' | 'SALA_FECHADA')
      setFormColor(zone.color ?? ZONE_COLORS[0])
      setFormDevices(zone.device_ids)
    } else {
      setFormName('')
      setFormMin(20)
      setFormMax(24)
      setFormType('ABERTA')
      setFormColor(ZONE_COLORS[0])
      setFormDevices([])
    }
    setFormError(null)
    setShowForm(true)
  }, [])

  const closeForm = useCallback(() => {
    setShowForm(false)
    setPendingRect(null)
    setSelected(null)
    setFormError(null)
  }, [])

  const handleSave = useCallback(() => {
    const name = formName.trim()
    setFormError(null)
    if (!name) { setFormError('Nome é obrigatório.'); return }
    if (formMin >= formMax) { setFormError('Temperatura mínima deve ser menor que a máxima.'); return }
    if (formDevices.length === 0) { setFormError('Selecione pelo menos um ar-condicionado.'); return }
    if (selected) {
      updateMutation.mutate({
        key: selected.zone_key,
        data: { name, ideal_min: formMin, ideal_max: formMax, zone_type: formType, color: formColor, device_ids: formDevices },
      })
    } else if (pendingRect) {
      createMutation.mutate({
        name, ideal_min: formMin, ideal_max: formMax, zone_type: formType,
        color: formColor, device_ids: formDevices, floor,
        x: pendingRect.x, y: pendingRect.y, w: pendingRect.w, h: pendingRect.h,
      })
    }
  }, [formName, formMin, formMax, formType, formColor, formDevices, selected, pendingRect, floor, createMutation, updateMutation])

  // ── Estado de operação ativo (refs para acesso em listeners globais) ─────────
  const drawStateRef  = useRef(drawState)
  const draggingRef   = useRef(dragging)
  const resizingRef   = useRef(resizing)
  drawStateRef.current  = drawState
  draggingRef.current   = dragging
  resizingRef.current   = resizing

  // ── Listeners globais para mousemove/mouseup ─────────────────────────────────
  // mousemove: atualiza só a posição visual (livePos), sem chamar API
  // mouseup: persiste a posição final no servidor (1 única chamada)
  useEffect(() => {
    if (!editMode) return

    const onMove = (e: MouseEvent) => {
      const ds = drawStateRef.current
      const dr = draggingRef.current
      const rs = resizingRef.current
      const { x, y } = screenToSVG(e.clientX, e.clientY)

      if (ds.active) {
        hasMoved.current = true
        setDrawState(d => ({ ...d, curX: x, curY: y }))
        return
      }

      if (dr) {
        hasMoved.current = true
        setLivePos(p => {
          const cur = p[dr.zoneKey] ?? { x: x - dr.ox, y: y - dr.oy, w: dr.w, h: dr.h }
          return { ...p, [dr.zoneKey]: { ...cur, x: x - dr.ox, y: y - dr.oy, w: cur.w || dr.w, h: cur.h || dr.h } }
        })
        return
      }

      if (rs) {
        hasMoved.current = true
        const oz = rs.oz
        if (oz.x == null || oz.y == null || oz.w == null || oz.h == null) return
        let nx = oz.x, ny = oz.y, nw = oz.w, nh = oz.h
        if (rs.handle.includes('e')) nw = Math.max(20, x - oz.x)
        if (rs.handle.includes('s')) nh = Math.max(20, y - oz.y)
        if (rs.handle.includes('w')) { nw = Math.max(20, oz.x + oz.w - x); nx = x }
        if (rs.handle.includes('n')) { nh = Math.max(20, oz.y + oz.h - y); ny = y }
        setLivePos(p => ({ ...p, [rs.zoneKey]: { x: nx, y: ny, w: nw, h: nh } }))
      }
    }

    const onUp = () => {
      const ds = drawStateRef.current
      const dr = draggingRef.current
      const rs = resizingRef.current

      if (ds.active) {
        const x = Math.min(ds.startX, ds.curX)
        const y = Math.min(ds.startY, ds.curY)
        const w = Math.abs(ds.curX - ds.startX)
        const h = Math.abs(ds.curY - ds.startY)
        setDrawState({ active: false, startX: 0, startY: 0, curX: 0, curY: 0 })
        if (hasMoved.current && w > 15 && h > 15) {
          setPendingRect({ x, y, w, h })
          openForm()
        }
      }

      // Persiste posição final — 1 chamada API só no mouseup
      setLivePos(live => {
        if (dr && live[dr.zoneKey]) {
          const p = live[dr.zoneKey]
          updateMutation.mutate({ key: dr.zoneKey, data: { x: p.x, y: p.y } })
        }
        if (rs && live[rs.zoneKey]) {
          const p = live[rs.zoneKey]
          updateMutation.mutate({ key: rs.zoneKey, data: { x: p.x, y: p.y, w: p.w, h: p.h } })
        }
        return live
      })

      setDragging(null)
      setResizing(null)
    }

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [editMode, screenToSVG, updateMutation, openForm])

  // ── MouseDown na área vazia para iniciar desenho ──────────────────────────────
  const onBgMouseDown = useCallback((e: React.MouseEvent<SVGRectElement>) => {
    if (!editMode || showForm) return
    e.stopPropagation()
    const { x, y } = screenToSVG(e.clientX, e.clientY)
    hasMoved.current = false
    setDrawState({ active: true, startX: x, startY: y, curX: x, curY: y })
  }, [editMode, showForm, screenToSVG])

  const onZoneMouseDown = useCallback((e: React.MouseEvent, zone: CustomZone) => {
    if (!editMode) return
    e.stopPropagation()
    const { x, y } = screenToSVG(e.clientX, e.clientY)
    hasMoved.current = false
    // Inicializa livePos com a posição atual da zona
    setLivePos(p => ({ ...p, [zone.zone_key]: { x: zone.x ?? 0, y: zone.y ?? 0, w: zone.w ?? 100, h: zone.h ?? 60 } }))
    setDragging({ zoneKey: zone.zone_key, ox: x - (zone.x ?? 0), oy: y - (zone.y ?? 0), w: zone.w ?? 100, h: zone.h ?? 60 })
  }, [editMode, screenToSVG])

  const onHandleMouseDown = useCallback((e: React.MouseEvent, zone: CustomZone, handle: string) => {
    e.stopPropagation()
    const { x, y } = screenToSVG(e.clientX, e.clientY)
    // Inicializa livePos com dimensões atuais
    setLivePos(p => ({ ...p, [zone.zone_key]: { x: zone.x ?? 0, y: zone.y ?? 0, w: zone.w ?? 100, h: zone.h ?? 60 } }))
    setResizing({ zoneKey: zone.zone_key, handle, ox: x, oy: y, oz: { ...zone } })
  }, [screenToSVG])

  const handleZoneClick = useCallback((e: React.MouseEvent, zone: CustomZone) => {
    e.stopPropagation()
    if (editMode) {
      setSelected(zone)
      openForm(zone)
    } else {
      onZoneClick?.(zone.zone_key)
    }
  }, [editMode, openForm, onZoneClick])

  // ── Touch equivalents ────────────────────────────────────────────────────────

  const onSVGTouchStart = useCallback((e: React.TouchEvent<SVGSVGElement>) => {
    if (!editMode || showForm || e.touches.length !== 1) return
    if ((e.target as SVGElement).closest('[data-zone]')) return
    e.stopPropagation()
    const t = e.touches[0]
    const { x, y } = screenToSVG(t.clientX, t.clientY)
    hasMoved.current = false
    setDrawState({ active: true, startX: x, startY: y, curX: x, curY: y })
  }, [editMode, showForm, screenToSVG])

  const onSVGTouchMove = useCallback((e: React.TouchEvent<SVGSVGElement>) => {
    if (!editMode || e.touches.length !== 1) return
    e.stopPropagation()
    const t = e.touches[0]
    const { x, y } = screenToSVG(t.clientX, t.clientY)
    if (drawState.active) {
      setDrawState(d => ({ ...d, curX: x, curY: y }))
      hasMoved.current = true
    }
    if (dragging) {
      updateMutation.mutate({ key: dragging.zoneKey, data: { x: x - dragging.ox, y: y - dragging.oy } })
    }
    if (resizing) {
      const oz = resizing.oz
      if (oz.x == null || oz.y == null || oz.w == null || oz.h == null) return
      let nx = oz.x, ny = oz.y, nw = oz.w, nh = oz.h
      if (resizing.handle.includes('e')) nw = Math.max(20, x - oz.x)
      if (resizing.handle.includes('s')) nh = Math.max(20, y - oz.y)
      if (resizing.handle.includes('w')) { nw = Math.max(20, oz.x + oz.w - x); nx = x }
      if (resizing.handle.includes('n')) { nh = Math.max(20, oz.y + oz.h - y); ny = y }
      updateMutation.mutate({ key: resizing.zoneKey, data: { x: nx, y: ny, w: nw, h: nh } })
    }
  }, [editMode, drawState.active, dragging, resizing, screenToSVG, updateMutation])

  const onSVGTouchEnd = useCallback((e: React.TouchEvent<SVGSVGElement>) => {
    if (drawState.active) {
      const x = Math.min(drawState.startX, drawState.curX)
      const y = Math.min(drawState.startY, drawState.curY)
      const w = Math.abs(drawState.curX - drawState.startX)
      const h = Math.abs(drawState.curY - drawState.startY)
      setDrawState({ active: false, startX: 0, startY: 0, curX: 0, curY: 0 })
      if (hasMoved.current && w > 15 && h > 15) {
        setPendingRect({ x, y, w, h })
        openForm()
      }
      e.stopPropagation()
    }
    setDragging(null)
    setResizing(null)
  }, [drawState, openForm])

  const onZoneTouchStart = useCallback((e: React.TouchEvent, zone: CustomZone) => {
    if (!editMode || e.touches.length !== 1) return
    if ((e.target as SVGElement).closest('[data-handle]')) return
    e.stopPropagation()
    const t = e.touches[0]
    const { x, y } = screenToSVG(t.clientX, t.clientY)
    hasMoved.current = false
    setDragging({ zoneKey: zone.zone_key, ox: x - (zone.x ?? 0), oy: y - (zone.y ?? 0), w: zone.w ?? 100, h: zone.h ?? 60 })
  }, [editMode, screenToSVG])

  const onHandleTouchStart = useCallback((e: React.TouchEvent, zone: CustomZone, handle: string) => {
    if (e.touches.length !== 1) return
    e.stopPropagation()
    const t = e.touches[0]
    const { x, y } = screenToSVG(t.clientX, t.clientY)
    setResizing({ zoneKey: zone.zone_key, handle, ox: x, oy: y, oz: { ...zone } })
  }, [screenToSVG])

  const onZoneTap = useCallback((e: React.TouchEvent, zone: CustomZone) => {
    if (!hasMoved.current) {
      e.stopPropagation()
      if (editMode) { setSelected(zone); openForm(zone) }
      else onZoneClick?.(zone.zone_key)
    }
  }, [editMode, openForm, onZoneClick])

  const toggleDevice = (id: string) =>
    setFormDevices(prev => prev.includes(id) ? prev.filter(d => d !== id) : [...prev, id])

  const nonSensorDevices = storeDevices.filter((d: Device) => !d.is_external_sensor)

  return (
    <>
      {/* ── Camada SVG de zonas customizadas ── */}
      <g>
        {/* Rect de captura: necessário para receber mousedown no vazio do SVG */}
        {editMode && (
          <rect
            x={0} y={0} width={viewbox.w} height={viewbox.h}
            fill="transparent"
            style={{ cursor: 'crosshair' }}
            onMouseDown={onBgMouseDown}
            onTouchStart={onSVGTouchStart as any}
            onTouchMove={onSVGTouchMove as any}
            onTouchEnd={onSVGTouchEnd as any}
          />
        )}
        {/* Zonas salvas */}
        {floorZones.filter(z => z.x != null).map(zone => {
          const color = zone.color ?? '#3B82F6'
          const statusColor = STATUS_COLOR[zone.temp_status] ?? color
          const isSelected = selected?.zone_key === zone.zone_key
          const handles = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']
          // Usa livePos durante drag/resize para movimento fluido sem latência de API
          const pos = livePos[zone.zone_key]
          const x = pos?.x ?? zone.x!, y = pos?.y ?? zone.y!
          const w = pos?.w ?? zone.w!, h = pos?.h ?? zone.h!
          return (
            <g key={zone.zone_key} data-zone={zone.zone_key}>
              {/* Corpo da zona */}
              <rect
                x={x} y={y} width={w} height={h}
                fill={`${statusColor}18`}
                stroke={isSelected ? '#A78BFA' : `${statusColor}99`}
                strokeWidth={isSelected ? 2.5 : 1.5}
                strokeDasharray={zone.zone_type === 'SALA_FECHADA' ? '5 3' : undefined}
                rx={4}
                style={{ cursor: editMode ? 'move' : 'pointer', touchAction: 'none' }}
                onMouseDown={e => onZoneMouseDown(e, zone)}
                onClick={e => handleZoneClick(e, zone)}
                onTouchStart={e => onZoneTouchStart(e, zone)}
                onTouchEnd={e => onZoneTap(e, zone)}
              />
              {/* Label */}
              <text x={x + w / 2} y={y + 13} textAnchor="middle" fontSize={9}
                fontWeight="600" fill={statusColor} opacity={0.9}
                style={{ pointerEvents: 'none', userSelect: 'none' }}>
                {zone.name}
              </text>
              {zone.current_temp != null && (
                <text x={x + w / 2} y={y + 24} textAnchor="middle" fontSize={10}
                  fontWeight="700" fill="#F1F5F9" opacity={0.85}
                  style={{ pointerEvents: 'none', userSelect: 'none' }}>
                  {formatTemp(zone.current_temp)}
                </text>
              )}
              {/* Ações rápidas: visíveis em modo edição para evitar esconder excluir no formulário */}
              {editMode && (
                <g>
                  <rect x={x + w - 42} y={y + 4} width={17} height={17} rx={4}
                    fill="rgba(15,23,42,0.88)" stroke="#A78BFA" strokeWidth={1}
                    style={{ cursor: 'pointer' }}
                    onMouseDown={e => e.stopPropagation()}
                    onClick={e => { e.stopPropagation(); setSelected(zone); openForm(zone) }} />
                  <text x={x + w - 33.5} y={y + 16} textAnchor="middle" fontSize={11} fill="#DDD6FE"
                    style={{ pointerEvents: 'none', userSelect: 'none' }}>E</text>
                  <rect x={x + w - 21} y={y + 4} width={17} height={17} rx={4}
                    fill="rgba(127,29,29,0.9)" stroke="#F87171" strokeWidth={1}
                    style={{ cursor: 'pointer' }}
                    onMouseDown={e => e.stopPropagation()}
                    onClick={e => {
                      e.stopPropagation()
                      setSelected(zone)
                      if (confirm(`Excluir a zona "${zone.name}"?`)) deleteMutation.mutate(zone.zone_key)
                    }} />
                  <text x={x + w - 12.5} y={y + 16} textAnchor="middle" fontSize={12} fill="#FEE2E2"
                    style={{ pointerEvents: 'none', userSelect: 'none' }}>x</text>
                </g>
              )}

              {/* Handles de redimensionamento */}
              {editMode && isSelected && handles.map(handle => {
                const hx = handle.includes('e') ? x + w : handle.includes('w') ? x : x + w / 2
                const hy = handle.includes('s') ? y + h : handle.includes('n') ? y : y + h / 2
                return (
                  <rect key={handle} data-handle={handle}
                    x={hx - 5} y={hy - 5} width={10} height={10}
                    rx={2} fill="white" stroke="#A78BFA" strokeWidth={1.5}
                    style={{ cursor: `${handle}-resize`, touchAction: 'none' }}
                    onMouseDown={e => onHandleMouseDown(e, zone, handle)}
                    onTouchStart={e => onHandleTouchStart(e, zone, handle)}
                  />
                )
              })}
            </g>
          )
        })}

        {/* Preview de zona sendo desenhada */}
        {drawState.active && (
          <rect
            x={Math.min(drawState.startX, drawState.curX)}
            y={Math.min(drawState.startY, drawState.curY)}
            width={Math.abs(drawState.curX - drawState.startX)}
            height={Math.abs(drawState.curY - drawState.startY)}
            fill="rgba(139,92,246,0.15)"
            stroke="#A78BFA"
            strokeWidth={1.5}
            strokeDasharray="5 3"
            rx={4}
            style={{ pointerEvents: 'none' }}
          />
        )}
      </g>

      {/* ── Painel de propriedades ── */}
      {showForm && (
        <foreignObject x={10} y={10} width={260} height={420}>
          <div className="rounded-xl border border-violet-500/30 bg-gray-900/95 p-3 shadow-2xl backdrop-blur text-xs text-gray-300">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-semibold text-white text-sm">
                {selected ? 'Editar zona' : 'Nova zona'}
              </span>
              <div className="flex gap-1">
                {selected && (
                  <button onClick={() => deleteMutation.mutate(selected.zone_key)}
                    className="rounded-md p-1 text-red-400 hover:bg-red-900/40">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
                <button onClick={closeForm} className="rounded-md p-1 hover:bg-gray-700">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* Nome */}
            <div className="mb-2">
              <label className="mb-0.5 block text-gray-400">Nome</label>
              <input value={formName} onChange={e => setFormName(e.target.value)}
                placeholder="ex: Contabilidade"
                className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-violet-500 focus:outline-none" />
            </div>

            {/* Faixa de temperatura */}
            <div className="mb-2 flex gap-2">
              <div className="flex-1">
                <label className="mb-0.5 block text-gray-400">Mín (°C)</label>
                <input type="number" value={formMin} min={16} max={30}
                  onChange={e => setFormMin(Number(e.target.value))}
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-violet-500 focus:outline-none" />
              </div>
              <div className="flex-1">
                <label className="mb-0.5 block text-gray-400">Máx (°C)</label>
                <input type="number" value={formMax} min={16} max={30}
                  onChange={e => setFormMax(Number(e.target.value))}
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-violet-500 focus:outline-none" />
              </div>
            </div>

            {/* Tipo */}
            <div className="mb-2">
              <label className="mb-0.5 block text-gray-400">Tipo</label>
              <select value={formType} onChange={e => setFormType(e.target.value as any)}
                className="w-full rounded-md border border-gray-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-violet-500 focus:outline-none">
                <option value="ABERTA">Aberta</option>
                <option value="SALA_FECHADA">Sala fechada</option>
              </select>
            </div>

            {/* Cor */}
            <div className="mb-2">
              <label className="mb-1 block text-gray-400">Cor</label>
              <div className="flex gap-1.5">
                {ZONE_COLORS.map(c => (
                  <button key={c} type="button" onClick={() => setFormColor(c)}
                    className={cn('h-5 w-5 rounded-full transition-transform', formColor === c && 'ring-2 ring-white ring-offset-1 ring-offset-gray-900 scale-110')}
                    style={{ background: c }} />
                ))}
              </div>
            </div>

            {/* Equipamentos */}
            <div className="mb-3">
              <label className="mb-1 block text-gray-400">Equipamentos vinculados</label>
              <div className="max-h-24 overflow-y-auto rounded-md border border-gray-700 bg-gray-800 p-1 space-y-0.5">
                {nonSensorDevices.length === 0
                  ? <div className="py-2 text-center text-gray-500">{devicesLoading ? 'Carregando...' : 'Nenhum ar-condicionado disponível'}</div>
                  : nonSensorDevices.map((d: Device) => (
                    <label key={d.id} className="flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 hover:bg-gray-700">
                      <input type="checkbox"
                        checked={formDevices.includes(d.id)}
                        onChange={() => toggleDevice(d.id)}
                        className="accent-violet-500 h-3 w-3" />
                      <span className="truncate text-[11px] text-gray-300">{d.name}</span>
                      {d.temperature != null && (
                        <span className="ml-auto text-[10px] text-gray-500">{formatTemp(d.temperature)}</span>
                      )}
                    </label>
                  ))
                }
              </div>
            </div>

            {formError && (
              <div className="mb-2 rounded-md border border-red-500/40 bg-red-950/40 px-2 py-1.5 text-[11px] text-red-200">
                {formError}
              </div>
            )}

            {/* Salvar */}
            <button
              type="button"
              disabled={!formName.trim() || formMin >= formMax || formDevices.length === 0 || createMutation.isPending || updateMutation.isPending}
              onClick={handleSave}
              className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed">
              <Check className="h-3.5 w-3.5" />
              {selected ? 'Salvar alterações' : 'Criar zona'}
            </button>
          </div>
        </foreignObject>
      )}

      {/* Botão flutuante para nova zona quando em edit mode e não tem form aberto */}
      {editMode && !showForm && (
        <g>
          <rect x={10} y={10} width={130} height={22} rx={6}
            fill="rgba(139,92,246,0.25)" stroke="#A78BFA" strokeWidth={1} />
          <text x={75} y={24} textAnchor="middle" fontSize={9} fill="#C4B5FD" fontWeight="600"
            style={{ pointerEvents: 'none', userSelect: 'none' }}>
            ✏ arraste para criar zona
          </text>
        </g>
      )}
    </>
  )
}
