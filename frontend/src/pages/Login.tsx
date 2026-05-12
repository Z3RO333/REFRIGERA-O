import { Building2, Thermometer } from 'lucide-react'

export default function LoginPage() {
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
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl p-8">
          <a
            href="/api/v1/auth/microsoft/login"
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-3 text-sm font-medium text-gray-900 dark:text-white transition-colors hover:bg-gray-100 dark:hover:bg-gray-700"
          >
            <Building2 className="h-5 w-5 text-blue-500" />
            Entrar com Microsoft (Bemol)
          </a>
        </div>
      </div>
    </div>
  )
}
