import { create } from 'zustand'

interface AuthState {
  token: string | null
  role: string | null
  name: string | null
  login: (token: string, role: string, name: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>(set => ({
  token: localStorage.getItem('hvac_token'),
  role: localStorage.getItem('hvac_role'),
  name: localStorage.getItem('hvac_name'),
  login: (token, role, name) => {
    localStorage.setItem('hvac_token', token)
    localStorage.setItem('hvac_role', role)
    localStorage.setItem('hvac_name', name)
    set({ token, role, name })
  },
  logout: () => {
    localStorage.removeItem('hvac_token')
    localStorage.removeItem('hvac_role')
    localStorage.removeItem('hvac_name')
    set({ token: null, role: null, name: null })
  },
}))
