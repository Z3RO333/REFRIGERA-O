import { useState, useRef } from 'react'
import type { Device, Sector } from '../../types'
import DeviceMarker from './DeviceMarker'

interface Props {
  devices: Device[]
  sector: Sector | null
  onDeviceClick: (device: Device) => void
  editMode?: boolean
  onDeviceMove?: (deviceId: string, x: number, y: number) => void
}

export default function FloorPlanCanvas({ devices, sector, onDeviceClick, editMode, onDeviceMove }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [dragging, setDragging] = useState<string | null>(null)
  const [viewBox] = useState({ x: 0, y: 0, w: 800, h: 600 })

  const handleMouseDown = (e: React.MouseEvent, deviceId: string) => {
    if (!editMode) return
    e.stopPropagation()
    setDragging(deviceId)
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragging || !svgRef.current || !editMode) return
    const rect = svgRef.current.getBoundingClientRect()
    const scaleX = viewBox.w / rect.width
    const scaleY = viewBox.h / rect.height
    const x = (e.clientX - rect.left) * scaleX + viewBox.x
    const y = (e.clientY - rect.top) * scaleY + viewBox.y
    onDeviceMove?.(dragging, Math.round(x), Math.round(y))
  }

  const handleMouseUp = () => setDragging(null)

  return (
    <div className="w-full h-full relative bg-white dark:bg-gray-900 rounded-xl overflow-hidden border border-gray-200 dark:border-gray-800">
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
      >
        {sector?.floor_plan_url && (
          <image href={sector.floor_plan_url} x={0} y={0} width={viewBox.w} height={viewBox.h} preserveAspectRatio="xMidYMid meet" opacity={0.3} />
        )}
        {devices
          .filter(d => d.position_x != null && d.position_y != null)
          .map(device => (
            <g key={device.id} onMouseDown={e => handleMouseDown(e, device.id)}>
              <DeviceMarker device={device} onClick={onDeviceClick} />
            </g>
          ))}
      </svg>
      {editMode && (
        <div className="absolute top-3 right-3 bg-yellow-500/20 border border-yellow-500/30 text-yellow-400 text-xs px-2 py-1 rounded">
          Modo de edição — arraste para reposicionar
        </div>
      )}
    </div>
  )
}
