import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Bot, LogIn, SlidersHorizontal, Thermometer, Wrench, Zap } from 'lucide-react'
import { auditApi } from '../api/client'
import { cn, formatRelativeTime } from '../lib/utils'

interface AuditEntry {
  id: string
  user_name: string | null
  user_email: string | null
  action_type: string
  device_name: string | null
  zone_key: string | null
  description: string | null
  old_value: string | null
  new_value: string | null
  metadata: Record<string, unknown> | null
  created_at: string
}

const ACTION_META: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  login:            { label: 'Login',          icon: <LogIn className="h-3.5 w-3.5" />,          color: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
  zone_mode_change: { label: 'Modo de zona',   icon: <SlidersHorizontal className="h-3.5 w-3.5" />, color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
  device_control:   { label: 'Controle AC',    icon: <Thermometer className="h-3.5 w-3.5" />,    color: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400' },
  zone_trigger:     { label: 'Disparo IA',     icon: <Zap className="h-3.5 w-3.5" />,            color: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
  zone_guardrails_change: { label: 'Guardrails', icon: <Wrench className="h-3.5 w-3.5" />,         color: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400' },
  ai_action:        { label: 'Ação da IA',     icon: <Bot className="h-3.5 w-3.5" />,            color: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
}

const FILTER_OPTIONS = [
  { value: 'all', label: 'Todos' },
  { value: 'login', label: 'Logins' },
  { value: 'device_control', label: 'Controles AC' },
  { value: 'zone_mode_change', label: 'Modo de zona' },
  { value: 'zone_guardrails_change', label: 'Guardrails' },
]

export default function ActivityLog() {
  const [filter, setFilter] = useState('all')

  const { data: entries = [], isLoading } = useQuery<AuditEntry[]>({
    queryKey: ['audit', filter],
    queryFn: () => auditApi.list({ limit: 200, action_type: filter === 'all' ? undefined : filter }),
    refetchInterval: 30_000,
  })

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Atividade</h1>
          <p className="text-xs text-gray-500">{entries.length} registro{entries.length !== 1 ? 's' : ''} • últimas ações no sistema</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {FILTER_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value)}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                filter === opt.value
                  ? 'border-blue-600 bg-blue-600 text-white'
                  : 'border-gray-200 text-gray-600 hover:bg-gray-100 dark:border-gray-800 dark:text-gray-400 dark:hover:bg-gray-800'
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="py-16 text-center text-sm text-gray-500">Carregando atividade...</div>
      ) : entries.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 py-16 text-center dark:border-gray-700">
          <Activity className="mx-auto mb-2 h-8 w-8 text-gray-300" />
          <p className="text-sm text-gray-500">Nenhuma atividade registrada ainda</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
          <ul className="divide-y divide-gray-100 dark:divide-gray-800">
            {entries.map(entry => {
              const meta = ACTION_META[entry.action_type] ?? {
                label: entry.action_type,
                icon: <Activity className="h-3.5 w-3.5" />,
                color: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
              }
              return (
                <li key={entry.id} className="flex items-start gap-4 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-800/40">
                  <div className={cn('mt-0.5 shrink-0 rounded-lg p-1.5', meta.color)}>
                    {meta.icon}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-gray-900 dark:text-white">
                        {entry.description ?? meta.label}
                      </span>
                      <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-semibold', meta.color)}>
                        {meta.label}
                      </span>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                      {entry.user_email && (
                        <span>{entry.user_email}</span>
                      )}
                      {entry.device_name && (
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 dark:bg-gray-800">
                          {entry.device_name}
                        </span>
                      )}
                      {entry.old_value && entry.new_value && (
                        <span>
                          <span className="text-red-500">{entry.old_value}</span>
                          {' → '}
                          <span className="text-green-600">{entry.new_value}</span>
                        </span>
                      )}
                    </div>
                  </div>
                  <time className="shrink-0 text-xs text-gray-400">{formatRelativeTime(entry.created_at)}</time>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
