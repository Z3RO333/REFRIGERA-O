import { NavLink } from 'react-router-dom'
import {
  Activity,
  BarChart3,
  Bell,
  Bot,
  Building2,
  ClipboardList,
  Cpu,
  LayoutDashboard,
  Map,
  Monitor,
  Settings,
  Thermometer,
  Truck,
  Users,
  Wind,
  Wrench,
} from 'lucide-react'
import { useAlertStore } from '../../store/useAlertStore'
import { useAuthStore } from '../../store/useAuthStore'
import { cn } from '../../lib/utils'

type NavItem = {
  to: string
  icon: React.ElementType
  label: string
  minRole?: 'EDITOR' | 'ADMIN'
}

const navItems: NavItem[] = [
  { to: '/cockpit', icon: LayoutDashboard, label: 'Cockpit' },
  { to: '/lojas', icon: Building2, label: 'Lojas' },
  { to: '/mapa-termico', icon: Map, label: 'Mapa Térmico' },
  { to: '/equipamentos', icon: Monitor, label: 'Equipamentos' },
  { to: '/alertas', icon: Bell, label: 'Alertas' },
  { to: '/ia', icon: Bot, label: 'Análise de IA' },
  { to: '/ambientes', icon: Wind, label: 'Ambientes' },
  { to: '/zonas', icon: Cpu, label: 'Zonas (Twin)' },
  { to: '/logs', icon: ClipboardList, label: 'Logs' },
  { to: '/manutencoes', icon: Wrench, label: 'Manutenções', minRole: 'EDITOR' },
  { to: '/fornecedores', icon: Truck, label: 'Fornecedores', minRole: 'EDITOR' },
  { to: '/relatorios', icon: BarChart3, label: 'Relatórios' },
  { to: '/atividade', icon: Activity, label: 'Atividade' },
  { to: '/configuracoes', icon: Settings, label: 'Configurações', minRole: 'ADMIN' },
  { to: '/usuarios', icon: Users, label: 'Usuários', minRole: 'ADMIN' },
]

const ROLE_LEVEL: Record<string, number> = { VIEWER: 0, EDITOR: 1, ADMIN: 2 }

function hasAccess(userRole: string | null, minRole?: 'EDITOR' | 'ADMIN'): boolean {
  if (!minRole) return true
  const userLevel = ROLE_LEVEL[userRole ?? 'VIEWER'] ?? 0
  return userLevel >= ROLE_LEVEL[minRole]
}

export default function Sidebar() {
  const { p1Count, p2Count } = useAlertStore()
  const { role } = useAuthStore()
  const totalAlerts = p1Count + p2Count
  const visibleItems = navItems.filter(item => hasAccess(role, item.minRole))

  return (
    <aside className="w-16 lg:w-60 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col shrink-0">
      <div className="flex items-center gap-2 p-4 border-b border-gray-200 dark:border-gray-800">
        <Thermometer className="w-6 h-6 text-blue-400 shrink-0" />
        <span className="hidden lg:block text-sm font-semibold text-gray-900 dark:text-white truncate">Refrigeração</span>
      </div>
      <nav className="flex-1 py-4 space-y-1 px-2">
        {visibleItems.map(({ to, icon: Icon, label }) => (
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
