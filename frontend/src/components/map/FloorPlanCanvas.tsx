import { useState, useRef, useEffect, useCallback } from 'react'
import { Minus, Plus, RotateCcw } from 'lucide-react'
import type { Device, Sector } from '../../types'
import DeviceMarker from './DeviceMarker'

interface Props {
  devices: Device[]
  sector: Sector | null
  onDeviceClick: (device: Device) => void
  editMode?: boolean
  onDeviceMove?: (deviceId: string, x: number, y: number) => void
  onCanvasPlace?: (x: number, y: number) => void
  placingDeviceName?: string | null
  dirtyDeviceIds?: string[]
}

const VIEWBOX_W = 800
const VIEWBOX_H = 556
const MIN_SCALE = 0.25
const MAX_SCALE = 10

export default function FloorPlanCanvas({
  devices,
  sector,
  onDeviceClick,
  editMode,
  onDeviceMove,
  onCanvasPlace,
  placingDeviceName,
  dirtyDeviceIds = [],
}: Props) {
  const svgRef       = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const dirtySet     = new Set(dirtyDeviceIds)

  // ── Device drag state ──────────────────────────────────────────────────────
  const [dragging, setDragging] = useState<string | null>(null)
  const [didDrag,  setDidDrag]  = useState(false)

  // ── Map pan/zoom state ──────────────────────────────────────────────────────
  const [transform, setTransformState] = useState({ x: 0, y: 0, scale: 1 })
  const transformRef = useRef(transform)
  const setTransform = useCallback((up: typeof transform | ((t: typeof transform) => typeof transform)) => {
    setTransformState(prev => {
      const next = typeof up === 'function' ? up(prev) : up
      transformRef.current = next
      return next
    })
  }, [])

  const isPanning  = useRef(false)
  const hasPanned  = useRef(false)
  const panStart   = useRef({ x: 0, y: 0 })
  const pinchDist  = useRef(0)

  // ── Helpers ────────────────────────────────────────────────────────────────
  const clamp = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))

  const zoomAt = useCallback((factor: number, cx: number, cy: number) => {
    setTransform(t => {
      const ns = clamp(t.scale * factor)
      const r  = ns / t.scale
      return { x: cx - (cx - t.x) * r, y: cy - (cy - t.y) * r, scale: ns }
    })
  }, [setTransform])

  const zoom = useCallback((factor: number) => {
    const el = containerRef.current
    if (!el) return
    const { width, height } = el.getBoundingClientRect()
    zoomAt(factor, width / 2, height / 2)
  }, [zoomAt])

  const resetView = useCallback(() => setTransform({ x: 0, y: 0, scale: 1 }), [setTransform])

  // Wheel zoom
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

  // ── SVG coordinate mapping (works with CSS transform via getScreenCTM) ─────
  const clientToSvg = (clientX: number, clientY: number) => {
    if (!svgRef.current) return null
    const pt = svgRef.current.createSVGPoint()
    pt.x = clientX
    pt.y = clientY
    const m = svgRef.current.getScreenCTM()
    if (!m) return null
    return pt.matrixTransform(m.inverse())
  }

  // ── Pointer handlers (mouse + touch + stylus unificados) ──────────────────
  const activePointers = useRef<Map<number, { x: number; y: number }>>(new Map())

  const handleDevicePointerDown = useCallback((e: React.PointerEvent, deviceId: string) => {
    if (!editMode) return
    e.stopPropagation()
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    setDragging(deviceId)
    setDidDrag(false)
  }, [editMode])

  const handleSvgPointerDown = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    if (dragging) return
    activePointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (activePointers.current.size === 1) {
      // single pointer → pan
      isPanning.current = true
      hasPanned.current = false
      const t = transformRef.current
      panStart.current = { x: e.clientX - t.x, y: e.clientY - t.y }
    } else {
      // second pointer → pinch — cancel pan
      isPanning.current = false
      const pts = [...activePointers.current.values()]
      const dx = pts[0].x - pts[1].x
      const dy = pts[0].y - pts[1].y
      pinchDist.current = Math.sqrt(dx * dx + dy * dy)
    }
  }, [dragging])

  const handleSvgPointerMove = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    activePointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })

    if (dragging && editMode) {
      const pt = clientToSvg(e.clientX, e.clientY)
      if (!pt) return
      const x = Math.max(0, Math.min(VIEWBOX_W, pt.x))
      const y = Math.max(0, Math.min(VIEWBOX_H, pt.y))
      setDidDrag(true)
      onDeviceMove?.(dragging, Math.round(x), Math.round(y))
    } else if (activePointers.current.size === 2) {
      // pinch zoom
      const pts = [...activePointers.current.values()]
      const dx = pts[0].x - pts[1].x
      const dy = pts[0].y - pts[1].y
      const dist = Math.sqrt(dx * dx + dy * dy)
      if (pinchDist.current > 0) {
        const el = containerRef.current
        if (el) {
          const r = el.getBoundingClientRect()
          const mid = {
            x: (pts[0].x + pts[1].x) / 2 - r.left,
            y: (pts[0].y + pts[1].y) / 2 - r.top,
          }
          zoomAt(dist / pinchDist.current, mid.x, mid.y)
        }
      }
      pinchDist.current = dist
      hasPanned.current = true
    } else if (isPanning.current) {
      const nx = e.clientX - panStart.current.x
      const ny = e.clientY - panStart.current.y
      if (Math.abs(nx - transformRef.current.x) + Math.abs(ny - transformRef.current.y) > 3)
        hasPanned.current = true
      setTransform(t => ({ ...t, x: nx, y: ny }))
    }
  }, [dragging, editMode, onDeviceMove, setTransform, zoomAt])

  const handleSvgPointerUp = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    activePointers.current.delete(e.pointerId)
    if (activePointers.current.size === 0) {
      setDragging(null)
      isPanning.current = false
      pinchDist.current = 0
      setTimeout(() => setDidDrag(false), 0)
    }
  }, [])

  const handleCanvasClick = useCallback((e: React.MouseEvent) => {
    if (hasPanned.current) { hasPanned.current = false; return }
    if (!editMode || !placingDeviceName || dragging || didDrag) return
    const pt = clientToSvg(e.clientX, e.clientY)
    if (!pt) return
    const x = Math.max(0, Math.min(VIEWBOX_W, pt.x))
    const y = Math.max(0, Math.min(VIEWBOX_H, pt.y))
    onCanvasPlace?.(Math.round(x), Math.round(y))
  }, [editMode, placingDeviceName, dragging, didDrag, onCanvasPlace])

  const handleDoubleClick = useCallback((e: React.MouseEvent) => {
    const el = containerRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    zoomAt(2, e.clientX - r.left, e.clientY - r.top)
  }, [zoomAt])

  const isDraggingDevice = !!dragging
  const cursorStyle = editMode && placingDeviceName ? 'crosshair' : dragging ? 'grabbing' : 'grab'

  return (
    <div
      ref={containerRef}
      className="w-full h-full relative rounded-xl overflow-hidden border border-gray-200 bg-gray-100 shadow-inner dark:border-gray-800 dark:bg-gray-950"
      style={{ touchAction: 'none' }}
    >
      {!sector?.floor_plan_url && (
        <div className="absolute inset-0 flex items-center justify-center text-gray-500 dark:text-gray-600 text-sm z-10">
          Nenhuma planta cadastrada para este setor
        </div>
      )}

      {/* Controles de zoom */}
      <div className="absolute right-2 top-2 z-20 flex flex-col gap-1">
        <button
          type="button"
          onClick={e => { e.stopPropagation(); zoom(1.25) }}
          className="flex h-7 w-7 items-center justify-center rounded-lg bg-gray-800/80 text-gray-300 backdrop-blur hover:bg-gray-700 hover:text-white"
          title="Ampliar"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={e => { e.stopPropagation(); resetView() }}
          className="flex h-7 w-7 items-center justify-center rounded-lg bg-gray-800/80 text-gray-300 backdrop-blur hover:bg-gray-700 hover:text-white"
          title="Resetar zoom"
        >
          <RotateCcw className="h-3 w-3" />
        </button>
        <button
          type="button"
          onClick={e => { e.stopPropagation(); zoom(0.8) }}
          className="flex h-7 w-7 items-center justify-center rounded-lg bg-gray-800/80 text-gray-300 backdrop-blur hover:bg-gray-700 hover:text-white"
          title="Reduzir"
        >
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
        viewBox={`0 0 ${VIEWBOX_W} ${VIEWBOX_H}`}
        className="w-full h-full"
        style={{
          transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
          transformOrigin: '0 0',
          cursor: cursorStyle,
          willChange: isDraggingDevice ? 'auto' : 'transform',
        }}
        onPointerDown={handleSvgPointerDown}
        onPointerMove={handleSvgPointerMove}
        onPointerUp={handleSvgPointerUp}
        onPointerCancel={handleSvgPointerUp}
        onClick={handleCanvasClick}
        onDoubleClick={handleDoubleClick}
      >
        <defs>
          <filter id="plan-shadow" x="-8%" y="-8%" width="116%" height="116%">
            <feDropShadow dx="0" dy="2" stdDeviation="4" floodOpacity="0.18" />
          </filter>
          <pattern id="edit-grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(37,99,235,0.18)" strokeWidth="0.8" />
          </pattern>
        </defs>

        <rect x={0} y={0} width={VIEWBOX_W} height={VIEWBOX_H} fill="#EEF2F7" />
        {sector?.floor_plan_url && (
          <image
            href={sector.floor_plan_url}
            x={0} y={0}
            width={VIEWBOX_W} height={VIEWBOX_H}
            preserveAspectRatio="xMidYMid meet"
            opacity={1}
            filter="url(#plan-shadow)"
          />
        )}
        {editMode && (
          <rect x={0} y={0} width={VIEWBOX_W} height={VIEWBOX_H} fill="url(#edit-grid)" pointerEvents="none" />
        )}

        {devices
          .filter(d => d.position_x != null && d.position_y != null)
          .map(device => (
            <g key={device.id} onPointerDown={e => handleDevicePointerDown(e, device.id)}>
              <DeviceMarker
                device={device}
                onClick={onDeviceClick}
                showLabel={editMode || dirtySet.has(device.id)}
                isDirty={dirtySet.has(device.id)}
                isDragging={dragging === device.id}
              />
            </g>
          ))}
      </svg>

      {editMode && (
        <div className="absolute top-3 right-12 rounded-lg border border-blue-500/30 bg-white/95 px-3 py-2 text-xs font-medium text-blue-700 shadow-sm dark:bg-gray-900/95 dark:text-blue-300">
          {placingDeviceName
            ? `Clique na planta para colocar: ${placingDeviceName}`
            : 'Arraste os marcadores · scroll para zoom'}
        </div>
      )}
    </div>
  )
}
