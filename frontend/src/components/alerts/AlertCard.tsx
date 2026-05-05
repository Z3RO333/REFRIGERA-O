import { formatRelativeTime, SEVERITY_CONFIG } from '../../lib/utils'
import { Check, Wrench } from 'lucide-react'
import type { Alert } from '../../types'
import { cn } from '../../lib/utils'
import StatusBadge from '../StatusBadge'

interface Props {
  alert: Alert
  onAck: (id: string) => void
  onResolve: (alert: Alert) => void
}

export default function AlertCard({ alert, onAck, onResolve }: Props) {
  const sev = SEVERITY_CONFIG[alert.severity] || SEVERITY_CONFIG.P4
  return (
    <div className={cn(
      'bg-white dark:bg-gray-900 border rounded-xl p-4 space-y-2',
      sev.border,
      alert.severity === 'P1' && alert.status === 'OPEN' && 'animate-blink-alert'
    )}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn('text-xs font-bold px-2 py-0.5 rounded', sev.bg, sev.color)}>{alert.severity}</span>
          <span className="text-sm font-medium text-gray-900 dark:text-white">{alert.device_name}</span>
          <span className="text-xs text-gray-500 font-mono">{alert.brise_id}</span>
        </div>
        <span className="text-xs text-gray-500 shrink-0">{formatRelativeTime(alert.opened_at)}</span>
      </div>
      <div className="text-xs text-gray-600 dark:text-gray-400">
        {alert.store_name} {alert.sector_name && `• ${alert.sector_name}`}
      </div>
      {alert.message && <p className="text-sm text-gray-700 dark:text-gray-300">{alert.message}</p>}
      {alert.temperature_at_alert != null && (
        <div className="flex gap-4 text-xs text-gray-600 dark:text-gray-400">
          <span>Temp: <span className="text-gray-900 dark:text-white">{alert.temperature_at_alert.toFixed(1)}°C</span></span>
          {alert.setpoint_at_alert && <span>Setpoint: <span className="text-gray-900 dark:text-white">{alert.setpoint_at_alert}°C</span></span>}
          {alert.delta_at_alert && <span>Delta: <span className="text-red-400">+{alert.delta_at_alert.toFixed(1)}°C</span></span>}
        </div>
      )}
      {alert.status === 'OPEN' && (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => onAck(alert.id)}
            className="flex items-center gap-1 px-3 py-1.5 bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 rounded-lg text-xs hover:bg-yellow-500/30 transition-colors"
          >
            <Check className="w-3 h-3" /> Reconhecer
          </button>
          <button
            onClick={() => onResolve(alert)}
            className="flex items-center gap-1 px-3 py-1.5 bg-green-500/20 text-green-400 border border-green-500/30 rounded-lg text-xs hover:bg-green-500/30 transition-colors"
          >
            <Wrench className="w-3 h-3" /> Resolver
          </button>
        </div>
      )}
      {alert.status !== 'OPEN' && (
        <StatusBadge status={alert.status === 'ACK' ? 'ATENÇÃO' : 'NORMAL'} size="sm" />
      )}
    </div>
  )
}
