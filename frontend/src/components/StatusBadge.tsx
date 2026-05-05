import { cn, getStatusConfig } from '../lib/utils'

interface Props {
  status: string
  size?: 'sm' | 'md'
}

export default function StatusBadge({ status, size = 'md' }: Props) {
  const cfg = getStatusConfig(status)
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full font-medium border',
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs',
        cfg.bg, cfg.border
      )}
      style={{ color: cfg.color }}
    >
      <span
        className={cn('w-1.5 h-1.5 rounded-full', cfg.pulse && 'animate-pulse-critical')}
        style={{ backgroundColor: cfg.color }}
      />
      {cfg.label}
    </span>
  )
}
