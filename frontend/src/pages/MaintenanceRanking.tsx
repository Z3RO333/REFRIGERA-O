import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { maintenanceApi } from '../api/client'
import StatusBadge from '../components/StatusBadge'
import type { MaintenanceItem } from '../types'

function ScoreBar({ score }: { score: number }) {
  const color = score > 70 ? '#EF4444' : score > 45 ? '#EAB308' : '#22C55E'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-full h-2">
        <div className="h-2 rounded-full transition-all" style={{ width: `${score}%`, backgroundColor: color }} />
      </div>
      <span className="text-xs font-bold w-8 text-right" style={{ color }}>{Math.round(score)}</span>
    </div>
  )
}

export default function MaintenanceRanking() {
  const navigate = useNavigate()
  const { data: ranking = [], isLoading } = useQuery({
    queryKey: ['maintenance-ranking'],
    queryFn: maintenanceApi.ranking,
    refetchInterval: 120000,
  })

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">Equipamentos ordenados por risco — análise dos últimos 30 dias</p>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-600 text-sm">Calculando ranking...</div>
      ) : ranking.length === 0 ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-600 text-sm">Nenhum equipamento no ranking</div>
      ) : (
        <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-800 text-xs text-gray-500">
                <th className="text-center w-12 px-4 py-3">#</th>
                <th className="text-left px-4 py-3">Equipamento</th>
                <th className="text-left px-3 py-3 hidden md:table-cell">Loja / Setor</th>
                <th className="text-left px-3 py-3">Status</th>
                <th className="text-left px-3 py-3 hidden lg:table-cell">Score</th>
                <th className="text-left px-3 py-3 hidden xl:table-cell">Diagnóstico</th>
                <th className="text-right px-4 py-3">Ação</th>
              </tr>
            </thead>
            <tbody>
              {(ranking as MaintenanceItem[]).map((item) => (
                <tr
                  key={item.device_id}
                  className="border-b border-gray-200/50 dark:border-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors cursor-pointer"
                  onClick={() => navigate(`/devices/${item.device_id}`)}
                >
                  <td className="text-center px-4 py-3">
                    <span className={`text-sm font-bold ${item.rank <= 3 ? 'text-red-400' : 'text-gray-500'}`}>
                      {item.rank}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900 dark:text-white">{item.device_name}</div>
                    <div className="text-xs text-gray-500">{item.btu?.toLocaleString()} BTU</div>
                  </td>
                  <td className="px-3 py-3 hidden md:table-cell">
                    <div className="text-gray-700 dark:text-gray-300">{item.store_name}</div>
                    {item.sector_name && <div className="text-xs text-gray-500">{item.sector_name}</div>}
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge status={item.status} size="sm" />
                  </td>
                  <td className="px-3 py-3 hidden lg:table-cell w-32">
                    <ScoreBar score={item.score} />
                  </td>
                  <td className="px-3 py-3 hidden xl:table-cell">
                    <div className="text-xs text-gray-600 dark:text-gray-400 space-y-0.5">
                      {item.reasons.slice(0, 2).map((r, i) => <div key={i}>• {r}</div>)}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className={`text-xs ${item.score > 70 ? 'text-red-400' : 'text-yellow-400'}`}>
                      {item.recommended_action}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
