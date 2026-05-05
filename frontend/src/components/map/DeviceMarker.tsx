import { getStatusConfig, formatTemp } from '../../lib/utils'
import type { Device } from '../../types'

interface Props {
  device: Device
  onClick: (device: Device) => void
  scale?: number
}

export default function DeviceMarker({ device, onClick, scale = 1 }: Props) {
  const cfg = getStatusConfig(device.status)
  const size = 24 * scale
  const isCritical = device.status === 'CRÍTICO'
  const isOff = device.status === 'DESLIGADO'
  const noReading = device.status === 'SEM_LEITURA'

  return (
    <g
      transform={`translate(${device.position_x || 0}, ${device.position_y || 0})`}
      onClick={() => onClick(device)}
      style={{ cursor: 'pointer' }}
    >
      {isCritical && (
        <circle r={size * 0.75} fill={cfg.color} opacity={0.15} className="animate-pulse-critical" />
      )}
      <circle
        r={size / 2}
        fill={isOff || noReading ? 'transparent' : cfg.color}
        stroke={cfg.color}
        strokeWidth={2}
        opacity={isOff ? 0.5 : 1}
      />
      {noReading && (
        <text textAnchor="middle" dominantBaseline="middle" fontSize={size * 0.5} fill={cfg.color}>?</text>
      )}
      {isOff && (
        <line x1={-size * 0.35} y1={0} x2={size * 0.35} y2={0} stroke={cfg.color} strokeWidth={2} />
      )}
      <title>{device.name} — {device.status}{device.temperature ? ` — ${formatTemp(device.temperature)}` : ''}</title>
    </g>
  )
}
