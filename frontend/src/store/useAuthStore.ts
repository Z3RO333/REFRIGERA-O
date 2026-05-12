import { create } from 'zustand'

localStorage.removeItem('hvac_token')

interface AuthState {
  status: 'checking' | 'authenticated' | 'anonymous'
  role: string | null
  name: string | null
  email: string | null
  login: (role: string, name: string, email?: string) => void
  setSession: (role: string, name: string, email?: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>(set => ({
  status: 'checking',
  role: localStorage.getItem('hvac_role'),
  name: localStorage.getItem('hvac_name'),
  email: localStorage.getItem('hvac_email'),
  login: (role, name, email) => {
    localStorage.setItem('hvac_role', role)
    localStorage.setItem('hvac_name', name)
    if (email) localStorage.setItem('hvac_email', email)
    set({ status: 'authenticated', role, name, email: email ?? null })
  },
  setSession: (role, name, email) => {
    localStorage.setItem('hvac_role', role)
    localStorage.setItem('hvac_name', name)
    if (email) localStorage.setItem('hvac_email', email)
    set({ status: 'authenticated', role, name, email: email ?? null })
  },
  logout: () => {
    localStorage.removeItem('hvac_role')
    localStorage.removeItem('hvac_name')
    localStorage.removeItem('hvac_email')
    set({ status: 'anonymous', role: null, name: null, email: null })
  },
}))
