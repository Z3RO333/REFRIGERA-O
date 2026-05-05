import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/useAuthStore'
import Layout from './components/layout/Layout'
import LoginPage from './pages/Login'
import Dashboard from './pages/Dashboard'
import StoreView from './pages/StoreView'
import FloorMap from './pages/FloorMap'
import Alerts from './pages/Alerts'
import History from './pages/History'
import MaintenanceRanking from './pages/MaintenanceRanking'
import DeviceDetail from './pages/DeviceDetail'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore(s => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
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
