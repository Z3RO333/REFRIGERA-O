import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Shield, User, UserCheck, UserX, ChevronDown } from 'lucide-react'
import { usersApi } from '../api/client'
import { useAuthStore } from '../store/useAuthStore'
import { cn, formatDate, formatRelativeTime } from '../lib/utils'

interface UserRecord {
  id: string
  name: string
  email: string
  role: string
  active: boolean
  created_at: string
  last_login_at: string | null
}

const ROLE_LABELS: Record<string, { label: string; color: string }> = {
  ADMIN:  { label: 'Admin',     color: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
  EDITOR: { label: 'Editor',    color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
  VIEWER: { label: 'Visualizador', color: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-400' },
}

export default function UsersPage() {
  const { role: myRole, email: myEmail } = useAuthStore()
  const queryClient = useQueryClient()
  const isAdmin = myRole === 'ADMIN'
  const [openRoleMenu, setOpenRoleMenu] = useState<string | null>(null)

  const { data: users = [], isLoading } = useQuery<UserRecord[]>({
    queryKey: ['users'],
    queryFn: usersApi.list,
    refetchInterval: 30_000,
  })

  const roleMutation = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => usersApi.updateRole(id, role),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['users'] }); setOpenRoleMenu(null) },
  })

  const activeMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => usersApi.toggleActive(id, active),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })

  const activeUsers = users.filter(u => u.active)
  const inactiveUsers = users.filter(u => !u.active)

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">Usuários</h1>
          <p className="text-xs text-gray-500">
            {activeUsers.length} ativo{activeUsers.length !== 1 ? 's' : ''}
            {inactiveUsers.length > 0 && ` • ${inactiveUsers.length} inativo${inactiveUsers.length !== 1 ? 's' : ''}`}
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 dark:border-blue-800 dark:bg-blue-900/20">
          <Shield className="h-4 w-4 text-blue-500" />
          <span className="text-xs font-medium text-blue-700 dark:text-blue-400">
            {isAdmin ? 'Você é admin' : 'Somente admins podem alterar perfis'}
          </span>
        </div>
      </div>

      {isLoading ? (
        <div className="py-16 text-center text-sm text-gray-500">Carregando usuários...</div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50 dark:border-gray-800 dark:bg-gray-800/50">
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">Usuário</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">Perfil</th>
                <th className="hidden px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500 md:table-cell">Último acesso</th>
                <th className="hidden px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500 lg:table-cell">Cadastrado em</th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase text-gray-500">Status</th>
                {isAdmin && <th className="px-4 py-3" />}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {users.map(user => {
                const roleMeta = ROLE_LABELS[user.role] ?? ROLE_LABELS.VIEWER
                const isMe = user.email === myEmail
                return (
                  <tr key={user.id} className={cn(
                    'transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/40',
                    !user.active && 'opacity-50'
                  )}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700 dark:bg-blue-900/40 dark:text-blue-400">
                          {user.name.charAt(0).toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="truncate font-medium text-gray-900 dark:text-white">
                            {user.name}
                            {isMe && <span className="ml-1.5 rounded-full bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold text-green-700 dark:bg-green-900/30 dark:text-green-400">você</span>}
                          </p>
                          <p className="truncate text-xs text-gray-500">{user.email}</p>
                        </div>
                      </div>
                    </td>

                    <td className="px-4 py-3">
                      {isAdmin && !isMe ? (
                        <div className="relative">
                          <button
                            onClick={() => setOpenRoleMenu(openRoleMenu === user.id ? null : user.id)}
                            className={cn(
                              'inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-semibold',
                              roleMeta.color
                            )}
                          >
                            {roleMeta.label}
                            <ChevronDown className="h-3 w-3" />
                          </button>
                          {openRoleMenu === user.id && (
                            <div className="absolute left-0 top-8 z-10 w-36 rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800">
                              {Object.entries(ROLE_LABELS).map(([role, meta]) => (
                                <button
                                  key={role}
                                  onClick={() => roleMutation.mutate({ id: user.id, role })}
                                  className={cn(
                                    'block w-full px-3 py-2 text-left text-xs hover:bg-gray-50 dark:hover:bg-gray-700',
                                    user.role === role && 'font-bold'
                                  )}
                                >
                                  {meta.label}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className={cn('inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold', roleMeta.color)}>
                          {roleMeta.label}
                        </span>
                      )}
                    </td>

                    <td className="hidden px-4 py-3 text-gray-500 md:table-cell">
                      {user.last_login_at ? formatRelativeTime(user.last_login_at) : '—'}
                    </td>

                    <td className="hidden px-4 py-3 text-gray-500 lg:table-cell">
                      {formatDate(user.created_at)}
                    </td>

                    <td className="px-4 py-3">
                      {user.active ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-1 text-xs font-semibold text-green-700 dark:bg-green-900/30 dark:text-green-400">
                          <UserCheck className="h-3 w-3" /> Ativo
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-1 text-xs font-semibold text-gray-500 dark:bg-gray-800">
                          <UserX className="h-3 w-3" /> Inativo
                        </span>
                      )}
                    </td>

                    {isAdmin && (
                      <td className="px-4 py-3">
                        {!isMe && (
                          <button
                            onClick={() => activeMutation.mutate({ id: user.id, active: !user.active })}
                            className="rounded-lg border border-gray-200 px-2 py-1 text-xs text-gray-600 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-700"
                          >
                            {user.active ? 'Desativar' : 'Reativar'}
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>

          {users.length === 0 && (
            <div className="py-16 text-center text-sm text-gray-500">
              <User className="mx-auto mb-2 h-8 w-8 text-gray-300" />
              Nenhum usuário cadastrado
            </div>
          )}
        </div>
      )}
    </div>
  )
}
