import { Construction } from 'lucide-react'

interface Props {
  title: string
  columns: string[]
}

export default function ModulePlaceholder({ title, columns }: Props) {
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-gray-900 dark:text-white">{title}</h1>
          <p className="text-xs text-gray-500">Módulo operacional</p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-2 text-xs text-gray-500 dark:border-gray-800">
          <Construction className="h-4 w-4" />
          Em implantação
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-xs text-gray-500 dark:border-gray-800">
              {columns.map(column => (
                <th key={column} className="px-5 py-3 text-left">{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colSpan={columns.length} className="py-12 text-center text-sm text-gray-500">
                Sem registros
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
