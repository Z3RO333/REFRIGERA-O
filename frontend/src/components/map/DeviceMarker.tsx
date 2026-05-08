import { getStatusConfig, formatTemp } from '../../lib/utils'
import type { Device } from '../../types'

interface Props {
  device: Device
  onClick: (device: Device) => void
  scale?: number
  showLabel?: boolean
  isDirty?: boolean
  isDragging?: boolean
}

export default function DeviceMarker({ device, onClick, scale = 1, showLabel, isDirty, isDragging }: Props) {
  const cfg = getStatusConfig(device.status)
  const size = 22 * scale
  const isCritical = device.status === 'CRÍTICO'
  const isOff = device.status === 'DESLIGADO'
  const noReading = device.status === 'SEM_LEITURA'
  const isSensor = Boolean(device.is_external_sensor)
  const label = isSensor ? device.name : (device.brise_id || device.name)

  return (
    <g
      transform={`translate(${device.position_x || 0}, ${device.position_y || 0})`}
      onClick={event => {
        event.stopPropagation()
        onClick(device)
      }}
      style={{ cursor: 'pointer' }}
    >
      {isCritical && (
        <circle r={size * 0.95} fill={cfg.color} opacity={0.18} className="animate-pulse-critical" />
      )}
      {isDragging && <circle r={size * 0.95} fill="none" stroke="#2563EB" strokeWidth={3} strokeDasharray="4 3" />}
      {isDirty && <circle r={size * 0.82} fill="none" stroke="#F97316" strokeWidth={2} />}

      {isSensor ? (
        /* Termômetro externo */
        <ThermometerIcon size={size} color={cfg.color} noReading={noReading} />
      ) : (
        /* AC Brise — marcador circular padrão */
        <>
          <circle r={size / 2} fill="#FFFFFF" stroke="rgba(17, 24, 39, 0.28)" strokeWidth={1.5} />
          <circle
            r={size * 0.28}
            fill={isOff || noReading ? 'transparent' : cfg.color}
            stroke={cfg.color}
            strokeWidth={2}
            opacity={isOff ? 0.5 : 1}
          />
          {noReading && (
            <text textAnchor="middle" dominantBaseline="middle" fontSize={size * 0.5} fontWeight={700} fill={cfg.color}>?</text>
          )}
          {isOff && (
            <line x1={-size * 0.25} y1={0} x2={size * 0.25} y2={0} stroke={cfg.color} strokeWidth={2} />
          )}
        </>
      )}

      {showLabel && (
        <g transform={`translate(0, ${size * 0.68})`}>
          <rect x={-26} y={0} width={52} height={15} rx={4} fill="rgba(17,24,39,0.86)" />
          <text x={0} y={10.5} textAnchor="middle" fontSize={8.5} fontWeight={700} fill="#FFFFFF">{label}</text>
        </g>
      )}
      <title>{device.name} — {device.status}{device.temperature ? ` — ${formatTemp(device.temperature)}` : ''}</title>
    </g>
  )
}

function ThermometerIcon({ size, color, noReading }: { size: number; color: string; noReading: boolean }) {
  const s = size * 0.9
  return (
    <g>
      {/* Fundo branco com borda colorida */}
      <rect x={-s / 2} y={-s / 2} width={s} height={s} rx={s * 0.22} fill="#FFFFFF" stroke={color} strokeWidth={1.8} />
      {/* Corpo do termômetro */}
      <rect x={-s * 0.12} y={-s * 0.36} width={s * 0.24} height={s * 0.42} rx={s * 0.12} fill={noReading ? 'transparent' : color} stroke={color} strokeWidth={1.2} opacity={0.85} />
      {/* Bulbo */}
      <circle cy={s * 0.14} r={s * 0.17} fill={noReading ? 'transparent' : color} stroke={color} strokeWidth={1.2} opacity={0.9} />
      {/* "T" para identificar */}
      {noReading && (
        <text textAnchor="middle" dominantBaseline="middle" fontSize={s * 0.44} fontWeight={700} fill={color}>?</text>
      )}
    </g>
  )
}
