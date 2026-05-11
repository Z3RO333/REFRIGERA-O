import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { ArrowLeft, RefreshCw, History, Minus, Plus, Power, PowerOff, CalendarDays } from 'lucide-react'
import { devicesApi } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import { formatTemp, formatDelta, formatRelativeTime, formatEfficiency } from '../lib/utils'
import type { BriseSchedule, DeviceControlAction, DeviceParameters } from '../types'

const MODE_DEVICE = ['Desligado', 'Manual', 'Absoluto', 'Eco']
const MODE_AC = ['Refrigeração', 'Aquecimento', 'Automático', 'Ventilação']
const FAN_SPEED = ['', 'Baixa', 'Média', 'Alta']
const SETPOINT_MIN = 18
const SETPOINT_MAX = 28

export default function DeviceDetail() {
  const { deviceId } = useParams<{ deviceId: string }>()
  const navigate = useNavigate()
  const [editParams, setEditParams] = useState(false)
  const [params, setParams] = useState<any>(null)
  const [controlNotice, setControlNotice] = useState('')
  const [editBtu, setEditBtu] = useState(false)
  const [btuValue, setBtuValue] = useState('')

  const { data: device, refetch } = useQuery({
    queryKey: ['device', deviceId],
    queryFn: () => devicesApi.get(deviceId!),
    enabled: !!deviceId,
  })

  const { data: briseSchedules } = useQuery<BriseSchedule[]>({
    queryKey: ['brise-schedules', deviceId],
    queryFn: () => devicesApi.briseSchedules(deviceId!),
    enabled: !!deviceId && !device?.is_external_sensor,
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (device?.parameters && !editParams) setParams(device.parameters)
  }, [device?.parameters, editParams])

  useEffect(() => {
    if (device?.btu && !editBtu) setBtuValue(String(device.btu))
  }, [device?.btu, editBtu])

  const syncMutation = useMutation({
    mutationFn: () => devicesApi.sync(deviceId!),
    onSuccess: () => setTimeout(refetch, 2000),
    onError: () => {
      setControlNotice('Falha ao sincronizar dispositivo')
      setTimeout(() => setControlNotice(''), 3000)
    },
  })

  const updateParams = useMutation({
    mutationFn: (p: object) => devicesApi.updateParams(deviceId!, p),
    onSuccess: () => { setEditParams(false); refetch() },
    onError: () => {
      setControlNotice('Falha ao salvar parâmetros')
      setTimeout(() => setControlNotice(''), 3000)
    },
  })

  const updateMetadata = useMutation({
    mutationFn: () => devicesApi.updateMetadata(deviceId!, { btu: Number(btuValue) }),
    onSuccess: () => {
      setEditBtu(false)
      refetch()
    },
    onError: () => {
      setControlNotice('Falha ao atualizar BTU')
      setTimeout(() => setControlNotice(''), 3000)
    },
  })

  const applyLocalCommand = (base: DeviceParameters | null | undefined, action: DeviceControlAction) => {
    if (!base) return null
    const next = { ...base }
    if (action === 'power_on') {
      next.mode_device = 1
      next.mode_ac = 0
    }
    if (action === 'power_off') next.mode_device = 0
    if (action === 'temperature_down') next.setpoint_cool = Math.max(SETPOINT_MIN, next.setpoint_cool - 1)
    if (action === 'temperature_up') next.setpoint_cool = Math.min(SETPOINT_MAX, next.setpoint_cool + 1)
    return next
  }

  const controlMutation = useMutation({
    mutationFn: (action: DeviceControlAction) => devicesApi.control(deviceId!, action),
    onMutate: (action) => {
      setControlNotice('')
      const nextParams = applyLocalCommand(params ?? device?.parameters, action)
      if (nextParams) setParams(nextParams)
    },
    onSuccess: (data) => {
      if (data?.parameters) setParams(data.parameters)
      setControlNotice('Comando enviado')
      setTimeout(() => setControlNotice(''), 2000)
      setTimeout(refetch, 2000)
    },
    onError: () => {
      setControlNotice('Não foi possível comunicar com o sistema')
      setTimeout(() => setControlNotice(''), 3000)
      setTimeout(refetch, 2000)
    },
  })

  if (!device) return <div className="text-gray-500 text-sm">Carregando...</div>

  const currentParams = params ?? device.parameters
  const currentSetpoint = currentParams?.setpoint_cool
  const isOff = currentParams?.mode_device != null
    ? currentParams.mode_device === 0
    : device.state === false || device.status === 'DESLIGADO'
  const canControl = Boolean(currentParams) && !controlMutation.isPending
  const canDecrease = canControl && currentSetpoint != null && currentSetpoint > SETPOINT_MIN
  const canIncrease = canControl && currentSetpoint != null && currentSetpoint < SETPOINT_MAX
  const powerAction: DeviceControlAction = isOff ? 'power_on' : 'power_off'
  const sendControl = (action: DeviceControlAction) => controlMutation.mutate(action)

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">{device.name}</h1>
          <p className="text-sm text-gray-500">{device.store_name} {device.sector_name && `• ${device.sector_name}`}</p>
        </div>
        <StatusBadge status={device.status} />
        <button
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white rounded-lg text-sm transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${syncMutation.isPending ? 'animate-spin' : ''}`} />
          Sincronizar
        </button>
        <button
          onClick={() => navigate(`/history/${deviceId}`)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white rounded-lg text-sm transition-colors"
        >
          <History className="w-4 h-4" />
          Histórico
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Temperatura', value: formatTemp(device.temperature) },
          { label: 'Média Histórica', value: formatTemp(device.historical_avg) },
          { label: 'Delta vs Setpoint', value: formatDelta(device.delta_temp) },
          { label: 'Eficiência', value: formatEfficiency(device.efficiency_score) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
            <div className="text-xs text-gray-500 mb-1">{label}</div>
            <div className="text-xl font-bold text-gray-900 dark:text-white">{value}</div>
          </div>
        ))}
      </div>

      {device.parameters && (
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Controles rápidos</h2>
            <div className="text-xs text-gray-500">
              Setpoint atual: <span className="font-medium text-gray-900 dark:text-white">{currentSetpoint ?? '—'}°C</span>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <button
              type="button"
              onClick={() => sendControl('temperature_down')}
              disabled={!canDecrease}
              title="Diminuir temperatura"
              className="flex min-h-12 items-center justify-center gap-2 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 transition-colors hover:border-blue-500/60 hover:text-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Minus className="w-4 h-4" />
              Diminuir
            </button>
            <button
              type="button"
              onClick={() => sendControl(powerAction)}
              disabled={!canControl}
              title={isOff ? 'Ligar equipamento' : 'Desligar equipamento'}
              className={`flex min-h-12 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                isOff
                  ? 'bg-green-600 text-white hover:bg-green-500'
                  : 'bg-red-600 text-white hover:bg-red-500'
              }`}
            >
              {isOff ? <Power className="w-4 h-4" /> : <PowerOff className="w-4 h-4" />}
              {isOff ? 'Ligar' : 'Desligar'}
            </button>
            <button
              type="button"
              onClick={() => sendControl('temperature_up')}
              disabled={!canIncrease}
              title="Aumentar temperatura"
              className="flex min-h-12 items-center justify-center gap-2 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 transition-colors hover:border-blue-500/60 hover:text-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus className="w-4 h-4" />
              Aumentar
            </button>
          </div>
          {controlNotice && (
            <div className={`text-xs ${controlMutation.isError ? 'text-red-500' : 'text-green-500'}`}>{controlNotice}</div>
          )}
        </div>
      )}

      {device.parameters && (
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Parametrizações</h2>
            <button
              onClick={() => editParams ? updateParams.mutate(params) : setEditParams(true)}
              className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${
                editParams ? 'bg-blue-600 text-gray-900 dark:text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {editParams ? (updateParams.isPending ? 'Salvando...' : 'Salvar') : 'Editar'}
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            {[
              { label: 'Modo Dispositivo', value: MODE_DEVICE[params?.mode_device] || '—', key: 'mode_device', type: 'select', opts: MODE_DEVICE },
              { label: 'Modo AC', value: MODE_AC[params?.mode_ac] || '—', key: 'mode_ac', type: 'select', opts: MODE_AC },
              { label: 'Fan Speed', value: FAN_SPEED[params?.fan_speed] || '—', key: 'fan_speed', type: 'select', opts: FAN_SPEED.slice(1), valueOffset: 1 },
              { label: 'Setpoint Resfr.', value: `${params?.setpoint_cool}°C`, key: 'setpoint_cool', type: 'number', min: 18, max: 28 },
            ].map(({ label, value, key, type, opts, min, max, valueOffset = 0 }: any) => (
              <div key={key}>
                <div className="text-gray-500 text-xs mb-1">{label}</div>
                {editParams && params ? (
                  type === 'select' ? (
                    <select
                      value={params[key]}
                      onChange={e => setParams({ ...params, [key]: +e.target.value })}
                      className="bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white rounded px-2 py-1 text-sm w-full"
                    >
                      {opts.map((o: string, i: number) => <option key={i} value={i + valueOffset}>{o}</option>)}
                    </select>
                  ) : (
                    <input
                      type="number"
                      value={params[key]}
                      min={min}
                      max={max}
                      onChange={e => setParams({ ...params, [key]: +e.target.value })}
                      className="bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white rounded px-2 py-1 text-sm w-full"
                    />
                  )
                ) : (
                  <div className="text-gray-900 dark:text-white font-medium">{value}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {briseSchedules && briseSchedules.length > 0 && (
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <CalendarDays className="w-4 h-4 text-blue-500" />
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Agendamentos Brise</h2>
          </div>
          <div className="space-y-2">
            {briseSchedules.map(s => (
              <div
                key={s.schedule_id}
                className={`flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border px-4 py-3 text-sm ${
                  s.currently_active
                    ? 'border-blue-400/50 bg-blue-50 dark:bg-blue-950/30'
                    : 'border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950'
                }`}
              >
                <span className={`font-medium ${s.currently_active ? 'text-blue-600 dark:text-blue-400' : 'text-gray-900 dark:text-white'}`}>
                  {s.name || `Schedule #${s.schedule_id}`}
                </span>
                {s.currently_active && (
                  <span className="text-xs bg-blue-500 text-white rounded-full px-2 py-0.5">ativo agora</span>
                )}
                {!s.enable && (
                  <span className="text-xs bg-gray-400 text-white rounded-full px-2 py-0.5">desativado</span>
                )}
                <span className="text-gray-500 text-xs">
                  {s.active_days.join(', ')} &nbsp;·&nbsp; {s.start_time}–{s.end_time}
                </span>
                {s.setpoint_cool != null && (
                  <span className="text-gray-500 text-xs">setpoint {s.setpoint_cool}°C</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-5 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Informações do Dispositivo</h2>
          <button
            onClick={() => editBtu ? updateMetadata.mutate() : setEditBtu(true)}
            disabled={updateMetadata.isPending || (editBtu && (!Number(btuValue) || Number(btuValue) < 1000))}
            className={`text-xs px-3 py-1.5 rounded-lg transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              editBtu ? 'bg-blue-600 text-gray-900 dark:text-white' : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
            }`}
          >
            {editBtu ? (updateMetadata.isPending ? 'Salvando...' : 'Salvar BTU') : 'Editar BTU'}
          </button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          <div><div className="text-gray-500 text-xs">ID Brise</div><div className="text-gray-900 dark:text-white font-mono">{device.brise_id}</div></div>
          <div>
            <div className="text-gray-500 text-xs">Capacidade</div>
            {editBtu ? (
              <input
                type="number"
                min={1000}
                step={1000}
                value={btuValue}
                onChange={e => setBtuValue(e.target.value)}
                className="mt-1 bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 text-gray-900 dark:text-white rounded px-2 py-1 text-sm w-full"
              />
            ) : (
              <div className="text-gray-900 dark:text-white">{device.btu?.toLocaleString()} BTU</div>
            )}
          </div>
          <div><div className="text-gray-500 text-xs">Última atualização</div><div className="text-gray-900 dark:text-white">{formatRelativeTime(device.updated_at)}</div></div>
          <div><div className="text-gray-500 text-xs">Última manutenção</div><div className="text-gray-900 dark:text-white">{device.last_maintenance ? formatRelativeTime(device.last_maintenance) : 'Não registrada'}</div></div>
          <div><div className="text-gray-500 text-xs">Ambiente crítico</div><div className="text-gray-900 dark:text-white">{device.is_critical_environment ? 'Sim' : 'Não'}</div></div>
        </div>
      </div>
    </div>
  )
}
