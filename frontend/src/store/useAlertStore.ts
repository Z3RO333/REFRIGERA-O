import { create } from 'zustand'
import type { Alert } from '../types'

interface AlertState {
  activeAlerts: Alert[]
  setAlerts: (alerts: Alert[]) => void
  addAlert: (alert: Alert) => void
  removeAlert: (id: string) => void
  p1Count: number
  p2Count: number
}

export const useAlertStore = create<AlertState>((set, get) => ({
  activeAlerts: [],
  p1Count: 0,
  p2Count: 0,
  setAlerts: (alerts) => set({
    activeAlerts: alerts,
    p1Count: alerts.filter(a => a.severity === 'P1' && a.status === 'OPEN').length,
    p2Count: alerts.filter(a => a.severity === 'P2' && a.status === 'OPEN').length,
  }),
  addAlert: (alert) => {
    const current = get().activeAlerts
    if (current.some(a => a.id === alert.id)) return
    const updated = [alert, ...current]
    set({
      activeAlerts: updated,
      p1Count: updated.filter(a => a.severity === 'P1' && a.status === 'OPEN').length,
      p2Count: updated.filter(a => a.severity === 'P2' && a.status === 'OPEN').length,
    })
  },
  removeAlert: (id) => {
    const current = get().activeAlerts.filter(a => a.id !== id)
    set({
      activeAlerts: current,
      p1Count: current.filter(a => a.severity === 'P1' && a.status === 'OPEN').length,
      p2Count: current.filter(a => a.severity === 'P2' && a.status === 'OPEN').length,
    })
  },
}))
