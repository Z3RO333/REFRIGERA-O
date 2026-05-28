import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useEffect } from 'react'
import { useAuthStore } from './store/useAuthStore'
import { authApi } from './api/client'
import Layout from './components/layout/Layout'
import LoginPage from './pages/Login'
import Dashboard from './pages/Dashboard'
import StoresOverview from './pages/StoresOverview'
import StoreView from './pages/StoreView'
import FloorMap from './pages/FloorMap'
import Alerts from './pages/Alerts'
import History from './pages/History'
import MaintenanceRanking from './pages/MaintenanceRanking'
import DeviceDetail from './pages/DeviceDetail'
import ThermalMapsOverview from './pages/ThermalMapsOverview'
import ThermalComfortMap from './pages/ThermalComfortMap'
import EquipmentOverview from './pages/EquipmentOverview'
import Reports from './pages/Reports'
import ModulePlaceholder from './pages/ModulePlaceholder'
import UsersPage from './pages/Users'
import ActivityLog from './pages/ActivityLog'
import DiagnosticsPage from './pages/DiagnosticsPage'
import AIAnalysisPage from './pages/AIAnalysisPage'
import LogsPage from './pages/LogsPage'
import DigitalTwinPage from './pages/DigitalTwinPage'
import ZoneControlPanel from './pages/ZoneControlPanel'
import PortfolioPage from './pages/PortfolioPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { status, setSession, logout } = useAuthStore()

  useEffect(() => {
    if (status !== 'checking') return
    authApi.me()
      .then(user => setSession(user.role, user.name, user.email))
      .catch(() => logout())
  }, [status, setSession, logout])

  if (status === 'checking') return null
  if (status !== 'authenticated') return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Navigate to="/portfolio" replace />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="cockpit" element={<Dashboard />} />
          <Route path="dashboard" element={<Navigate to="/cockpit" replace />} />
          <Route path="lojas" element={<StoresOverview />} />
          <Route path="lojas/:storeId" element={<StoreView />} />
          <Route path="lojas/:storeId/mapa" element={<FloorMap />} />
          <Route path="lojas/:storeId/mapa/:sectorId" element={<FloorMap />} />
          <Route path="mapa-termico" element={<ThermalMapsOverview />} />
          <Route path="mapa-termico/:storeId" element={<ThermalComfortMap />} />
          <Route path="equipamentos" element={<EquipmentOverview />} />
          <Route path="alertas" element={<Alerts />} />
          <Route path="manutencoes" element={<MaintenanceRanking />} />
          <Route path="fornecedores" element={<ModulePlaceholder title="Fornecedores" columns={['Fornecedor', 'Especialidade', 'SLA', 'Chamados', 'Status']} />} />
          <Route path="relatorios" element={<Reports />} />
          <Route path="configuracoes" element={<ModulePlaceholder title="Configurações" columns={['Regra', 'Escopo', 'Valor', 'Atualizado em']} />} />
          <Route path="usuarios" element={<UsersPage />} />
          <Route path="atividade" element={<ActivityLog />} />
          <Route path="diagnostico" element={<DiagnosticsPage />} />
          <Route path="ia" element={<AIAnalysisPage />} />
          <Route path="ambientes" element={<ZoneControlPanel />} />
          <Route path="zonas" element={<DigitalTwinPage />} />
          <Route path="logs" element={<LogsPage />} />
          <Route path="stores/:storeId" element={<StoreView />} />
          <Route path="stores/:storeId/map/:sectorId" element={<FloorMap />} />
          <Route path="devices/:deviceId" element={<DeviceDetail />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="history/:deviceId" element={<History />} />
          <Route path="maintenance" element={<MaintenanceRanking />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
