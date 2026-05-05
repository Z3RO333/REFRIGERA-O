import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { alertsApi } from '../api/client'
import AlertCard from '../components/alerts/AlertCard'
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

      {isLoading ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-600 text-sm">Carregando alertas...</div>
      ) : alerts.length === 0 ? (
        <div className="text-center py-16 text-gray-500 dark:text-gray-600 text-sm">Nenhum alerta {statusTab === 'OPEN' ? 'aberto' : 'encontrado'}</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {alerts.map((alert: any) => (
            <AlertCard
              key={alert.id}
              alert={alert}
              onAck={ackMutation.mutate}
              onResolve={openDevicePanel}
            />
          ))}
        </div>
      )}
    </div>
  )
}
