import { create } from 'zustand'

export type InspectorTarget =
  | { type: 'zone'; storeId: string; zoneKey: string; zoneName: string }
  | { type: 'device'; deviceId: string; deviceName: string; storeId?: string }
  | { type: 'store'; storeId: string; storeName: string }

interface InspectorState {
  target: InspectorTarget | null
  open: boolean
  setTarget: (t: InspectorTarget) => void
  close: () => void
}

export const useInspectorStore = create<InspectorState>(set => ({
  target: null,
  open: false,
  setTarget: (t) => set({ target: t, open: true }),
  close: () => set({ open: false }),
}))
