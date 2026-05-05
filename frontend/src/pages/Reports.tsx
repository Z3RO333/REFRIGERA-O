import { useQuery } from '@tanstack/react-query'
import { CalendarDays, TrendingUp, Zap } from 'lucide-react'
import { historyApi } from '../api/client'
import KPICard from '../components/KPICard'
import { formatCurrency } from '../lib/utils'

export default function Reports() {
  const { data, isLoading } = useQuery({
    queryKey: ['reports-consumption-summary', 24],
    queryFn: () => historyApi.consumptionSummary(24, 100),
    refetchInterval: 60000,
  })

  const summary = data?.summary
  const stores = data?.by_store || []
  const projectedMonth = summary?.estimated_cost != null ? summary.estimated_cost * 30 : null

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Relatórios</h1>
        <p className="text-xs text-gray-500">Consumo calibrado com tarifa de R$ {(summary?.energy_price_per_kwh ?? 0.93).toFixed(2).replace('.', ',')}/kWh</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPICard
          title="Custo 24h"
          value={formatCurrency(summary?.estimated_cost)}
          subtitle={`${summary?.samples ?? 0} amostras`}
          color="#16A34A"
          icon={<Zap className="h-4 w-4" />}
        />
        <KPICard
          title="Projeção mensal"
          value={formatCurrency(projectedMonth)}
          subtitle="baseada nas últimas 24h"
          color="#0EA5E9"
          icon={<CalendarDays className="h-4 w-4" />}
        />
        <KPICard
          title="Energia 24h"
          value={summary?.total_estimated_kwh != null ? `${summary.total_estimated_kwh.toLocaleString('pt-BR')} kWh` : '—'}
          subtitle="kWh estimado"
          color="#14B8A6"
          icon={<Zap className="h-4 w-4" />}
        />
        <KPICard
          title="Potência média"
          value={summary?.avg_consumption_kw != null ? `${summary.avg_consumption_kw.toFixed(1)} kW` : '—'}
          subtitle="média calibrada"
          color="#F97316"
          icon={<TrendingUp className="h-4 w-4" />}
        />
      </div>

      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4 dark:border-gray-800">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Consumo por Unidade</h2>
          <span className="text-xs text-gray-500">últimas 24h</span>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-xs text-gray-500 dark:border-gray-800">
              <th className="px-5 py-3 text-left">Unidade</th>
              <th className="px-3 py-3 text-right">Equip.</th>
              <th className="px-3 py-3 text-right">Potência média</th>
              <th className="px-3 py-3 text-right">Energia</th>
              <th className="px-5 py-3 text-right">Custo</th>
            </tr>
          </thead>
          <tbody>
            {stores.map((store: any) => (
              <tr key={store.store_id || store.store_name} className="border-b border-gray-200/60 dark:border-gray-800/60">
                <td className="px-5 py-3 font-medium text-gray-900 dark:text-white">{store.store_name || 'Sem unidade'}</td>
                <td className="px-3 py-3 text-right text-gray-600 dark:text-gray-400">{store.devices ?? '—'}</td>
                <td className="px-3 py-3 text-right text-gray-900 dark:text-white">{store.avg_consumption_kw != null ? `${store.avg_consumption_kw.toFixed(1)} kW` : '—'}</td>
                <td className="px-3 py-3 text-right text-gray-900 dark:text-white">{store.total_estimated_kwh != null ? `${store.total_estimated_kwh.toLocaleString('pt-BR')} kWh` : '—'}</td>
                <td className="px-5 py-3 text-right font-semibold text-green-600 dark:text-green-400">{formatCurrency(store.estimated_cost)}</td>
              </tr>
            ))}
            {!stores.length && (
              <tr>
                <td colSpan={5} className="py-10 text-center text-sm text-gray-500">
                  {isLoading ? 'Carregando consumo...' : 'Sem dados de consumo no período'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
