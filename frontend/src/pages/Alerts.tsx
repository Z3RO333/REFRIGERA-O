import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, Wrench } from 'lucide-react'
import { alertsApi } from '../api/client'
import { cn, formatRelativeTime, SEVERITY_CONFIG } from '../lib/utils'
import type { Alert } from '../types'

const STATUS_TABS = [
  { label: 'Abertos', value: 'OPEN' },
  { label: 'Reconhecidos', value: 'ACK' },
  { label: 'Resolvidos', value: 'RESOLVED' },
]

export default function Alerts() {
  const navigate = useNavigate()
  const [statusTab, setStatusTab] = useState('OPEN')
  const [severityFilter, setSeverityFilter] = useState('')
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['alerts', statusTab, severityFilter],
    queryFn: () => alertsApi.list({
      status: statusTab,
      severity: severityFilter || undefined,
      per_page: 50,
    }),
    refetchInterval: 20000,
  })

  const ackMutation = useMutation({
    mutationFn: (id: string) => alertsApi.acknowledge(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  })

  const alerts = data?.alerts || []
  const openDevicePanel = (alert: Alert) => navigate(`/devices/${alert.device_id}`)

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-1 gap-1">
          {STATUS_TABS.map(tab => (
            <button
              key={tab.value}
              onClick={() => setStatusTab(tab.value)}
              className={`px-4 py-1.5 rounded-md text-sm transition-colors ${
                statusTab === tab.value ? 'bg-blue-600 text-gray-900 dark:text-white' : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          {['', 'P1', 'P2', 'P3', 'P4'].map(s => (
            <button
              key={s}
              onClick={() => setSeverityFilter(s)}
              className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                severityFilter === s
                  ? 'bg-blue-600 border-blue-600 text-gray-900 dark:text-white'
                  : 'border-gray-300 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {s || 'Todos'}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-xs text-gray-500 dark:border-gray-800">
                <th className="px-4 py-3 text-left">Severidade</th>
                <th className="px-3 py-3 text-left">Loja</th>
                <th className="px-3 py-3 text-left">Zona</th>
                <th className="px-3 py-3 text-left">Equipamento</th>
                <th className="px-3 py-3 text-left">Problema</th>
                <th className="px-3 py-3 text-left">Tempo</th>
                <th className="px-3 py-3 text-left">Responsável</th>
                <th className="px-4 py-3 text-right">Ação</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert: Alert) => (
                <AlertRow
                  key={alert.id}
                  alert={alert}
                  onAck={() => ackMutation.mutate(alert.id)}
                  onResolve={() => openDevicePanel(alert)}
                />
              ))}
              {(isLoading || alerts.length === 0) && (
                <tr>
                  <td colSpan={8} className="py-14 text-center text-sm text-gray-500">
                    {isLoading ? 'Carregando alertas...' : `Nenhum alerta ${statusTab === 'OPEN' ? 'aberto' : 'encontrado'}`}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function AlertRow({ alert, onAck, onResolve }: { alert: Alert; onAck: () => void; onResolve: () => void }) {
  const severity = SEVERITY_CONFIG[alert.severity] || SEVERITY_CONFIG.P4
  const problem = alert.message || alert.alert_type.replace(/_/g, ' ')
  const assignee = alert.acked_by || 'Operação'

  return (
    <tr className={cn('border-b border-gray-200/60 dark:border-gray-800/60', alert.severity === 'P1' && alert.status === 'OPEN' && 'bg-red-500/5')}>
      <td className="px-4 py-3">
        <span className={cn('inline-flex rounded px-2 py-1 text-xs font-bold', severity.bg, severity.color)}>
          {alert.severity}
        </span>
      </td>
      <td className="px-3 py-3 text-gray-900 dark:text-white">{alert.store_name || '—'}</td>
      <td className="px-3 py-3 text-gray-600 dark:text-gray-400">{alert.sector_name || '—'}</td>
      <td className="px-3 py-3">
        <button type="button" onClick={onResolve} className="text-left">
          <div className="font-medium text-gray-900 hover:text-blue-500 dark:text-white">{alert.device_name || 'Equipamento'}</div>
          <div className="font-mono text-xs text-gray-500">{alert.brise_id}</div>
        </button>
      </td>
      <td className="max-w-sm px-3 py-3 text-gray-700 dark:text-gray-300">
        <div className="line-clamp-2">{problem}</div>
        {alert.temperature_at_alert != null && (
          <div className="mt-1 text-xs text-gray-500">
            {alert.temperature_at_alert.toFixed(1)}°C
            {alert.setpoint_at_alert != null && ` / setpoint ${alert.setpoint_at_alert}°C`}
            {alert.delta_at_alert != null && ` / +${alert.delta_at_alert.toFixed(1)}°C`}
          </div>
        )}
      </td>
      <td className="px-3 py-3 text-gray-600 dark:text-gray-400">{formatRelativeTime(alert.opened_at)}</td>
      <td className="px-3 py-3 text-gray-600 dark:text-gray-400">{assignee}</td>
      <td className="px-4 py-3">
        <div className="flex justify-end gap-2">
          {alert.status === 'OPEN' && (
            <button
              type="button"
              onClick={onAck}
              className="inline-flex items-center gap-1 rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-3 py-1.5 text-xs font-medium text-yellow-500 hover:bg-yellow-500/20"
            >
              <Check className="h-3.5 w-3.5" />
              Reconhecer
            </button>
          )}
          <button
            type="button"
            onClick={onResolve}
            className="inline-flex items-center gap-1 rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-1.5 text-xs font-medium text-green-600 hover:bg-green-500/20 dark:text-green-400"
          >
            <Wrench className="h-3.5 w-3.5" />
            Resolver
          </button>
        </div>
      </td>
    </tr>
  )
}
