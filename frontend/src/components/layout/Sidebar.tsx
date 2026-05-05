import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Bell, Wrench, Thermometer } from 'lucide-react'
import { useAlertStore } from '../../store/useAlertStore'
import { cn } from '../../lib/utils'

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/alerts', icon: Bell, label: 'Alertas' },
  { to: '/maintenance', icon: Wrench, label: 'Manutenção' },
]

export default function Sidebar() {
  const { p1Count, p2Count } = useAlertStore()
  const totalAlerts = p1Count + p2Count

  return (
    <aside className="w-16 lg:w-56 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col shrink-0">
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
                isActive ? 'bg-blue-600 text-gray-900 dark:text-white' : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white'
              )
            }
          >
            <Icon className="w-5 h-5 shrink-0" />
            <span className="hidden lg:block">{label}</span>
            {label === 'Alertas' && totalAlerts > 0 && (
              <span className="hidden lg:flex ml-auto bg-red-500 text-gray-900 dark:text-white text-xs rounded-full w-5 h-5 items-center justify-center">
                {totalAlerts}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="p-4 border-t border-gray-200 dark:border-gray-800">
        <div className="hidden lg:block text-xs text-gray-500 dark:text-gray-600">Bemol Varejo v1.0</div>
      </div>
    </aside>
  )
}
