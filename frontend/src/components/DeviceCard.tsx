import { Link } from 'react-router-dom'
import { Thermometer, Zap } from 'lucide-react'
import type { Device } from '../types'
import StatusBadge from './StatusBadge'
import { formatTemp, formatDelta, formatRelativeTime, formatEfficiency } from '../lib/utils'

interface Props {
  device: Device
}

export default function DeviceCard({ device }: Props) {
  return (
    <Link to={`/devices/${device.id}`} className="block bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700 rounded-xl p-4 transition-colors space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium text-gray-900 dark:text-white text-sm truncate">{device.name}</div>
          {device.sector_name && <div className="text-xs text-gray-500">{device.sector_name}</div>}
        </div>
        <StatusBadge status={device.status} size="sm" />
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="flex flex-col gap-0.5">
          <span className="text-gray-500 flex items-center gap-1"><Thermometer className="w-3 h-3" /> Temp</span>
          <span className="text-gray-900 dark:text-white font-medium">{formatTemp(device.temperature)}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-gray-500">Delta</span>
          <span className={device.delta_temp && device.delta_temp > 4 ? 'text-red-400 font-medium' : 'text-gray-900 dark:text-white font-medium'}>
            {formatDelta(device.delta_temp)}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-gray-500 flex items-center gap-1"><Zap className="w-3 h-3" /> Efic.</span>
          <span className="text-gray-900 dark:text-white font-medium">{formatEfficiency(device.efficiency_score)}</span>
        </div>
      </div>
      <div className="text-xs text-gray-500 dark:text-gray-600">{formatRelativeTime(device.updated_at)}</div>
    </Link>
  )
}
