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
    set({
      activeAlerts: [alert, ...current],
      p1Count: alert.severity === 'P1' ? get().p1Count + 1 : get().p1Count,
      p2Count: alert.severity === 'P2' ? get().p2Count + 1 : get().p2Count,
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
