import { cn } from '../lib/utils'

interface Props {
  title: string
  value: string | number
  subtitle?: string
  color?: string
  icon?: React.ReactNode
  onClick?: () => void
}

export default function KPICard({ title, value, subtitle, color, icon, onClick }: Props) {
  return (
    <div
      className={cn(
        'bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4 flex flex-col gap-2',
        onClick && 'cursor-pointer hover:border-gray-300 dark:hover:border-gray-700 transition-colors'
      )}
      onClick={onClick}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500 font-medium uppercase tracking-wide">{title}</span>
        {icon && <span className="text-gray-500 dark:text-gray-600">{icon}</span>}
      </div>
      <div className="text-2xl font-bold text-gray-900 dark:text-white" style={color ? { color } : undefined}>{value}</div>
      {subtitle && <div className="text-xs text-gray-500">{subtitle}</div>}
    </div>
  )
}
