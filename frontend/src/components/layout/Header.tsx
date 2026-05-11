import { useState, type FormEvent } from 'react'
import { Bell, RefreshCw, LogOut, Sun, Moon, Search } from 'lucide-react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '../../store/useAuthStore'
import { useAlertStore } from '../../store/useAlertStore'
import { useThemeStore } from '../../store/useThemeStore'
import { authApi, devicesApi } from '../../api/client'
import type { Device } from '../../types'

const PAGE_TITLES: Record<string, string> = {
  '/cockpit': 'Cockpit de Refrigeração',
  '/dashboard': 'Cockpit de Refrigeração',
  '/lojas': 'Mapa das Lojas',
  '/mapa-termico': 'Mapa Térmico',
  '/equipamentos': 'Equipamentos',
  '/alertas': 'Alertas Operacionais',
  '/alerts': 'Central de Alertas',
  '/manutencoes': 'Manutenções',
  '/maintenance': 'Ranking de Manutenção',
  '/fornecedores': 'Fornecedores',
  '/relatorios': 'Relatórios',
  '/configuracoes': 'Configurações',
  '/usuarios': 'Usuários',
}

export default function Header() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const { name, logout } = useAuthStore()
  const { p1Count, p2Count } = useAlertStore()
  const [machineQuery, setMachineQuery] = useState('')
  const [machineResults, setMachineResults] = useState<Device[]>([])
  const [searchMessage, setSearchMessage] = useState('')
  const [isSearching, setIsSearching] = useState(false)

  const title = PAGE_TITLES[location.pathname]
    || (location.pathname.startsWith('/lojas/') ? 'Unidade Monitorada' : 'Monitoramento de Refrigeração')
  const { theme, toggle } = useThemeStore()

  const openDevice = (deviceId: string) => {
    setMachineResults([])
    setSearchMessage('')
    setMachineQuery('')
    navigate(`/devices/${deviceId}`)
  }

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } finally {
      logout()
      navigate('/login')
    }
  }

  const handleMachineSearch = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const query = machineQuery.trim()
    if (!query) return

    setIsSearching(true)
    setSearchMessage('')
    try {
      const results = await devicesApi.search(query)
      if (results.length === 1) {
        openDevice(results[0].id)
        return
      }
      setMachineResults(results)
      if (results.length === 0) setSearchMessage('Nenhuma máquina encontrada')
    } catch {
      setMachineResults([])
      setSearchMessage('Falha na busca')
    } finally {
      setIsSearching(false)
    }
  }

  return (
    <header className="h-14 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between gap-4 px-6 shrink-0">
      <h1 className="min-w-0 flex-1 text-base font-semibold text-gray-900 dark:text-white truncate">{title}</h1>
      <div className="flex items-center gap-3 shrink-0">
        <form onSubmit={handleMachineSearch} className="relative flex items-center">
          <input
            value={machineQuery}
            onChange={e => {
              setMachineQuery(e.target.value)
              setMachineResults([])
              setSearchMessage('')
            }}
            className="h-9 w-36 sm:w-56 rounded-l-lg border border-gray-300 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 px-3 text-sm text-gray-900 dark:text-white outline-none focus:border-blue-500"
            placeholder="Nº máquina"
          />
          <button
            type="submit"
            disabled={isSearching}
            className="h-9 w-10 rounded-r-lg border border-l-0 border-gray-300 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-50"
            title="Pesquisar máquina"
          >
            <Search className="mx-auto w-4 h-4" />
          </button>
          {(machineResults.length > 0 || searchMessage) && (
            <div className="absolute right-0 top-11 z-20 w-72 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg">
              {machineResults.map(device => (
                <button
                  key={device.id}
                  type="button"
                  onClick={() => openDevice(device.id)}
                  className="block w-full border-b border-gray-100 dark:border-gray-800 px-3 py-2 text-left text-sm last:border-b-0 hover:bg-gray-100 dark:hover:bg-gray-800"
                >
                  <div className="font-mono text-xs text-blue-500">{device.brise_id}</div>
                  <div className="truncate font-medium text-gray-900 dark:text-white">{device.name}</div>
                  <div className="truncate text-xs text-gray-500">{device.store_name} {device.sector_name && `• ${device.sector_name}`}</div>
                </button>
              ))}
              {searchMessage && <div className="px-3 py-2 text-sm text-gray-500">{searchMessage}</div>}
            </div>
          )}
        </form>
        {(p1Count + p2Count) > 0 && (
          <button
            onClick={() => navigate('/alertas')}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/20 border border-red-500/50 rounded-lg text-red-400 text-sm hover:bg-red-500/30 transition-colors"
          >
            <Bell className="w-4 h-4" />
            <span>{p1Count + p2Count} alertas</span>
          </button>
        )}
        <button
          onClick={toggle}
          className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
          title={theme === 'dark' ? 'Modo claro' : 'Modo escuro'}
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
        <button
          onClick={() => queryClient.invalidateQueries()}
          className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
          title="Atualizar dados"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-600 dark:text-gray-400 hidden md:block">{name}</span>
          <button
            onClick={handleLogout}
            className="p-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
            title="Sair"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  )
}
