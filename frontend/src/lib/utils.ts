import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { DeviceStatus } from '../types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const STATUS_CONFIG: Record<DeviceStatus, { color: string; bg: string; border: string; label: string; pulse: boolean }> = {
  NORMAL: { color: '#22C55E', bg: 'bg-green-500/10', border: 'border-green-500/30', label: 'Normal', pulse: false },
  ATENÇÃO: { color: '#EAB308', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', label: 'Atenção', pulse: false },
  CRÍTICO: { color: '#EF4444', bg: 'bg-red-500/10', border: 'border-red-500/30', label: 'Crítico', pulse: true },
  BAIXA_EFICIÊNCIA: { color: '#F97316', bg: 'bg-orange-500/10', border: 'border-orange-500/30', label: 'Baixa Eficiência', pulse: false },
  SEM_LEITURA: { color: '#6B7280', bg: 'bg-gray-500/10', border: 'border-gray-500/30', label: 'Sem Leitura', pulse: false },
  DESLIGADO: { color: '#3B82F6', bg: 'bg-blue-500/10', border: 'border-blue-500/30', label: 'Desligado', pulse: false },
  COMPRESSOR_CYCLING: { color: '#A855F7', bg: 'bg-purple-500/10', border: 'border-purple-500/30', label: 'Compres. Ciclando', pulse: true },
}

export function getStatusConfig(status: string | undefined) {
  return STATUS_CONFIG[(status as DeviceStatus) || 'SEM_LEITURA'] || STATUS_CONFIG['SEM_LEITURA']
}

export function formatTemp(t: number | null | undefined): string {
  if (t == null) return '—'
  return `${t.toFixed(1)}°C`
}

export function formatDelta(d: number | null | undefined): string {
  if (d == null) return '—'
  return d > 0 ? `+${d.toFixed(1)}°C` : `${d.toFixed(1)}°C`
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return 'Nunca'
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Agora'
  if (mins < 60) return `há ${mins} min`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `há ${hours}h`
  return `há ${Math.floor(hours / 24)}d`
}

export function formatEfficiency(score: number | null | undefined): string {
  if (score == null) return '—'
  return `${Math.round(score * 100)}%`
}

export const SEVERITY_CONFIG = {
  P1: { color: 'text-red-400', bg: 'bg-red-500/20', border: 'border-red-500', label: 'P1 — Crítico' },
  P2: { color: 'text-orange-400', bg: 'bg-orange-500/20', border: 'border-orange-500', label: 'P2 — Alto' },
  P3: { color: 'text-yellow-400', bg: 'bg-yellow-500/20', border: 'border-yellow-500', label: 'P3 — Médio' },
  P4: { color: 'text-blue-400', bg: 'bg-blue-500/20', border: 'border-blue-500', label: 'P4 — Baixo' },
}
