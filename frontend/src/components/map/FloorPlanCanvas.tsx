import { useState, useRef } from 'react'
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
  const svgRef = useRef<SVGSVGElement>(null)
  const [dragging, setDragging] = useState<string | null>(null)
  const [didDrag, setDidDrag] = useState(false)
  const [viewBox] = useState({ x: 0, y: 0, w: 800, h: 556 })
  const dirtySet = new Set(dirtyDeviceIds)

  const clientToSvgPoint = (e: React.MouseEvent) => {
    if (!svgRef.current) return null
    const point = svgRef.current.createSVGPoint()
    point.x = e.clientX
    point.y = e.clientY
    const matrix = svgRef.current.getScreenCTM()
    if (!matrix) return null
    return point.matrixTransform(matrix.inverse())
  }

  const handleMouseDown = (e: React.MouseEvent, deviceId: string) => {
    if (!editMode) return
    e.stopPropagation()
    setDragging(deviceId)
    setDidDrag(false)
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragging || !svgRef.current || !editMode) return
    const point = clientToSvgPoint(e)
    if (!point) return
    const x = Math.max(viewBox.x, Math.min(viewBox.x + viewBox.w, point.x))
    const y = Math.max(viewBox.y, Math.min(viewBox.y + viewBox.h, point.y))
    setDidDrag(true)
    onDeviceMove?.(dragging, Math.round(x), Math.round(y))
  }

  const handleMouseUp = () => {
    setDragging(null)
    setTimeout(() => setDidDrag(false), 0)
  }

  const handleCanvasClick = (e: React.MouseEvent) => {
    if (!editMode || !placingDeviceName || dragging || didDrag) return
    const point = clientToSvgPoint(e)
    if (!point) return
    const x = Math.max(viewBox.x, Math.min(viewBox.x + viewBox.w, point.x))
    const y = Math.max(viewBox.y, Math.min(viewBox.y + viewBox.h, point.y))
    onCanvasPlace?.(Math.round(x), Math.round(y))
  }

  return (
    <div className="w-full h-full relative rounded-xl overflow-hidden border border-gray-200 bg-gray-100 shadow-inner dark:border-gray-800 dark:bg-gray-950">
      {!sector?.floor_plan_url && (
        <div className="absolute inset-0 flex items-center justify-center text-gray-500 dark:text-gray-600 text-sm">
          Nenhuma planta cadastrada para este setor
        </div>
      )}
      <svg
        ref={svgRef}
        viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
        className="w-full h-full"
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onClick={handleCanvasClick}
        style={{ cursor: editMode && placingDeviceName ? 'crosshair' : undefined }}
      >
        <defs>
          <filter id="plan-shadow" x="-8%" y="-8%" width="116%" height="116%">
            <feDropShadow dx="0" dy="2" stdDeviation="4" floodOpacity="0.18" />
          </filter>
          <pattern id="edit-grid" width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" fill="none" stroke="rgba(37,99,235,0.18)" strokeWidth="0.8" />
          </pattern>
        </defs>
        <rect x={viewBox.x} y={viewBox.y} width={viewBox.w} height={viewBox.h} fill="#EEF2F7" />
        {sector?.floor_plan_url && (
          <image href={sector.floor_plan_url} x={0} y={0} width={viewBox.w} height={viewBox.h} preserveAspectRatio="xMidYMid meet" opacity={1} filter="url(#plan-shadow)" />
        )}
        {editMode && <rect x={viewBox.x} y={viewBox.y} width={viewBox.w} height={viewBox.h} fill="url(#edit-grid)" pointerEvents="none" />}
        {devices
          .filter(d => d.position_x != null && d.position_y != null)
          .map(device => (
            <g key={device.id} onMouseDown={e => handleMouseDown(e, device.id)}>
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
        <div className="absolute top-3 right-3 rounded-lg border border-blue-500/30 bg-white/95 px-3 py-2 text-xs font-medium text-blue-700 shadow-sm dark:bg-gray-900/95 dark:text-blue-300">
          {placingDeviceName ? `Clique na planta para colocar: ${placingDeviceName}` : 'Arraste os marcadores'}
        </div>
      )}
    </div>
  )
}
