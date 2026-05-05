import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { historyApi, devicesApi } from '../api/client'
import TemperatureChart from '../components/charts/TemperatureChart'
import ConsumptionChart from '../components/charts/ConsumptionChart'
import { formatTemp } from '../lib/utils'

const PERIOD_OPTIONS = [
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7 dias', hours: 168 },
  { label: '30 dias', hours: 720 },
]

const formatCurrency = (value: number | null | undefined) =>
  value == null
    ? '—'
    : new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value)

export default function History() {
  const { deviceId } = useParams<{ deviceId: string }>()
  const navigate = useNavigate()
  const [hours, setHours] = useState(24)

  const { data: device } = useQuery({
    queryKey: ['device', deviceId],
    queryFn: () => devicesApi.get(deviceId!),
    enabled: !!deviceId,
  })

  const { data: history } = useQuery({
    queryKey: ['history', deviceId, hours],
    queryFn: () => historyApi.readings(deviceId!, hours),
    enabled: !!deviceId,
    refetchInterval: 60000,
  })

  const { data: stats } = useQuery({
    queryKey: ['history-stats', deviceId, hours],
    queryFn: () => historyApi.stats(deviceId!, hours),
    enabled: !!deviceId,
  })

  const readings = history?.readings || []

  return (
    <div className="max-w-5xl space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div>
          <h1 className="font-semibold text-gray-900 dark:text-white">{device?.name || 'Histórico'}</h1>
          <p className="text-xs text-gray-500">{device?.store_name} {device?.sector_name && `• ${device.sector_name}`}</p>
        </div>
        <div className="ml-auto flex bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg p-1 gap-1">
          {PERIOD_OPTIONS.map(opt => (
            <button
              key={opt.hours}
              onClick={() => setHours(opt.hours)}
              className={`px-3 py-1 rounded-md text-sm transition-colors ${
                hours === opt.hours ? 'bg-blue-600 text-gray-900 dark:text-white' : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Temp. Média', value: formatTemp(stats.avg_temp) },
            { label: 'Temp. Máx.', value: formatTemp(stats.max_temp) },
            { label: 'Temp. Mín.', value: formatTemp(stats.min_temp) },
            { label: 'Eficiência Média', value: stats.avg_efficiency ? `${Math.round(stats.avg_efficiency * 100)}%` : '—' },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
              <div className="text-xs text-gray-500 mb-1">{label}</div>
              <div className="text-lg font-bold text-gray-900 dark:text-white">{value}</div>
            </div>
          ))}
        </div>
      )}

      {stats && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Energia Calibrada', value: stats.total_kwh != null ? `${stats.total_kwh.toFixed(1)} kWh` : '—' },
            { label: 'Custo Estimado', value: formatCurrency(stats.estimated_cost) },
            { label: 'Potência Média', value: stats.avg_consumption_kw != null ? `${stats.avg_consumption_kw.toFixed(1)} kW` : '—' },
            { label: 'Pico Estimado', value: stats.peak_consumption_kw != null ? `${stats.peak_consumption_kw.toFixed(1)} kW` : '—' },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
              <div className="text-xs text-gray-500 mb-1">{label}</div>
              <div className="text-lg font-bold text-gray-900 dark:text-white">{value}</div>
            </div>
          ))}
        </div>
      )}

      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">Temperatura × Setpoint</h2>
        <TemperatureChart
          data={readings}
          setpoint={device?.parameters?.setpoint_cool || device?.setpoint_cool}
        />
      </div>

      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">Potência Estimada</h2>
        <ConsumptionChart data={readings} />
      </div>

      {stats && (
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">Distribuição do Status no Período</h2>
          <div className="grid grid-cols-3 gap-4 text-center">
            {[
              { label: 'Horas Normal', value: stats.hours_normal?.toFixed(1), color: '#22C55E' },
              { label: 'Horas Atenção', value: stats.hours_warning?.toFixed(1), color: '#EAB308' },
              { label: 'Horas Crítico', value: stats.hours_critical?.toFixed(1), color: '#EF4444' },
            ].map(({ label, value, color }) => (
              <div key={label} className="space-y-1">
                <div className="text-2xl font-bold" style={{ color }}>{value ?? '—'}</div>
                <div className="text-xs text-gray-500">{label}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
