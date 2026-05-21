import { useEffect, useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, Thermometer, Wind, X, Zap } from 'lucide-react'
import { customZonesApi, storesApi } from '../api/client'
import { cn } from '../lib/utils'
import type { CustomZone, Device, ZoneType } from '../types'

interface Props {
  storeId: string
  editZone?: CustomZone | null
  onClose: () => void
}

export default function ZoneEditorModal({ storeId, editZone, onClose }: Props) {
  const qc = useQueryClient()
  const isEdit = !!editZone

  const [name, setName] = useState(editZone?.name ?? '')
  const [idealMin, setIdealMin] = useState(editZone?.ideal_min ?? 20)
  const [idealMax, setIdealMax] = useState(editZone?.ideal_max ?? 24)
  const [zoneType, setZoneType] = useState<ZoneType>(editZone?.zone_type ?? 'ABERTA')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    new Set(editZone?.device_ids ?? [])
  )
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)

  const { data: devices = [] } = useQuery<Device[]>({
    queryKey: ['store-devices', storeId],
    queryFn: () => storesApi.devices(storeId),
    enabled: !!storeId,
  })

  // Filtra sensores externos e mostra só ACs reais
  const actionableDevices = useMemo(
    () => devices.filter(d => !d.is_external_sensor && d.status !== 'DESLIGADO'),
    [devices]
  )

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    return actionableDevices.filter(d =>
      d.name.toLowerCase().includes(q) || (d.sector_name ?? '').toLowerCase().includes(q)
    )
  }, [actionableDevices, search])

  const mutation = useMutation({
    mutationFn: () => isEdit
      ? customZonesApi.update(storeId, editZone!.zone_key, {
          name, ideal_min: idealMin, ideal_max: idealMax,
          zone_type: zoneType, device_ids: [...selectedIds],
        })
      : customZonesApi.create(storeId, {
          name, ideal_min: idealMin, ideal_max: idealMax,
          zone_type: zoneType, device_ids: [...selectedIds],
          mode: 'manual',
        }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['custom-zones', storeId] })
      qc.invalidateQueries({ queryKey: ['zones-automation', storeId] })
      onClose()
    },
    onError: (err: any) => {
      setError(err?.response?.data?.detail ?? 'Erro ao salvar zona')
    },
  })

  function toggle(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!name.trim()) { setError('Nome é obrigatório'); return }
    if (idealMin >= idealMax) { setError('Temperatura mínima deve ser menor que a máxima'); return }
    if (selectedIds.size === 0) { setError('Selecione pelo menos um equipamento'); return }
    mutation.mutate()
  }

  // Fecha ao pressionar Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const STATUS_COLOR: Record<string, string> = {
    NORMAL: 'text-green-500', ATENÇÃO: 'text-yellow-500',
    CRÍTICO: 'text-red-500', BAIXA_EFICIÊNCIA: 'text-orange-400',
    SEM_LEITURA: 'text-gray-400', DESLIGADO: 'text-gray-300',
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Overlay */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-lg bg-white dark:bg-gray-900 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <div className="flex items-center gap-2">
            <Wind className="h-5 w-5 text-blue-500" />
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">
              {isEdit ? 'Editar Zona' : 'Nova Zona Térmica'}
            </h2>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800">
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col flex-1 overflow-hidden">
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
            {/* Nome */}
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Nome do ambiente
              </label>
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="Ex: Farma – Área de Vendas"
                className="w-full rounded-lg px-3 py-2 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {/* Faixa de temperatura */}
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
                Faixa alvo de temperatura
              </label>
              <div className="flex items-center gap-3">
                <div className="flex-1 relative">
                  <Thermometer className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-blue-400" />
                  <input
                    type="number" min={16} max={30}
                    value={idealMin}
                    onChange={e => setIdealMin(Number(e.target.value))}
                    className="w-full rounded-lg pl-8 pr-3 py-2 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">min</span>
                </div>
                <span className="text-gray-400 text-sm">até</span>
                <div className="flex-1 relative">
                  <Thermometer className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-red-400" />
                  <input
                    type="number" min={16} max={30}
                    value={idealMax}
                    onChange={e => setIdealMax(Number(e.target.value))}
                    className="w-full rounded-lg pl-8 pr-3 py-2 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white outline-none focus:ring-2 focus:ring-blue-500"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">max</span>
                </div>
              </div>
              <p className="text-xs text-gray-400 mt-1">
                Meta: manter entre {idealMin}°C e {idealMax}°C
              </p>
            </div>

            {/* Tipo */}
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
                Tipo de ambiente
              </label>
              <div className="flex gap-3">
                {(['ABERTA', 'SALA_FECHADA'] as ZoneType[]).map(t => (
                  <label
                    key={t}
                    className={cn(
                      'flex-1 flex items-center justify-center gap-2 py-2 rounded-lg border-2 cursor-pointer text-sm transition-colors',
                      zoneType === t
                        ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 font-medium'
                        : 'border-gray-200 dark:border-gray-700 text-gray-500 hover:border-gray-300',
                    )}
                  >
                    <input
                      type="radio" className="sr-only"
                      checked={zoneType === t}
                      onChange={() => setZoneType(t)}
                    />
                    {t === 'ABERTA' ? '🏢 Área aberta' : '🚪 Sala fechada'}
                  </label>
                ))}
              </div>
            </div>

            {/* Equipamentos */}
            <div className="flex-1">
              <div className="flex items-center justify-between mb-2">
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  Equipamentos vinculados
                </label>
                {selectedIds.size > 0 && (
                  <span className="text-xs text-blue-600 dark:text-blue-400 font-medium">
                    {selectedIds.size} selecionado{selectedIds.size > 1 ? 's' : ''}
                  </span>
                )}
              </div>
              <div className="relative mb-2">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Buscar equipamento ou setor..."
                  className="w-full rounded-lg pl-8 pr-3 py-1.5 text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white outline-none"
                />
              </div>
              <div className="space-y-1 max-h-48 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-700 p-1">
                {filtered.length === 0 ? (
                  <p className="text-xs text-gray-400 text-center py-4">Nenhum equipamento encontrado</p>
                ) : filtered.map(d => {
                  const checked = selectedIds.has(d.id)
                  return (
                    <label
                      key={d.id}
                      className={cn(
                        'flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors',
                        checked
                          ? 'bg-blue-50 dark:bg-blue-900/20'
                          : 'hover:bg-gray-50 dark:hover:bg-gray-800',
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(d.id)}
                        className="h-4 w-4 rounded accent-blue-600 cursor-pointer"
                      />
                      <Zap className="h-3 w-3 text-gray-400 shrink-0" />
                      <span className="text-sm text-gray-700 dark:text-gray-300 flex-1 truncate">{d.name}</span>
                      {d.sector_name && (
                        <span className="text-xs text-gray-400 shrink-0 truncate max-w-[80px]">{d.sector_name}</span>
                      )}
                      {d.temperature != null && (
                        <span className={cn('text-xs font-medium tabular-nums shrink-0', STATUS_COLOR[d.status] ?? 'text-gray-500')}>
                          {d.temperature.toFixed(1)}°C
                        </span>
                      )}
                    </label>
                  )
                })}
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-800 space-y-3">
            {error && (
              <p className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 py-2 rounded-lg text-sm font-medium border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={mutation.isPending}
                className="flex-1 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50"
              >
                {mutation.isPending ? 'Salvando…' : isEdit ? 'Salvar alterações' : 'Criar zona'}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
