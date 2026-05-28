import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'
import InspectorPanel from '../inspector/InspectorPanel'
import { useWebSocket } from '../../hooks/useWebSocket'
import { useInspectorStore } from '../../store/useInspectorStore'

export default function Layout() {
  useWebSocket()
  const inspectorOpen = useInspectorStore(s => s.open)

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-950 overflow-hidden">
      <Sidebar />
      <div
        className="flex-1 flex flex-col overflow-hidden transition-all duration-300"
        style={{ marginRight: inspectorOpen ? 320 : 0 }}
      >
        <Header />
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
      <InspectorPanel />
    </div>
  )
}
