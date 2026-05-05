import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Monitor, AlertTriangle, TrendingUp, Thermometer, Wifi, Zap, Building2 } from 'lucide-react'
import { kpiApi, storesApi, alertsApi, historyApi } from '../api/client'
import KPICard from '../components/KPICard'
import StatusDonut from '../components/charts/StatusDonut'
import AlertCard from '../components/alerts/AlertCard'
import { useAlertStore } from '../store/useAlertStore'
import type { Alert, Store } from '../types'

const formatCurrency = (value: number | null | undefined) =>
  value == null
    ? '—'
    : new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value)

export default function Dashboard() {
  const navigate = useNavigate()
  const { setAlerts } = useAlertStore()
  const [selectedStoreId, setSelectedStoreId] = useState('all')
  const scopedStoreId = selectedStoreId === 'all' ? undefined : selectedStoreId

  const { data: kpis } = useQuery({
    queryKey: ['kpis', scopedStoreId || 'all'],
    queryFn: () => kpiApi.summary(scopedStoreId),
    refetchInterval: 30000,
  })

  const { data: stores } = useQuery({
    queryKey: ['stores'],
    queryFn: storesApi.list,
  })

  const { data: alertsData, refetch: refetchAlerts } = useQuery({
    queryKey: ['alerts', 'open', scopedStoreId || 'all'],
    queryFn: () => alertsApi.list({ status: 'OPEN', per_page: 10, ...(scopedStoreId ? { store_id: scopedStoreId } : {}) }),
    refetchInterval: 30000,
  })

  const { data: consumption } = useQuery({
    queryKey: ['consumption-summary', 24, scopedStoreId || 'all'],
    queryFn: () => historyApi.consumptionSummary(24, 5, scopedStoreId),
    refetchInterval: 60000,
  })

  const { data: allConsumption } = useQuery({
    queryKey: ['consumption-summary-by-store', 24],
    queryFn: () => historyApi.consumptionSummary(24, 100),
    refetchInterval: 60000,
  })

  useEffect(() => {
    if (alertsData?.alerts) setAlerts(alertsData.alerts)
  }, [alertsData, setAlerts])

  const alerts = alertsData?.alerts || []

  const handleAck = async (id: string) => {
    await alertsApi.acknowledge(id)
    refetchAlerts()
  }

  const handleResolve = (alert: Alert) => navigate(`/devices/${alert.device_id}`)
  const consumptionSummary = consumption?.summary
  const topConsumption = consumption?.top_devices || []
  const selectedStore = stores?.find((store: Store) => store.id === selectedStoreId)
  const unitLabel = selectedStore ? selectedStore.name : 'Todas as unidades'
  const storeConsumption = new Map((allConsumption?.by_store || []).map((item: any) => [item.store_id, item]))
  const activeStores = stores?.filter((store: Store) => (store.device_count ?? 0) > 0) || []
  const cdCount = activeStores.filter((store: Store) => store.kind === 'CD').length
  const farmaCount = activeStores.filter((store: Store) => store.kind === 'FARMA').length
  const storeCount = activeStores.filter((store: Store) => store.kind === 'LOJA').length

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">{unitLabel}</h1>
          <p className="text-xs text-gray-500">
            {selectedStore ? `${selectedStore.kind || 'LOJA'} • ${selectedStore.device_count ?? 0} equipamentos` : `${storeCount} lojas • ${farmaCount} farmas • ${cdCount} CDs • ${kpis?.total_devices ?? 0} equipamentos monitorados`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Building2 className="w-4 h-4 text-gray-500" />
          <select
            value={selectedStoreId}
            onChange={event => setSelectedStoreId(event.target.value)}
            className="min-w-64 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-2 text-sm text-gray-900 dark:text-white outline-none focus:border-blue-500"
          >
            <option value="all">Todas as unidades</option>
            {stores?.map((store: Store) => (
              <option key={store.id} value={store.id}>
                {store.kind || 'LOJA'} · {store.name} ({store.device_count ?? 0})
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <KPICard
          title="Dispositivos"
          value={kpis?.total_devices ?? '—'}
          subtitle={`${kpis?.devices_online ?? 0} online`}
          icon={<Monitor className="w-4 h-4" />}
        />
        <KPICard
          title="Normais"
          value={kpis?.devices_normal ?? '—'}
          color="#22C55E"
          icon={<Wifi className="w-4 h-4" />}
        />
        <KPICard
          title="Atenção"
          value={kpis?.devices_warning ?? '—'}
          color="#EAB308"
          icon={<AlertTriangle className="w-4 h-4" />}
        />
        <KPICard
          title="Críticos"
          value={kpis?.devices_critical ?? '—'}
          color="#EF4444"
          icon={<AlertTriangle className="w-4 h-4" />}
        />
        <KPICard
          title="Temp. Média"
          value={kpis?.avg_temperature ? `${kpis.avg_temperature.toFixed(1)}°C` : '—'}
          icon={<Thermometer className="w-4 h-4" />}
        />
        <KPICard
          title="Conformidade"
          value={kpis?.compliance_rate ? `${kpis.compliance_rate}%` : '—'}
          color={kpis?.compliance_rate && kpis.compliance_rate >= 80 ? '#22C55E' : '#EAB308'}
          icon={<TrendingUp className="w-4 h-4" />}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <KPICard
          title="Energia 24h"
          value={consumptionSummary?.total_estimated_kwh != null ? `${consumptionSummary.total_estimated_kwh.toLocaleString('pt-BR')} kWh` : '—'}
          subtitle={`${consumptionSummary?.samples ?? 0} amostras calibradas`}
          color="#0EA5E9"
          icon={<Zap className="w-4 h-4" />}
        />
        <KPICard
          title="Custo 24h"
          value={formatCurrency(consumptionSummary?.estimated_cost)}
          subtitle={`Tarifa R$ ${(consumptionSummary?.energy_price_per_kwh ?? 0.93).toFixed(2).replace('.', ',')}/kWh`}
          color="#16A34A"
          icon={<Zap className="w-4 h-4" />}
        />
        <KPICard
          title="Potência Média"
          value={consumptionSummary?.avg_consumption_kw != null ? `${consumptionSummary.avg_consumption_kw.toFixed(1)} kW` : '—'}
          subtitle="Média calibrada"
          color="#14B8A6"
          icon={<TrendingUp className="w-4 h-4" />}
        />
        <KPICard
          title="Pico de Consumo"
          value={consumptionSummary?.peak_consumption_kw != null ? `${consumptionSummary.peak_consumption_kw.toFixed(1)} kW` : '—'}
          subtitle="Maior potência no período"
          color="#F97316"
          icon={<Zap className="w-4 h-4" />}
        />
      </div>

      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Maiores Consumos nas Últimas 24h</h2>
          <span className="text-xs text-gray-500">kWh e custo calibrados</span>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800 text-xs text-gray-500">
              <th className="text-left px-5 py-3">Equipamento</th>
              <th className="text-left px-3 py-3">Local</th>
              <th className="text-right px-3 py-3">Média</th>
              <th className="text-right px-3 py-3">Energia</th>
              <th className="text-right px-5 py-3">Custo</th>
            </tr>
          </thead>
          <tbody>
            {topConsumption.map((item: any) => (
              <tr
                key={item.device_id}
                className="border-b border-gray-200/50 dark:border-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
                onClick={() => navigate(`/history/${item.device_id}`)}
              >
                <td className="px-5 py-3">
                  <div className="font-medium text-gray-900 dark:text-white">{item.device_name}</div>
                  <div className="text-xs text-gray-500">Brise {item.brise_id}</div>
                </td>
                <td className="px-3 py-3 text-gray-600 dark:text-gray-400">
                  {item.store_name || '—'}{item.sector_name ? ` • ${item.sector_name}` : ''}
                </td>
                <td className="px-3 py-3 text-right text-sky-500 font-medium">
                  {item.avg_consumption_kw != null ? `${item.avg_consumption_kw.toFixed(1)} kW` : '—'}
                </td>
                <td className="px-3 py-3 text-right text-gray-900 dark:text-white font-semibold">
                  {item.total_estimated_kwh != null ? `${item.total_estimated_kwh.toLocaleString('pt-BR')} kWh` : '—'}
                </td>
                <td className="px-5 py-3 text-right text-green-600 dark:text-green-400 font-semibold">
                  {formatCurrency(item.estimated_cost)}
                </td>
              </tr>
            ))}
            {!topConsumption.length && (
              <tr><td colSpan={5} className="text-center py-8 text-gray-500 dark:text-gray-600">Sem dados de consumo no período</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">Distribuição de Status</h2>
          {kpis ? <StatusDonut kpis={kpis} /> : <div className="h-48 flex items-center justify-center text-gray-500 dark:text-gray-600 text-sm">Carregando...</div>}
        </div>

        <div className="lg:col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Lojas</h2>
            <span className="text-xs text-gray-500">{activeStores.length} unidades com equipamentos</span>
          </div>
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-800 text-xs text-gray-500">
                  <th className="text-left px-4 py-3">Unidade</th>
                  <th className="text-center px-3 py-3">Equip.</th>
                  <th className="text-center px-3 py-3">Normal</th>
                  <th className="text-center px-3 py-3">Atenção</th>
                  <th className="text-center px-3 py-3">Crítico</th>
                  <th className="text-center px-3 py-3">S/Leitura</th>
                  <th className="text-right px-3 py-3">Custo 24h</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody>
                {activeStores.map((store: Store) => (
                  <StoreRow
                    key={store.id}
                    store={store}
                    consumption={storeConsumption.get(store.id)}
                    isSelected={selectedStoreId === store.id}
                    onSelect={() => setSelectedStoreId(store.id)}
                    onNavigate={() => navigate(`/stores/${store.id}`)}
                  />
                ))}
                {!activeStores.length && (
                  <tr><td colSpan={8} className="text-center py-8 text-gray-500 dark:text-gray-600">Nenhuma unidade com equipamentos cadastrados</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Alertas Recentes</h2>
          <button onClick={() => navigate('/alerts')} className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
            Ver todos →
          </button>
        </div>
        {alerts.length === 0 && (
          <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-6 text-center text-gray-500 dark:text-gray-600 text-sm">
            Nenhum alerta aberto no momento
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {alerts.slice(0, 6).map((alert: any) => (
            <AlertCard key={alert.id} alert={alert} onAck={handleAck} onResolve={handleResolve} />
          ))}
        </div>
      </div>
    </div>
  )
}

function StoreRow({
  store,
  consumption,
  isSelected,
  onSelect,
  onNavigate,
}: {
  store: Store
  consumption?: any
  isSelected: boolean
  onSelect: () => void
  onNavigate: () => void
}) {
  const { data } = useQuery({
    queryKey: ['store-kpis', store.id],
    queryFn: () => kpiApi.store(store.id),
    refetchInterval: 60000,
  })

  return (
    <tr
      className={`border-b border-gray-200/50 dark:border-gray-800/50 transition-colors ${isSelected ? 'bg-blue-50 dark:bg-blue-950/30' : 'hover:bg-gray-100 dark:hover:bg-gray-800/30'}`}
    >
      <td className="px-4 py-3">
        <div className="font-medium text-gray-900 dark:text-white">{store.name}</div>
        <div className="text-xs text-gray-500">{store.kind || 'LOJA'}{store.city ? ` • ${store.city}` : ''}</div>
      </td>
      <td className="text-center px-3 py-3 text-gray-700 dark:text-gray-300 font-medium">{store.device_count ?? data?.total_devices ?? '—'}</td>
      <td className="text-center px-3 py-3 text-green-400 font-medium">{data?.devices_normal ?? '—'}</td>
      <td className="text-center px-3 py-3 text-yellow-400 font-medium">{data?.devices_warning ?? '—'}</td>
      <td className="text-center px-3 py-3 text-red-400 font-medium">{data?.devices_critical ?? '—'}</td>
      <td className="text-center px-3 py-3 text-gray-600 dark:text-gray-400 font-medium">{data?.devices_no_reading ?? '—'}</td>
      <td className="px-3 py-3 text-right text-green-600 dark:text-green-400 font-semibold">{formatCurrency(consumption?.estimated_cost)}</td>
      <td className="px-4 py-3 text-right">
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onSelect} className="text-xs text-blue-400 hover:text-blue-300">Filtrar</button>
          <button type="button" onClick={onNavigate} className="text-xs text-blue-400 hover:text-blue-300">Abrir</button>
        </div>
      </td>
    </tr>
  )
}
