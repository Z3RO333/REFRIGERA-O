import { create } from 'zustand'

localStorage.removeItem('hvac_token')

interface AuthState {
  status: 'checking' | 'authenticated' | 'anonymous'
  role: string | null
  name: string | null
  login: (role: string, name: string) => void
  setSession: (role: string, name: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>(set => ({
  status: 'checking',
  role: localStorage.getItem('hvac_role'),
  name: localStorage.getItem('hvac_name'),
  login: (role, name) => {
    localStorage.setItem('hvac_role', role)
    localStorage.setItem('hvac_name', name)
    set({ status: 'authenticated', role, name })
  },
  setSession: (role, name) => {
    localStorage.setItem('hvac_role', role)
    localStorage.setItem('hvac_name', name)
    set({ status: 'authenticated', role, name })
  },
  logout: () => {
    localStorage.removeItem('hvac_role')
    localStorage.removeItem('hvac_name')
    set({ status: 'anonymous', role: null, name: null })
  },
}))
