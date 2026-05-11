import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Building2, Thermometer, Eye, EyeOff } from 'lucide-react'
import { useAuthStore } from '../store/useAuthStore'
import { authApi } from '../api/client'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading] = useState(false)
  const [microsoftEnabled, setMicrosoftEnabled] = useState(false)
  const [error, setError] = useState('')
  const login = useAuthStore(s => s.login)
  const navigate = useNavigate()

  useEffect(() => {
    authApi.methods()
      .then(data => setMicrosoftEnabled(Boolean(data.microsoft)))
      .catch(() => setMicrosoftEnabled(false))
  }, [])

  const handleMicrosoftLogin = () => {
    window.location.href = '/api/v1/auth/microsoft/login'
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const data = await authApi.login(email, password)
      login(data.role, data.name)
      navigate('/dashboard')
    } catch {
      setError('Email ou senha inválidos')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <div className="flex items-center justify-center gap-3 mb-3">
            <div className="p-3 bg-blue-600/20 rounded-2xl">
              <Thermometer className="w-8 h-8 text-blue-400" />
            </div>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Monitoramento de Refrigeração</h1>
          <p className="text-gray-500 text-sm mt-1">Bemol Varejo</p>
        </div>
        <form onSubmit={handleSubmit} className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl p-8 space-y-5">
          {microsoftEnabled && (
            <>
              <button
                type="button"
                onClick={handleMicrosoftLogin}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-2.5 text-sm font-medium text-gray-900 dark:text-white transition-colors hover:bg-gray-100 dark:hover:bg-gray-700"
              >
                <Building2 className="h-4 w-4" />
                Entrar com Microsoft
              </button>
              <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-gray-200 dark:bg-gray-800" />
                <span className="text-xs text-gray-500">ou</span>
                <div className="h-px flex-1 bg-gray-200 dark:bg-gray-800" />
              </div>
            </>
          )}
          <div className="space-y-2">
            <label className="text-sm text-gray-600 dark:text-gray-400">Email</label>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-4 py-2.5 text-gray-900 dark:text-white text-sm focus:outline-none focus:border-blue-500 transition-colors"
              placeholder="seu@email.com"
              required
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm text-gray-600 dark:text-gray-400">Senha</label>
            <div className="relative">
              <input
                type={showPass ? 'text' : 'password'}
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-4 py-2.5 pr-10 text-gray-900 dark:text-white text-sm focus:outline-none focus:border-blue-500 transition-colors"
                placeholder="••••••••"
                required
              />
              <button type="button" onClick={() => setShowPass(!showPass)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300">
                {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          {error && <p className="text-red-400 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-gray-900 dark:text-white font-medium py-2.5 rounded-lg transition-colors"
          >
            {loading ? 'Entrando...' : 'Entrar'}
          </button>
        </form>
      </div>
    </div>
  )
}
