import { NavLink } from 'react-router-dom'
import {
  Activity,
  BarChart3,
  Bell,
  Building2,
  LayoutDashboard,
  Map,
  Monitor,
  Settings,
  Thermometer,
  Truck,
  Users,
  Wrench,
} from 'lucide-react'
import { useAlertStore } from '../../store/useAlertStore'
import { cn } from '../../lib/utils'

const navItems = [
  { to: '/cockpit', icon: LayoutDashboard, label: 'Cockpit' },
  { to: '/lojas', icon: Building2, label: 'Lojas' },
  { to: '/mapa-termico', icon: Map, label: 'Mapa Térmico' },
  { to: '/equipamentos', icon: Monitor, label: 'Equipamentos' },
  { to: '/alertas', icon: Bell, label: 'Alertas' },
  { to: '/manutencoes', icon: Wrench, label: 'Manutenções' },
  { to: '/fornecedores', icon: Truck, label: 'Fornecedores' },
  { to: '/relatorios', icon: BarChart3, label: 'Relatórios' },
  { to: '/configuracoes', icon: Settings, label: 'Configurações' },
  { to: '/usuarios', icon: Users, label: 'Usuários' },
  { to: '/atividade', icon: Activity, label: 'Atividade' },
]

export default function Sidebar() {
  const { p1Count, p2Count } = useAlertStore()
  const totalAlerts = p1Count + p2Count

  return (
    <aside className="w-16 lg:w-60 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col shrink-0">
      <div className="flex items-center gap-2 p-4 border-b border-gray-200 dark:border-gray-800">
        <Thermometer className="w-6 h-6 text-blue-400 shrink-0" />
        <span className="hidden lg:block text-sm font-semibold text-gray-900 dark:text-white truncate">Refrigeração</span>
      </div>
      <nav className="flex-1 py-4 space-y-1 px-2">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors',
                isActive ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white'
              )
            }
            title={label}
          >
            <Icon className="w-5 h-5 shrink-0" />
            <span className="hidden lg:block">{label}</span>
            {label === 'Alertas' && totalAlerts > 0 && (
              <span className="hidden lg:flex ml-auto bg-red-500 text-white text-xs rounded-full w-5 h-5 items-center justify-center">
                {totalAlerts}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="p-4 border-t border-gray-200 dark:border-gray-800">
        <div className="hidden lg:block text-xs text-gray-500 dark:text-gray-600">Breeze HVAC v1.0</div>
      </div>
    </aside>
  )
}
